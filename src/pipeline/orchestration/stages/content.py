from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from ..io import load_json, write_json, write_jsonl
from ..logging import configure_stage_logging
from ..run_context import module_output_dir
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
    require_non_empty_script,
    require_ready,
    reusable_result,
    reusable_config_matches,
    write_module_config_snapshot,
)


STAGE = "content"
MODULES = [
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

    config_mode: Literal["live", "frozen"] = "live"
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

    run_context = current_or_named_context(output_root, (request.run.run_id or "current").strip())
    if request.run.run_profile and run_context.get("run_profile") != request.run.run_profile:
        raise ValueError(
            f"Selected run uses profile {run_context.get('run_profile')!r}, "
            f"not requested profile {request.run.run_profile!r}"
        )
    require_matching_config_environment(run_context, request.run.config_environment)

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
            config_path=config_path,
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
                "config_environment": str(run_context.get("config_environment") or "prod"),
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
        return response
    except Exception as exc:
        duration = (datetime.now().astimezone() - stage_started).total_seconds()
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
            "handoff": {"ready_for_voiceover": False, "ready_for_visuals": False},
        }
        logger.attach_paths(response, state_path=state.path)
        write_json(stage_result_path, response)
        state.finish_stage(STAGE, status="failed", failure_reason=reason)
        logger.logger.exception("FAILED stage=%s duration=%.2fs", STAGE, duration)
        return response


def _run_modules(
    *,
    run_context: dict[str, Any],
    config_path: Path,
    options: ContentOptions,
    logger,
    state: RunStateStore,
) -> dict[str, Any]:
    config_resolver = StageConfigResolver(run_context, config_path, options.config_mode)
    shared_document = config_resolver.shared()
    shared_config = deepcopy(shared_document.value)
    run_id = str(run_context["run_id"])
    run_profile = str(run_context["run_profile"])
    from_index = MODULES.index(options.from_module) if options.from_module else None
    stop_index = MODULES.index(options.stop_after) if options.stop_after else len(MODULES) - 1
    collection_dir = module_output_dir(run_context, "news_collection")
    collection_result_path = collection_dir / "news_collection_result.json"
    collection_input_path = collection_dir / "news_collection_input.json"
    if not collection_result_path.exists() or not collection_input_path.exists():
        raise FileNotFoundError(
            "Content requires a completed ingestion stage. Run `python3 -m "
            "src.pipeline.orchestration.runner collect --profile <profile>` first."
        )
    collection_result = load_json(collection_result_path)
    require_ready(collection_result, "news_collection", allowed_statuses=("ok", "partial"))
    results: dict[str, dict[str, Any]] = {"news_collection": collection_result}
    inputs: dict[str, dict[str, Any]] = {"news_collection": load_json(collection_input_path)}
    result_paths: dict[str, str] = {"news_collection": str(collection_result_path)}
    completed: list[str] = []
    reused: list[str] = []
    config_changed_upstream = False

    for index, module in enumerate(MODULES):
        if index > stop_index:
            break
        output_dir = module_output_dir(run_context, module)
        result_path = output_dir / f"{module}_result.json"
        input_path = output_dir / f"{module}_input.json"
        config_snapshot_path = output_dir / "config_snapshot.json"
        module_document = config_resolver.module("content", module)
        authoring_document = combine_config_documents(shared_document, module_document)
        can_reuse = (
            options.resume_completed
            and not config_changed_upstream
            and (from_index is None or index < from_index)
        )
        existing = reusable_result(result_path) if can_reuse else None
        explicit_upstream_reuse = from_index is not None and index < from_index
        config_matches = explicit_upstream_reuse or reusable_config_matches(
            config_snapshot_path,
            authoring_document,
            mode=options.config_mode,
        )
        if existing is not None and config_matches:
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
            _require_module_result(module, existing)
            continue
        if can_reuse and existing is not None and not config_matches:
            config_changed_upstream = True
            logger.logger.info(
                "CONFIG_CHANGED module=%s mode=%s; rerunning this module and downstream modules",
                module,
                options.config_mode,
            )

        module_input = _build_input(
            module=module,
            run_id=run_id,
            module_config=module_document.value,
            shared_config=shared_config,
            inputs=inputs,
            results=results,
        )
        function = _module_function(module)
        write_json(input_path, module_input)
        write_module_config_snapshot(
            output_dir,
            stage=STAGE,
            module=module,
            mode=options.config_mode,
            profile_name=run_profile,
            document=authoring_document,
            effective_config=module_input["config"],
            environment_name=config_resolver.environment_name,
        )
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
    module_config: dict[str, Any],
    shared_config: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    run = {"run_id": run_id, "generated_at": now_iso()}
    if module == "evidence_prep":
        config = deepcopy(module_config)
        first_collector = next(iter(inputs["news_collection"]["config"]["collectors"].values()))
        config["collection_window"] = deepcopy(first_collector["collection_window"])
        config["query_themes"] = list(inputs["news_collection"]["config"]["query_themes"])
        return {"run": run, "config": config, "input": {"news_collection": results["news_collection"]}}
    if module == "editorial_triage":
        config = deepcopy(module_config)
        config["channel"] = deepcopy(shared_config["channel"])
        return {
            "run": run,
            "config": config,
            "input": {
                "news_collection": results["news_collection"],
                "evidence_prep": results["evidence_prep"],
            },
        }
    if module == "story_mapping":
        config = deepcopy(module_config)
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
        config = deepcopy(module_config)
        config["channel"] = deepcopy(shared_config["channel"])
        return {"run": run, "config": config, "input": {"story_mapping": results["story_mapping"]}}
    if module == "video_packaging":
        return {
            "run": run,
            "config": deepcopy(module_config),
            "input": {"editorial_selection": results["editorial_selection"]},
        }
    if module == "script_generation":
        return {
            "run": run,
            "config": deepcopy(module_config),
            "input": {"video_packaging": results["video_packaging"]},
        }
    if module == "metadata_creator":
        config = deepcopy(module_config)
        channel = shared_config["channel"]
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
    if module == "evidence_prep":
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
    if module == "editorial_triage":
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
    if module == "evidence_prep":
        from src.pipeline.content.evidence_prep import run
    elif module == "editorial_triage":
        from src.pipeline.content.editorial_triage import run
    elif module == "story_mapping":
        from src.pipeline.content.story_mapping import run
    elif module == "editorial_selection":
        from src.pipeline.content.editorial_selection import run
    elif module == "video_packaging":
        from src.pipeline.content.video_packaging import run
    elif module == "script_generation":
        from src.pipeline.content.script_generation.formats.roundup import run
    else:
        from src.pipeline.content.metadata_creator import run
    return run
