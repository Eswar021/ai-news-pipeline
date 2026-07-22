from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from src.pipeline.ingestion.news_collection import run as run_news_collection

from ..io import load_json, write_json
from ..logging import configure_stage_logging
from ..run_context import create_run_context, module_output_dir
from ..state import RunStateStore
from .common import (
    BaseStageRequest,
    StageConfigResolver,
    combine_config_documents,
    current_or_named_context,
    effective_logging_config,
    now_iso,
    project_paths,
    require_matching_config_environment,
    require_ready,
    reusable_config_matches,
    reusable_result,
    write_module_config_snapshot,
)


STAGE = "ingestion"
MODULE = "news_collection"


class IngestionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_mode: Literal["live", "frozen"] = "live"
    resume_completed: bool = True


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    request = BaseStageRequest.model_validate(input_json)
    options = IngestionOptions.model_validate(request.config)
    project_root, output_root, config_path = project_paths(request.paths)
    requested_run_id = (request.run.run_id or "").strip()

    if requested_run_id == "current":
        run_context = current_or_named_context(output_root, "current")
        if request.run.run_profile and run_context.get("run_profile") != request.run.run_profile:
            raise ValueError(
                f"Current run uses profile {run_context.get('run_profile')!r}, "
                f"not requested profile {request.run.run_profile!r}"
            )
        require_matching_config_environment(run_context, request.run.config_environment)
    else:
        run_context = create_run_context(
            project_root=project_root,
            run_profile=request.run.run_profile,
            run_id=requested_run_id or None,
            trigger="runner",
            orchestrator="src.pipeline.orchestration.runner:collect",
            config_path=config_path,
            output_root=output_root,
            config_environment=request.run.config_environment,
        )

    logger = configure_stage_logging(run_context, STAGE, effective_logging_config(run_context))
    state = RunStateStore(run_context)
    state.start_stage(STAGE, [MODULE])
    started = datetime.now().astimezone()
    stage_result_path = Path(run_context["run_dir"]) / "orchestration" / "ingestion_stage_result.json"

    try:
        module_result, result_path, reused = _run_collection(
            run_context=run_context,
            project_root=project_root,
            config_path=config_path,
            options=options,
            logger=logger,
            state=state,
        )
        duration = (datetime.now().astimezone() - started).total_seconds()
        response = {
            "status": "ok",
            "data": {
                "run_id": run_context["run_id"],
                "run_profile": run_context["run_profile"],
                "config_environment": str(run_context.get("config_environment") or "prod"),
                "run_dir": run_context["run_dir"],
                "stage": STAGE,
                "news_collection_result_path": str(result_path),
            },
            "summary": {
                "reused": reused,
                "record_count": int((module_result.get("data") or {}).get("record_count", 0) or 0),
                "duration_seconds": round(duration, 3),
            },
            "handoff": {"ready_for_content": True},
        }
        logger.attach_paths(response, state_path=state.path)
        write_json(stage_result_path, response)
        state.finish_stage(STAGE, status="ok")
        logger.logger.info("COMPLETE stage=%s duration=%.2fs", STAGE, duration)
        return response
    except Exception as exc:
        duration = (datetime.now().astimezone() - started).total_seconds()
        reason = f"{type(exc).__name__}: {exc}"
        response = {
            "status": "failed",
            "data": {
                "run_id": run_context["run_id"],
                "run_profile": run_context["run_profile"],
                "config_environment": str(run_context.get("config_environment") or "prod"),
                "run_dir": run_context["run_dir"],
                "stage": STAGE,
            },
            "summary": {"failure_reason": reason, "duration_seconds": round(duration, 3)},
            "handoff": {"ready_for_content": False},
        }
        logger.attach_paths(response, state_path=state.path)
        write_json(stage_result_path, response)
        state.finish_stage(STAGE, status="failed", failure_reason=reason)
        logger.logger.exception("FAILED stage=%s duration=%.2fs", STAGE, duration)
        return response


