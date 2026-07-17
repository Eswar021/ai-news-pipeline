from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config_templates import render_config_templates
from ..io import load_json
from ..run_context import load_run_context


IST = timezone(timedelta(hours=5, minutes=30))


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

