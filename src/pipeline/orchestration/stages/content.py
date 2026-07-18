from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import os
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from ..io import load_json, write_json, write_jsonl
from ..logging import configure_stage_logging
from ..run_context import create_run_context, module_output_dir
from ..state import RunStateStore
from .common import (
    BaseStageRequest,
    current_or_named_context,
    effective_logging_config,
    now_iso,
    project_paths,
    require_non_empty_script,
    require_ready,
    reusable_result,
)


STAGE = "content"
MODULES = [
    "news_collection",
    "evidence_prep",
    "editorial_triage",
    "story_mapping",
    "editorial_selection",
    "video_packaging",
    "script_generation",
    "metadata_creator",
]


class ContentOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_completed: bool = True
    from_module: str | None = None
    stop_after: str | None = None
    @field_validator("from_module", "stop_after")
    @classmethod
    def module_names_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in MODULES:
            raise ValueError(f"module must be one of {MODULES}")
        return value


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    request = BaseStageRequest.model_validate(input_json)
    options = ContentOptions.model_validate(request.config)
    project_root, output_root, config_path = project_paths(request.paths)

    requested_run_id = (request.run.run_id or "").strip()
    if requested_run_id == "current":
        run_context = current_or_named_context(output_root, "current")
        if request.run.run_profile and run_context.get("run_profile") != request.run.run_profile:
            raise ValueError(
                f"Current run uses profile {run_context.get('run_profile')!r}, "
                f"not requested profile {request.run.run_profile!r}"
            )
    else:
        run_context = create_run_context(
            project_root=project_root,
            run_profile=request.run.run_profile,
            run_id=requested_run_id or None,
            trigger="runner",
            orchestrator="src.pipeline.orchestration.runner:content",
            config_path=config_path,
            output_root=output_root,
        )

    logger = configure_stage_logging(
        run_context,
        STAGE,
        effective_logging_config(run_context),
    )
    state = RunStateStore(run_context)
    state.start_stage(STAGE, MODULES)
    stage_started = datetime.now().astimezone()
    stage_result_path = Path(run_context["run_dir"]) / "orchestration" / "content_stage_result.json"

    try:
        result = _run_modules(
            run_context=run_context,
            project_root=project_root,
            options=options,
            logger=logger,
            state=state,
        )
        duration = (datetime.now().astimezone() - stage_started).total_seconds()
        response = {
            "status": "ok",
            "data": {
                "run_id": run_context["run_id"],
                "run_profile": run_context["run_profile"],
                "run_dir": run_context["run_dir"],
                "stage": STAGE,
                "completed_modules": result["completed_modules"],
                "result_paths": result["result_paths"],
            },
            "summary": {
                "module_count": len(result["completed_modules"]),
                "reused_module_count": len(result["reused_modules"]),
                "reused_modules": result["reused_modules"],
                "duration_seconds": round(duration, 3),
                "stopped_after": result["stopped_after"],
            },
            "handoff": {
                "ready_for_voiceover": "script_generation" in result["completed_modules"],
                "ready_for_visuals": False,
            },
        }
        logger.attach_paths(response, state_path=state.path)
        write_json(stage_result_path, response)
        state.finish_stage(STAGE, status="ok")
        logger.logger.info("COMPLETE stage=%s duration=%.2fs", STAGE, duration)
        logger.event("stage.completed", status="ok", duration_seconds=duration, details=response["summary"])
        return response
    except Exception as exc:
        duration = (datetime.now().astimezone() - stage_started).total_seconds()
        reason = f"{type(exc).__name__}: {exc}"
        response = {
            "status": "failed",
            "data": {
                "run_id": run_context["run_id"],
                "run_profile": run_context["run_profile"],
                "run_dir": run_context["run_dir"],
                "stage": STAGE,
            },
            "summary": {"failure_reason": reason, "duration_seconds": round(duration, 3)},
            "handoff": {"ready_for_voiceover": False, "ready_for_visuals": False},
        }
        logger.attach_paths(response, state_path=state.path)
        write_json(stage_result_path, response)
        state.finish_stage(STAGE, status="failed", failure_reason=reason)
        logger.logger.exception("FAILED stage=%s duration=%.2fs", STAGE, duration)
        logger.event("stage.failed", status="failed", duration_seconds=duration, details={"error": reason})
        return response