def _run_collection(
    *,
    run_context: dict[str, Any],
    project_root: Path,
    config_path: Path,
    options: IngestionOptions,
    logger,
    state: RunStateStore,
) -> tuple[dict[str, Any], Path, bool]:
    resolver = StageConfigResolver(run_context, config_path, options.config_mode)
    shared_document = resolver.shared()
    module_document = resolver.module("ingestion", MODULE)
    authoring_document = combine_config_documents(shared_document, module_document)
    output_dir = module_output_dir(run_context, MODULE)
    result_path = output_dir / f"{MODULE}_result.json"
    input_path = output_dir / f"{MODULE}_input.json"
    config_snapshot_path = output_dir / "config_snapshot.json"

    existing = reusable_result(result_path, allowed_statuses=("ok", "partial")) if options.resume_completed else None
    if existing is not None and reusable_config_matches(
        config_snapshot_path,
        authoring_document,
        mode=options.config_mode,
    ):
        if not input_path.exists():
            raise FileNotFoundError(f"Cannot resume {MODULE}; input envelope is missing: {input_path}")
        module_input = load_json(input_path)
        _write_outputs(output_dir, module_input, existing)
        state.record_module(
            STAGE,
            MODULE,
            status=str(existing.get("status")),
            result_path=str(result_path),
            summary=existing.get("summary", {}),
            reused=True,
        )
        logger.logger.info("REUSE module=%s result=%s", MODULE, result_path)
        require_ready(existing, MODULE, allowed_statuses=("ok", "partial"))
        return existing, result_path, True

    module_input = _build_input(
        run_id=str(run_context["run_id"]),
        run_profile=str(run_context["run_profile"]),
        module_config=module_document.value,
        shared_config=shared_document.value,
    )
    _validate_news_collection_credentials(module_input)
    write_json(input_path, module_input)
    write_module_config_snapshot(
        output_dir,
        stage=STAGE,
        module=MODULE,
        mode=options.config_mode,
        profile_name=str(run_context["run_profile"]),
        document=authoring_document,
        effective_config=module_input["config"],
        environment_name=resolver.environment_name,
    )
    result = logger.run_module(MODULE, run_news_collection, module_input)
    _write_outputs(output_dir, module_input, result)
    state.record_module(
        STAGE,
        MODULE,
        status=str(result.get("status")),
        result_path=str(result_path),
        summary=result.get("summary", {}),
    )
    require_ready(result, MODULE, allowed_statuses=("ok", "partial"))
    return result, result_path, False


def _build_input(
    *,
    run_id: str,
    run_profile: str,
    module_config: dict[str, Any],
    shared_config: dict[str, Any],
) -> dict[str, Any]:
    collection_profile = deepcopy(module_config.get("profile") or {})
    source_groups = deepcopy(module_config.get("source_groups") or {})
    if not collection_profile or not source_groups:
        raise KeyError("news_collection config requires profile and source_groups")
    end = datetime.now().astimezone()
    lookback_hours = int(collection_profile["lookback_hours"])
    window = {
        "start": (end - timedelta(hours=lookback_hours)).isoformat(),
        "end": end.isoformat(),
        "lookback_hours": lookback_hours,
    }
    collectors: dict[str, Any] = {}
    for group in collection_profile["enabled_source_groups"]:
        collector = deepcopy(source_groups[group])
        collector.update(
            {
                "source_group": group,
                "collection_window": window,
                "query_themes": list(collection_profile["query_themes"]),
                "runtime": deepcopy(collection_profile.get("collector_caps", {}).get(group, {})),
            }
        )
        collectors[group] = collector
    return {
        "run": {"run_id": run_id, "generated_at": now_iso()},
        "config": {
            "enabled_source_groups": list(collection_profile["enabled_source_groups"]),
            "query_themes": list(collection_profile["query_themes"]),
            "collectors": collectors,
        },
        "input": {"run_profile": run_profile, "channel": deepcopy(shared_config["channel"])},
    }


def _write_outputs(output_dir: Path, module_input: dict[str, Any], result: dict[str, Any]) -> None:
    write_json(output_dir / "news_collection_input.json", module_input)
    write_json(output_dir / "news_collection_result.json", result)
    write_json(output_dir / "summary.json", result.get("summary", {}))
    data = result.get("data") or {}
    write_json(output_dir / "raw_records.json", data)
    write_json(output_dir / "candidate_ledger.json", {"candidates": data.get("candidate_ledger", [])})


def _validate_news_collection_credentials(module_input: dict[str, Any]) -> None:
    config = module_input.get("config") or {}
    collectors = config.get("collectors") or {}
    missing: list[str] = []
    for group_name in config.get("enabled_source_groups") or []:
        collector = collectors.get(group_name) or {}
        _record_missing_credential(missing, group_name, collector.get("env_keys"))
        for source in collector.get("sources") or []:
            if not source.get("enabled", True):
                continue
            source_name = str(source.get("id") or source.get("name") or "unknown_source")
            _record_missing_credential(missing, f"{group_name}.{source_name}", source.get("env_keys"))
    if missing:
        raise RuntimeError("Missing credentials for enabled news sources: " + "; ".join(missing))


def _record_missing_credential(missing: list[str], source_name: str, env_keys: Any) -> None:
    keys = [str(key).strip() for key in (env_keys or []) if str(key).strip()]
    if keys and not any(os.getenv(key) for key in keys):
        missing.append(f"{source_name} ({' | '.join(keys)})")
