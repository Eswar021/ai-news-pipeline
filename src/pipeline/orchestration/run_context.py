from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from src.pipeline.config import ConfigRepository


IST = timezone(timedelta(hours=5, minutes=30))
SCHEMA_VERSION = "pipeline_run_context_v1"


def create_run_context(
    *,
    project_root: Path,
    run_profile: str | None = None,
    run_id: str | None = None,
    trigger: str = "notebook",
    orchestrator: str = "",
    config_path: Path | None = None,
    output_root: Path | None = None,
    config_environment: str | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    output = (output_root or root / "output").resolve()
    requested_run_id = (run_id or "").strip()
    if requested_run_id:
        existing_path = output / "runs" / requested_run_id / "run_context.json"
        if existing_path.exists():
            context = _read_context(existing_path)
            if run_profile and context.get("run_profile") != run_profile:
                raise ValueError(
                    f"Existing run {requested_run_id!r} uses profile {context.get('run_profile')!r}, "
                    f"not requested profile {run_profile!r}"
                )
            existing_environment = str(context.get("config_environment") or "prod")
            if config_environment and existing_environment != config_environment:
                raise ValueError(
                    f"Existing run {requested_run_id!r} uses config environment "
                    f"{existing_environment!r}, not requested environment {config_environment!r}"
                )
            _write_json(output / "current_run.json", context)
            return context

    config_file = (config_path or root / "src" / "pipeline" / "config" / "workbench.yaml").resolve()
    repository = ConfigRepository(config_file, environment=config_environment)
    selected_profile = run_profile or repository.default_profile
    profile_document = repository.profile(selected_profile)

    created_at = datetime.now(IST)
    resolved_run_id = (requested_run_id or f"run_{created_at.strftime('%Y_%m_%d_%H%M%S')}_{selected_profile}").strip()
    if not resolved_run_id:
        raise ValueError("run_id must not be empty")

    run_dir = output / "runs" / resolved_run_id
    context = {
        "schema_version": SCHEMA_VERSION,
        "run_id": resolved_run_id,
        "created_at": created_at.isoformat(),
        "run_profile": selected_profile,
        "config_environment": repository.environment,
        "trigger": trigger,
        "orchestrator": orchestrator,
        "pipeline_config_path": str(config_file.relative_to(root)),
        "pipeline_config_schema_version": repository.schema_version,
        "pipeline_config_sha256": profile_document.sha256,
        "pipeline_config_sources": list(profile_document.source_paths),
        "profile_config": deepcopy(profile_document.value),
        "output_root": str(output),
        "run_dir": str(run_dir),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "run_context.json", context)
    _write_json(output / "current_run.json", context)
    return context


def load_run_context(*, output_root: Path, run_id: str = "current") -> dict[str, Any]:
    output = output_root.resolve()
    path = output / "current_run.json" if run_id == "current" else output / "runs" / run_id / "run_context.json"
    if not path.exists():
        raise FileNotFoundError(f"Run context not found: {path}")
    return _read_context(path)


def module_output_dir(run_context: dict[str, Any], module_name: str, *parts: str) -> Path:
    clean_module = module_name.strip().strip("/")
    if not clean_module or ".." in Path(clean_module).parts:
        raise ValueError(f"Unsafe module_name: {module_name!r}")
    path = Path(run_context["run_dir"]) / clean_module
    for part in parts:
        clean_part = str(part).strip().strip("/")
        if not clean_part or ".." in Path(clean_part).parts:
            raise ValueError(f"Unsafe output path part: {part!r}")
        path /= clean_part
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_context(path: Path) -> dict[str, Any]:
    context = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(context, dict) or context.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported run context at {path}")
    return context