def _run_modules(
    *,
    run_context: dict[str, Any],
    project_root: Path,
    options: ContentOptions,
    logger,
    state: RunStateStore,
) -> dict[str, Any]:
    profile = deepcopy(run_context["profile_config"])
    run_id = str(run_context["run_id"])
    run_profile = str(run_context["run_profile"])
    from_index = MODULES.index(options.from_module) if options.from_module else None
    stop_index = MODULES.index(options.stop_after) if options.stop_after else len(MODULES) - 1
    results: dict[str, dict[str, Any]] = {}
    inputs: dict[str, dict[str, Any]] = {}
    result_paths: dict[str, str] = {}
    completed: list[str] = []
    reused: list[str] = []

    for index, module in enumerate(MODULES):
        if index > stop_index:
            break
        output_dir = module_output_dir(run_context, module)
        result_path = output_dir / f"{module}_result.json"
        input_path = output_dir / f"{module}_input.json"
        can_reuse = options.resume_completed and (from_index is None or index < from_index)
        ready_statuses = ("ok", "partial") if module == "news_collection" else ("ok",)
        existing = reusable_result(result_path, allowed_statuses=ready_statuses) if can_reuse else None
        if existing is not None:
            if not input_path.exists():
                raise FileNotFoundError(f"Cannot resume {module}; input envelope is missing: {input_path}")
            results[module] = existing
            inputs[module] = load_json(input_path)
            # Rebuild sidecars from the canonical result so a resumed run cannot
            # retain projections from an earlier failed attempt.
            _write_outputs(module, output_dir, inputs[module], existing, options)
            completed.append(module)
            reused.append(module)
            result_paths[module] = str(result_path)
            state.record_module(
                STAGE,
                module,
                status=str(existing.get("status")),
                result_path=str(result_path),
                summary=existing.get("summary", {}),
                reused=True,
            )
            logger.logger.info("REUSE module=%s result=%s", module, result_path)
            logger.event("module.reused", module=module, status=str(existing.get("status")), details={"result_path": str(result_path)})
            _require_module_result(module, existing)
            continue

        module_input = _build_input(
            module=module,
            run_id=run_id,
            run_profile=run_profile,
            profile=profile,
            project_root=project_root,
            inputs=inputs,
            results=results,
        )
        if module == "news_collection":
            _validate_news_collection_credentials(module_input)
        function = _module_function(module)
        write_json(input_path, module_input)
        module_result = logger.run_module(module, function, module_input)
        _write_outputs(module, output_dir, module_input, module_result, options)
        state.record_module(
            STAGE,
            module,
            status=str(module_result.get("status")),
            result_path=str(result_path),
            summary=module_result.get("summary", {}),
        )
        _require_module_result(module, module_result)
        results[module] = module_result
        inputs[module] = module_input
        completed.append(module)
        result_paths[module] = str(result_path)

    return {
        "completed_modules": completed,
        "reused_modules": reused,
        "result_paths": result_paths,
        "stopped_after": completed[-1] if completed else "",
    }


def _build_input(
    *,
    module: str,
    run_id: str,
    run_profile: str,
    profile: dict[str, Any],
    project_root: Path,
    inputs: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    run = {"run_id": run_id, "generated_at": now_iso()}
    if module == "news_collection":
        app_dir = project_root / "src" / "pipeline" / "apps" / "news_collection"
        profile_config = _load_yaml(app_dir / "profiles.yaml")
        source_config = _load_yaml(app_dir / "source_config.yaml")
        collection_profile = profile_config["profiles"][run_profile]
        end = datetime.now().astimezone()
        lookback_hours = int(collection_profile["lookback_hours"])
        from datetime import timedelta

        window = {
            "start": (end - timedelta(hours=lookback_hours)).isoformat(),
            "end": end.isoformat(),
            "lookback_hours": lookback_hours,
        }
        collectors: dict[str, Any] = {}
        for group in collection_profile["enabled_source_groups"]:
            collector = deepcopy(source_config["source_groups"][group])
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
            "run": run,
            "config": {
                "enabled_source_groups": list(collection_profile["enabled_source_groups"]),
                "query_themes": list(collection_profile["query_themes"]),
                "collectors": collectors,
            },
            "input": {"run_profile": run_profile, "channel": deepcopy(profile["channel"])},
        }
    if module == "evidence_prep":
        config = _module_config(profile, module)
        first_collector = next(iter(inputs["news_collection"]["config"]["collectors"].values()))
        config["collection_window"] = deepcopy(first_collector["collection_window"])
        config["query_themes"] = list(inputs["news_collection"]["config"]["query_themes"])
        return {"run": run, "config": config, "input": {"news_collection": results["news_collection"]}}
    if module == "editorial_triage":
        config = _module_config(profile, module)
        config["channel"] = deepcopy(profile["channel"])
        return {
            "run": run,
            "config": config,
            "input": {
                "news_collection": results["news_collection"],
                "evidence_prep": results["evidence_prep"],
            },
        }
    if module == "story_mapping":
        config = _module_config(profile, module)
        config["collection_window"] = deepcopy(inputs["evidence_prep"]["config"]["collection_window"])
        return {
            "run": run,
            "config": config,
            "input": {
                "evidence_prep": results["evidence_prep"],
                "editorial_triage": results["editorial_triage"],
            },
        }
    if module == "editorial_selection":
        config = _module_config(profile, module)
        config["channel"] = deepcopy(profile["channel"])
        return {"run": run, "config": config, "input": {"story_mapping": results["story_mapping"]}}
    if module == "video_packaging":
        return {
            "run": run,
            "config": _module_config(profile, module),
            "input": {"editorial_selection": results["editorial_selection"]},
        }
    if module == "script_generation":
        return {
            "run": run,
            "config": _module_config(profile, module),
            "input": {"video_packaging": results["video_packaging"]},
        }
    if module == "metadata_creator":
        config = _module_config(profile, module)
        channel = profile["channel"]
        config["channel"] = {
            "channel_name": channel["channel_name"],
            "content_promise": channel.get("content_promise", ""),
        }
        return {
            "run": run,
            "config": config,
            "input": {
                "script_generation": results["script_generation"],
                "video_packaging": results["video_packaging"],
            },
        }
    raise KeyError(module)


