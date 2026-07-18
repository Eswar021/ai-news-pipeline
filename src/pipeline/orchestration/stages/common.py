from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.pipeline.config import ConfigDocument, ConfigRepository

from ..config_templates import render_config_templates
from ..io import load_json, write_json
from ..run_context import load_run_context


IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class StageConfigResolver:
    run_context: dict[str, Any]
    config_path: Path
    mode: str = "live"

    def __post_init__(self) -> None:
        if self.mode not in {"live", "frozen"}:
            raise ValueError("config_mode must be live or frozen")

    @property
    def profile_name(self) -> str:
        return str(self.run_context["run_profile"])

    def shared(self) -> ConfigDocument:
        if self.mode == "live":
            return ConfigRepository(self.config_path).shared(self.profile_name)
        profile = self._frozen_profile()
        return _frozen_document(
            {
                key: deepcopy(value)
                for key, value in profile.items()
                if key in {"channel", "orchestration"}
            },
            run_context=self.run_context,
        )

    def module(self, stage: str, module: str) -> ConfigDocument:
        if self.mode == "live":
            return ConfigRepository(self.config_path).module(self.profile_name, stage, module)
        profile = self._frozen_profile()
        if stage == "visuals":
            visuals = profile.get("visuals")
            value = visuals.get(module) if isinstance(visuals, dict) else None
        else:
            value = profile.get(module)
        if not isinstance(value, dict) or not value:
            raise KeyError(f"Frozen profile is missing config for {stage}.{module}")
        return _frozen_document(value, run_context=self.run_context)

    def _frozen_profile(self) -> dict[str, Any]:
        profile = self.run_context.get("profile_config")
        if not isinstance(profile, dict):
            raise KeyError("run_context.profile_config is missing")
        return profile


def write_module_config_snapshot(
    output_dir: Path,
    *,
    stage: str,
    module: str,
    mode: str,
    profile_name: str,
    document: ConfigDocument,
    effective_config: dict[str, Any],
) -> Path:
    path = output_dir / "config_snapshot.json"
    write_json(
        path,
        {
            "schema_version": "pipeline_module_config_snapshot_v1",
            "stage": stage,
            "module": module,
            "config_mode": mode,
            "run_profile": profile_name,
            "authoring_config_sha256": document.sha256,
            "source_paths": list(document.source_paths),
            "effective_config_sha256": _json_sha256(effective_config),
            "effective_config": deepcopy(effective_config),
        },
    )
    return path


def combine_config_documents(*documents: ConfigDocument) -> ConfigDocument:
    values = [document.value for document in documents]
    return ConfigDocument(
        value={"documents": deepcopy(values)},
        sha256=_json_sha256(
            {
                "documents": [document.sha256 for document in documents],
                "values": values,
            }
        ),
        source_paths=tuple(
            dict.fromkeys(path for document in documents for path in document.source_paths)
        ),
    )


def reusable_config_matches(
    path: Path,
    document: ConfigDocument,
    *,
    mode: str,
    effective_config: dict[str, Any] | None = None,
) -> bool:
    if not path.exists():
        return False
    snapshot = load_json(path)
    matches = (
        snapshot.get("schema_version") == "pipeline_module_config_snapshot_v1"
        and snapshot.get("config_mode") == mode
        and snapshot.get("authoring_config_sha256") == document.sha256
    )
    if effective_config is not None:
        matches = matches and snapshot.get("effective_config_sha256") == _json_sha256(effective_config)
    return matches


def _frozen_document(value: dict[str, Any], *, run_context: dict[str, Any]) -> ConfigDocument:
    return ConfigDocument(
        value=deepcopy(value),
        sha256=_json_sha256(value),
        source_paths=(
            str(Path(run_context["run_dir"]) / "run_context.json"),
        ),
    )


def _json_sha256(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class RunnerRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    run_profile: str | None = None


class RunnerPaths(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_root: str = "."
    output_root: str = "output"
    pipeline_config_path: str = "src/pipeline/config/workbench.yaml"

    @field_validator("project_root", "output_root", "pipeline_config_path")
    @classmethod
    def paths_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("runner paths must not be empty")
        return value


class BaseStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: RunnerRun = Field(default_factory=RunnerRun)
    paths: RunnerPaths = Field(default_factory=RunnerPaths)
    config: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)


def project_paths(paths: RunnerPaths) -> tuple[Path, Path, Path]:
    root = Path(paths.project_root).expanduser().resolve()
    output = Path(paths.output_root).expanduser()
    if not output.is_absolute():
        output = root / output
    config = Path(paths.pipeline_config_path).expanduser()
    if not config.is_absolute():
        config = root / config
    if not (root / "src" / "pipeline").exists():
        raise FileNotFoundError(f"Canonical pipeline not found under project_root: {root}")
    return root, output.resolve(), config.resolve()


def current_or_named_context(output_root: Path, run_id: str | None) -> dict[str, Any]:
    selected = (run_id or "current").strip() or "current"
    return load_run_context(output_root=output_root, run_id=selected)


def effective_logging_config(run_context: dict[str, Any]) -> dict[str, Any]:
    profile = run_context.get("profile_config") or {}
    orchestration = profile.get("orchestration") if isinstance(profile, dict) else {}
    return deepcopy((orchestration or {}).get("logging") or {})


def rendered_config(
    run_context: dict[str, Any],
    value: dict[str, Any],
    *,
    project_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    context = {
        "PROJECT_ROOT": str(project_root),
        "OUTPUT_ROOT": str(output_root),
        "CACHE_ROOT": str(project_root / ".cache" / "ai_content_creation" / "models"),
        "RUN_ID": str(run_context["run_id"]),
    }
    return render_config_templates(deepcopy(value), context)


def require_ready(
    result: dict[str, Any],
    module: str,
    *,
    allowed_statuses: tuple[str, ...] = ("ok",),
    handoff_key: str | None = None,
) -> None:
    status = str(result.get("status", ""))
    if status not in allowed_statuses:
        raise RuntimeError(f"{module} is not ready. status={status!r}. reason={failure_reason(result)}")
    if handoff_key and not bool((result.get("handoff") or {}).get(handoff_key)):
        raise RuntimeError(
            f"{module} is not ready. status={status!r}. "
            f"reason={failure_reason(result) or f'handoff.{handoff_key} is false'}"
        )


def require_non_empty_script(result: dict[str, Any]) -> str:
    require_ready(result, "script_generation", handoff_key="ready_for_metadata_creation")
    package = (result.get("data") or {}).get("script_package") or {}
    full_script = str(package.get("full_script", "")).strip()
    if not full_script:
        raise RuntimeError("script_generation produced an empty script_package.full_script")
    sections = package.get("sections") or []
    if not sections or any(not section.get("beats") for section in sections if isinstance(section, dict)):
        raise RuntimeError("script_generation did not produce canonical section-aware beats")
    return full_script


def failure_reason(result: dict[str, Any]) -> str:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    return str(
        summary.get("failure_reason")
        or summary.get("error")
        or result.get("reason")
        or "No failure reason provided."
    )


def reusable_result(path: Path, *, allowed_statuses: tuple[str, ...] = ("ok",)) -> dict[str, Any] | None:
    if not path.exists():
        return None
    result = load_json(path)
    return result if result.get("status") in allowed_statuses else None


def now_iso() -> str:
    return datetime.now(IST).isoformat()
