from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

import yaml

from .control_catalog import STAGE_CATALOG, STAGE_ORDER
from .models import RunPlan


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class CommandSpec:
    stage: str
    argv: tuple[str, ...]
    display: str

    def public(self) -> dict[str, str]:
        return {"stage": self.stage, "display": self.display}


@dataclass(frozen=True)
class PlannedRun:
    plan: RunPlan
    commands: tuple[CommandSpec, ...]
    risk_notes: tuple[str, ...]
    requires_provider_confirmation: bool
    requires_final_confirmation: bool

    def public(self) -> dict[str, Any]:
        return {
            "plan": self.plan.model_dump(mode="json"),
            "run_id": self.plan.run_id,
            "commands": [command.public() for command in self.commands],
            "risk_notes": list(self.risk_notes),
            "requires_provider_confirmation": self.requires_provider_confirmation,
            "requires_final_confirmation": self.requires_final_confirmation,
        }


class RunPlanner:
    def __init__(
        self,
        project_root: Path,
        *,
        pipeline_python: str | None = None,
        runner_module: str = "src.pipeline.orchestration.runner",
    ) -> None:
        self.project_root = project_root.resolve()
        self.output_root = (self.project_root / "output").resolve()
        self.runs_root = (self.output_root / "runs").resolve()
        self.config_root = (self.project_root / "src" / "pipeline" / "config").resolve()
        self.manifest_path = self.config_root / "workbench.yaml"
        self.pipeline_python = str(
            Path(
                pipeline_python
                or os.environ.get("RUN_DESK_PIPELINE_PYTHON")
                or sys.executable
            ).expanduser()
        )
        self.runner_module = runner_module

    def capabilities(self) -> dict[str, Any]:
        manifest = self._manifest()
        profiles = manifest.get("profiles") if isinstance(manifest.get("profiles"), dict) else {}
        environments = manifest.get("environments") if isinstance(manifest.get("environments"), dict) else {}
        return {
            "local_only": True,
            "profiles": list(profiles),
            "environments": list(environments) or [str(manifest.get("default_environment") or "prod")],
            "default_profile": str(manifest.get("default_run_profile") or next(iter(profiles), "")),
            "default_environment": str(manifest.get("default_environment") or next(iter(environments), "prod")),
            "stages": [
                {"key": key, **STAGE_CATALOG[key]}
                for key in STAGE_ORDER
            ],
            "config_modes": ["live", "frozen"],
            "synthesis_modes": ["preview", "final"],
            "runtime": self.runtime_status(),
        }

    def runtime_status(self) -> dict[str, Any]:
        command = [self.pipeline_python, "-m", self.runner_module, "--help"]
        try:
            result = subprocess.run(
                command,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "ready": False,
                "python": self._public_python(),
                "reason": f"{type(exc).__name__}: {exc}",
            }
        ready = result.returncode == 0 and "collect" in result.stdout and "visuals" in result.stdout
        reason = "" if ready else (result.stderr or result.stdout or "Runner help failed").strip()[-1200:]
        return {"ready": ready, "python": self._public_python(), "reason": reason}

    def preview(self, requested: RunPlan) -> PlannedRun:
        plan = self._normalize(requested)
        commands = self._commands(plan)
        provider_confirmation = self._provider_confirmation(plan, commands)
        stage_names = {command.stage for command in commands}
        final_confirmation = (
            "voiceover" in stage_names and plan.synthesis_mode == "final"
        ) or ("visuals" in stage_names and not plan.skip_render)
        risks = [
            STAGE_CATALOG[command.stage]["provider_risk"]
            for command in commands
            if STAGE_CATALOG[command.stage]["provider_risk"]
        ]
        if plan.operation != "new":
            risks.append("The selected stage can replace existing downstream artifacts for this run.")
        if plan.config_mode == "live":
            risks.append("Live mode reloads the current authoring YAML before each executed module.")
        else:
            risks.append("Frozen mode reuses the run's initial composed profile.")
        return PlannedRun(
            plan=plan,
            commands=tuple(commands),
            risk_notes=tuple(dict.fromkeys(risks)),
            requires_provider_confirmation=provider_confirmation,
            requires_final_confirmation=final_confirmation,
        )

    def _normalize(self, requested: RunPlan) -> RunPlan:
        data = requested.model_dump(mode="python")
        capabilities = self.capabilities()
        if requested.operation == "new":
            profile = requested.profile or capabilities["default_profile"]
            environment = requested.environment or capabilities["default_environment"]
            if profile not in capabilities["profiles"]:
                raise PlanError(f"Unknown run profile: {profile}")
            if environment not in capabilities["environments"]:
                raise PlanError(f"Unknown config environment: {environment}")
            run_id = requested.run_id or self.suggest_run_id(profile)
            if (self.runs_root / run_id).exists():
                raise PlanError(f"Run already exists: {run_id}")
            data.update({
                "run_id": run_id,
                "profile": profile,
                "environment": environment,
                "from_module": None,
                "stop_after": None,
            })
        else:
            if not requested.run_id:
                raise PlanError("A persisted run is required for resume or retry")
            context = self._run_context(requested.run_id)
            data["profile"] = str(context.get("run_profile") or "")
            data["environment"] = str(context.get("config_environment") or "prod")

        stage = data["target_stage"]
        # A new run always executes collect -> target; run_to_stage only applies to
        # resume/retry, where it extends the plan through a later endpoint.
        if requested.operation == "new":
            data["run_to_stage"] = None
        elif data.get("run_to_stage"):
            if STAGE_ORDER.index(data["run_to_stage"]) < STAGE_ORDER.index(stage):
                raise PlanError("run_to_stage must not come before the selected stage")
        planned = self._planned_stage_names(
            operation=requested.operation,
            target_stage=stage,
            run_to_stage=data.get("run_to_stage"),
        )

        modules = list(STAGE_CATALOG[stage]["modules"])
        # Module boundaries refine a single stage; they are meaningless across a chain.
        if not STAGE_CATALOG[stage]["supports_boundaries"] or len(planned) > 1:
            if data.get("from_module") or data.get("stop_after"):
                raise PlanError(f"{stage} does not support module boundaries in this plan")
            data["from_module"] = None
            data["stop_after"] = None
        else:
            for key in ("from_module", "stop_after"):
                value = data.get(key)
                if value and value not in modules:
                    raise PlanError(f"{key} must be one of {modules}")
            if data.get("from_module") and data.get("stop_after"):
                if modules.index(data["from_module"]) > modules.index(data["stop_after"]):
                    raise PlanError("from_module must not come after stop_after")
        if "visuals" not in planned:
            data["deterministic"] = False
            data["units"] = None
            data["skip_render"] = False
        return RunPlan.model_validate(data)

    def _planned_stage_names(
        self,
        *,
        operation: str,
        target_stage: str,
        run_to_stage: str | None,
    ) -> tuple[str, ...]:
        start = STAGE_ORDER.index(target_stage)
        if operation == "new":
            return tuple(STAGE_ORDER[: start + 1])
        end = STAGE_ORDER.index(run_to_stage) if run_to_stage else start
        return tuple(STAGE_ORDER[start : end + 1])

    def _commands(self, plan: RunPlan) -> list[CommandSpec]:
        stages = self._planned_stage_names(
            operation=plan.operation,
            target_stage=plan.target_stage,
            run_to_stage=plan.run_to_stage,
        )
        return [self._command_for(stage, plan) for stage in stages]

    def _command_for(self, stage: str, plan: RunPlan) -> CommandSpec:
        argv = [
            self.pipeline_python,
            "-m",
            self.runner_module,
            stage,
            "--run-id",
            str(plan.run_id),
            "--environment",
            str(plan.environment),
            "--config-mode",
            plan.config_mode,
        ]
        if stage == "collect":
            argv.extend(["--profile", str(plan.profile)])
            if plan.operation == "retry":
                argv.append("--no-resume")
        elif stage == "content":
            if plan.operation == "retry" and not plan.from_module:
                argv.append("--no-resume")
            if plan.from_module:
                argv.extend(["--from-module", plan.from_module])
            if plan.stop_after:
                argv.extend(["--stop-after", plan.stop_after])
        elif stage == "voiceover":
            argv.extend([
                "--synthesis-mode",
                plan.synthesis_mode,
            ])
            if plan.voiceover_variant:
                argv.extend(["--variant", plan.voiceover_variant])
            if plan.operation == "retry":
                argv.append("--no-resume")
            if plan.skip_metadata_finalization:
                argv.append("--skip-metadata-finalization")
        else:
            if plan.deterministic:
                argv.append("--deterministic")
            if plan.units is not None:
                argv.extend(["--units", str(plan.units)])
            if plan.skip_render:
                argv.append("--skip-render")
        display = " ".join(
            shlex.quote("python3" if index == 0 else value)
            for index, value in enumerate(argv)
        )
        return CommandSpec(stage=stage, argv=tuple(argv), display=display)

    def _provider_confirmation(self, plan: RunPlan, commands: list[CommandSpec]) -> bool:
        stages = {command.stage for command in commands}
        if "content" in stages:
            return True
        if "voiceover" in stages and plan.synthesis_mode == "final":
            return True
        if "visuals" in stages and not plan.deterministic:
            return True
        return False

    def suggest_run_id(self, profile: str) -> str:
        timestamp = datetime.now().astimezone().strftime("%Y_%m_%d_%H%M%S")
        base = f"run_{timestamp}_{profile}"
        candidate = base
        suffix = 2
        while (self.runs_root / candidate).exists():
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def _run_context(self, run_id: str) -> dict[str, Any]:
        path = (self.runs_root / run_id / "run_context.json").resolve()
        try:
            path.relative_to(self.runs_root)
        except ValueError as exc:
            raise PlanError("Run path escapes output/runs") from exc
        if not path.is_file():
            raise PlanError(f"Run context not found: {run_id}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlanError(f"Run context is not readable: {type(exc).__name__}: {exc}") from exc
        if not isinstance(value, dict):
            raise PlanError("Run context must be a JSON object")
        return value

    def _manifest(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            raise PlanError(f"Workbench manifest not found: {self.manifest_path}")
        value = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise PlanError("Workbench manifest must be a YAML mapping")
        return value

    def _public_python(self) -> str:
        name = Path(self.pipeline_python).name
        return name if name.startswith("python") else "configured runtime"