def _write_outputs(
    module: str,
    output_dir: Path,
    module_input: dict[str, Any],
    result: dict[str, Any],
    options: ContentOptions,
) -> None:
    del options
    write_json(output_dir / f"{module}_input.json", module_input)
    write_json(output_dir / f"{module}_result.json", result)
    write_json(output_dir / "summary.json", result.get("summary", {}))
    if result.get("llm_calls") is not None:
        write_jsonl(output_dir / "llm_calls.jsonl", result.get("llm_calls", []))
    data = result.get("data") or {}
    if module == "news_collection":
        write_json(output_dir / "raw_records.json", data)
        write_json(output_dir / "candidate_ledger.json", {"candidates": data.get("candidate_ledger", [])})
    elif module == "evidence_prep":
        write_json(output_dir / "prepared_records.json", {"record_count": data.get("record_count", 0), "records": data.get("records", [])})
        write_json(output_dir / "decision_ledger.json", {"decisions": data.get("decision_ledger", [])})
    elif module == "editorial_triage":
        write_json(output_dir / "decisions.json", {"decisions": data.get("decisions", [])})
    elif module == "story_mapping":
        write_json(output_dir / "stories.json", data)
    elif module == "editorial_selection":
        write_json(output_dir / "editorial_slate.json", data.get("editorial_slate", {}))
    elif module == "video_packaging":
        write_json(output_dir / "video_packet.json", data.get("video_packet", {}))
    elif module == "script_generation":
        package = data.get("script_package", {})
        write_json(output_dir / "script_package.json", package)
        script = str(package.get("full_script", "")).strip()
        if script:
            (output_dir / "full_script.txt").write_text(script, encoding="utf-8")
    elif module == "metadata_creator":
        package = data.get("metadata_package", {})
        write_json(output_dir / "metadata_package.json", package)
        write_json(output_dir / "youtube_metadata.json", package.get("youtube_metadata", {}))


def _require_module_result(module: str, result: dict[str, Any]) -> None:
    if module == "news_collection":
        require_ready(result, module, allowed_statuses=("ok", "partial"))
    elif module == "editorial_triage":
        require_ready(result, module, handoff_key="ready_for_story_mapping")
    elif module == "story_mapping":
        require_ready(result, module, handoff_key="ready_for_editorial_selection")
    elif module == "editorial_selection":
        require_ready(result, module, handoff_key="ready_for_video_packaging")
    elif module == "video_packaging":
        require_ready(result, module, handoff_key="ready_for_script_generation")
    elif module == "script_generation":
        require_non_empty_script(result)
    elif module == "metadata_creator":
        require_ready(result, module, handoff_key="ready_for_metadata_finalization")
    else:
        require_ready(result, module)


def _module_function(module: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    if module == "news_collection":
        from src.pipeline.apps.news_collection import run
    elif module == "evidence_prep":
        from src.pipeline.apps.evidence_prep import run
    elif module == "editorial_triage":
        from src.pipeline.apps.editorial_triage import run
    elif module == "story_mapping":
        from src.pipeline.apps.story_mapping import run
    elif module == "editorial_selection":
        from src.pipeline.apps.editorial_selection import run
    elif module == "video_packaging":
        from src.pipeline.apps.video_packaging import run
    elif module == "script_generation":
        from src.pipeline.apps.script_generation.formats.roundup import run
    else:
        from src.pipeline.apps.metadata_creator import run
    return run


def _module_config(profile: dict[str, Any], module: str) -> dict[str, Any]:
    config = deepcopy(profile.get(module) or {})
    if not config:
        raise KeyError(f"Frozen profile is missing config for {module!r}")
    return config


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
            _record_missing_credential(
                missing,
                f"{group_name}.{source_name}",
                source.get("env_keys"),
            )

    if missing:
        raise RuntimeError(
            "Missing credentials for enabled news sources: " + "; ".join(missing)
        )


def _record_missing_credential(
    missing: list[str],
    source_name: str,
    env_keys: Any,
) -> None:
    keys = [str(key).strip() for key in (env_keys or []) if str(key).strip()]
    if keys and not any(os.getenv(key) for key in keys):
        missing.append(f"{source_name} ({' | '.join(keys)})")


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML object at {path}")
    return value
