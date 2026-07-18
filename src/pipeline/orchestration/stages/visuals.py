from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.pipeline.handoffs.publish_handoff import run as run_publish_handoff
from src.pipeline.visuals.assembly import run as run_video_assembly
from src.pipeline.visuals.asset_catalog import run as run_asset_catalog
from src.pipeline.visuals.asset_resolver import run as run_asset_resolver
from src.pipeline.visuals.media_discovery import run as run_media_discovery
from src.pipeline.visuals.planner import run as run_visual_planner
from src.pipeline.visuals.render import run as run_visual_render
from src.pipeline.visuals.review import run as run_visual_review

from ..artifact_selection import (
    resolve_script_result,
    resolve_voiceover_package,
    validate_visual_plan_result,
)
from ..io import load_json, write_handoff_files, write_json, write_jsonl
from ..logging import configure_stage_logging
from ..state import RunStateStore
from .common import (
    BaseStageRequest,
    StageConfigResolver,
    current_or_named_context,
    effective_logging_config,
    now_iso,
    project_paths,
    rendered_config,
    require_ready,
    reusable_config_matches,
    write_module_config_snapshot,
)


STAGE = "visuals"
MODULES = [
    "asset_catalog",
    "visual_planner",
    "media_discovery",
    "asset_resolver",
    "visual_render",
    "video_assembly",
    "visual_review",
    "publish_handoff",
]

CONFIG_MODULE_KEYS = {
    "asset_catalog": "asset_catalog",
    "visual_planner": "planner",
    "media_discovery": "media_discovery",
    "asset_resolver": "asset_resolver",
    "visual_render": "render",
    "video_assembly": "assembly",
    "visual_review": "review",
    "publish_handoff": "publish_handoff",
}


class VisualsOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_mode: Literal["live", "frozen"] = "live"
    script_source: str = "auto"
    voiceover_variant: str | None = None
    plan_source: str = "generate"
    render_mode: str = "preview"
    render_backend: Literal["remotion", "hyperframes"] | None = None
    selected_scene_ids: list[str] = Field(default_factory=list)
    selected_story_ids: list[str] = Field(default_factory=list)
    resume_completed: bool = True
    from_module: str | None = None
    create_publish_handoff: bool = True

    @field_validator("plan_source")
    @classmethod
    def plan_source_must_be_supported(cls, value: str) -> str:
        if value not in {"generate", "chatgpt"}:
            raise ValueError("plan_source must be generate or chatgpt")
        return value

    @field_validator("render_mode")
    @classmethod
    def render_mode_must_be_supported(cls, value: str) -> str:
        if value not in {"preview", "final"}:
            raise ValueError("render_mode must be preview or final")
        return value

    @field_validator("from_module")
    @classmethod
    def from_module_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in MODULES:
            raise ValueError(f"from_module must be one of {MODULES}")
        return value


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    request = BaseStageRequest.model_validate(input_json)
    options = VisualsOptions.model_validate(request.config)
    project_root, output_root, config_path = project_paths(request.paths)
    run_context = current_or_named_context(output_root, request.run.run_id)
    logger = configure_stage_logging(run_context, STAGE, effective_logging_config(run_context))
    state = RunStateStore(run_context)
    state.start_stage(STAGE, MODULES)
    stage_result_path = Path(run_context["run_dir"]) / "orchestration" / "visuals_stage_result.json"

    try:
        response = _run_stage(
            options=options,
            project_root=project_root,
            output_root=output_root,
            config_path=config_path,
            run_context=run_context,
            logger=logger,
            state=state,
        )
        logger.attach_paths(response, state_path=state.path)
        write_json(stage_result_path, response)
        state.finish_stage(STAGE, status="ok")
        logger.logger.info("COMPLETE stage=%s", STAGE)
        logger.event("stage.completed", status="ok", details=response["summary"])
        return response
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        response = {
            "status": "failed",
            "data": {"run_id": run_context["run_id"], "run_dir": run_context["run_dir"], "stage": STAGE},
            "summary": {"failure_reason": reason},
            "handoff": {"ready_for_manual_review": False},
        }
        logger.attach_paths(response, state_path=state.path)
        write_json(stage_result_path, response)
        state.finish_stage(STAGE, status="failed", failure_reason=reason)
        logger.logger.exception("FAILED stage=%s", STAGE)
        logger.event("stage.failed", status="failed", details={"error": reason})
        return response


def _run_stage(
    *,
    options: VisualsOptions,
    project_root: Path,
    output_root: Path,
    config_path: Path,
    run_context: dict[str, Any],
    logger,
    state: RunStateStore,
) -> dict[str, Any]:
    run_id = str(run_context["run_id"])
    run_dir = Path(run_context["run_dir"])
    config_resolver = StageConfigResolver(run_context, config_path, options.config_mode)
    config_documents = {
        module: config_resolver.module("visuals", config_key)
        for module, config_key in CONFIG_MODULE_KEYS.items()
    }

    video_packaging_result = load_json(run_dir / "video_packaging" / "video_packaging_result.json")
    script_path, script_result = resolve_script_result(
        run_dir=run_dir,
        run_id=run_id,
        source=options.script_source,
    )
    script_provenance = script_result["data"]["script_package"]["provenance"]
    voiceover_path, voiceover_package = resolve_voiceover_package(
        run_dir=run_dir,
        run_id=run_id,
        script_fingerprint=script_provenance["script_fingerprint"],
        variant=options.voiceover_variant,
    )
    voiceover_result_path = voiceover_path.parent / "voiceover_result.json"
    voiceover_result = (
        load_json(voiceover_result_path)
        if voiceover_result_path.exists()
        else {
            "status": "ok",
            "data": {"run_id": run_id, "voiceover_package": voiceover_package},
            "summary": {"audio_path": (voiceover_package.get("audio") or {}).get("full_audio_path", "")},
            "handoff": voiceover_package.get("handoff", {}),
        }
    )
    voiceover_provenance = voiceover_package["provenance"]
    visuals_dir = run_dir / "visuals"
    inputs_dir = run_dir / "inputs" / "visuals"
    write_json(
        run_dir / "orchestration" / "visual_selection.json",
        {
            "script_result_path": str(script_path),
            "script_fingerprint": script_provenance["script_fingerprint"],
            "voiceover_package_path": str(voiceover_path),
            "voiceover_fingerprint": voiceover_provenance["voiceover_fingerprint"],
            "visual_plan_source": options.plan_source,
            "render_mode": options.render_mode,
        },
    )
    from_index = MODULES.index(options.from_module) if options.from_module else None
    if options.resume_completed:
        changed_indexes = [
            index
            for index, module in enumerate(MODULES)
            if from_index is None or index >= from_index
            if _module_result_path(run_dir, options, module).exists()
            and not reusable_config_matches(
                _module_config_snapshot_path(run_dir, options, module),
                config_documents[module],
                mode=options.config_mode,
            )
        ]
        if changed_indexes:
            changed_index = min(changed_indexes)
            if from_index is None or changed_index < from_index:
                from_index = changed_index
            logger.logger.info(
                "CONFIG_CHANGED module=%s mode=%s; rerunning this module and downstream modules",
                MODULES[changed_index],
                options.config_mode,
            )

    asset_catalog_dir = visuals_dir / "asset_catalog"
    asset_catalog_result_path = asset_catalog_dir / "visual_asset_catalog_result.json"
    asset_catalog_result = _reuse_before(
        "asset_catalog",
        asset_catalog_result_path,
        options,
        from_index,
        logger,
        state,
    )
    if asset_catalog_result is None:
        config = rendered_config(
            run_context,
            config_documents["asset_catalog"].value,
            project_root=project_root,
            output_root=output_root,
        )
        config["output_dir"] = str(asset_catalog_dir)
        asset_input = {
            "run": {"run_id": run_id, "generated_at": now_iso()},
            "config": config,
            "input": {"script_generation": script_result, "video_packaging": video_packaging_result},
        }
        write_module_config_snapshot(
            asset_catalog_dir,
            stage=STAGE,
            module="asset_catalog",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=config_documents["asset_catalog"],
            effective_config=config,
        )
        write_json(inputs_dir / f"{run_id}_visual_asset_catalog_input.json", asset_input)
        asset_catalog_result = logger.run_module("asset_catalog", run_asset_catalog, asset_input)
        write_json(asset_catalog_dir / "visual_asset_catalog_input.json", asset_input)
        write_json(asset_catalog_result_path, asset_catalog_result)
        write_json(asset_catalog_dir / "summary.json", asset_catalog_result["summary"])
        _record(state, "asset_catalog", asset_catalog_result_path, asset_catalog_result)
    require_ready(asset_catalog_result, "asset_catalog")
    write_json(
        asset_catalog_dir / "visual_asset_catalog.json",
        asset_catalog_result["data"]["visual_asset_catalog"],
    )

    planning_dir = visuals_dir / "planning" / options.plan_source
    planning_result_path = planning_dir / "visual_scene_planning_result.json"
    planning_result = _reuse_before(
        "visual_planner",
        planning_result_path,
        options,
        from_index,
        logger,
        state,
    )
    if planning_result is None:
        planner_config = rendered_config(
            run_context,
            config_documents["visual_planner"].value,
            project_root=project_root,
            output_root=output_root,
        )
        if options.plan_source == "generate":
            planner_input = {
                "run": {"run_id": run_id, "generated_at": now_iso()},
                "config": planner_config,
                "input": {
                    "video_packaging": video_packaging_result,
                    "script_generation": script_result,
                    "voiceover": voiceover_package,
                    "asset_catalog": asset_catalog_result,
                },
            }
            planning_result = logger.run_module("visual_planner", run_visual_planner, planner_input)
        else:
            planner_input = {"source": str(planning_result_path)}
            if not planning_result_path.exists():
                raise FileNotFoundError(
                    f"Parsed ChatGPT visual plan not found: {planning_result_path}. Run the handoff parser first."
                )
            planning_result = load_json(planning_result_path)
        planning_dir.mkdir(parents=True, exist_ok=True)
        write_module_config_snapshot(
            planning_dir,
            stage=STAGE,
            module="visual_planner",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=config_documents["visual_planner"],
            effective_config=planner_config,
        )
        write_json(planning_dir / "visual_scene_planning_input.json", planner_input)
        write_json(planning_result_path, planning_result)
        write_json(planning_dir / "summary.json", planning_result.get("summary", {}))
        write_jsonl(planning_dir / "llm_calls.jsonl", planning_result.get("llm_calls", []))
        _record(state, "visual_planner", planning_result_path, planning_result)
    require_ready(planning_result, "visual_planner")

    visual_plan = validate_visual_plan_result(
        planning_result,
        run_id=run_id,
        script_fingerprint=script_provenance["script_fingerprint"],
        voiceover_fingerprint=voiceover_provenance["voiceover_fingerprint"],
    )
    write_json(planning_dir / "visual_scene_plan.json", visual_plan)

    media_dir = visuals_dir / "media_discovery"
    media_result_path = media_dir / "visual_media_discovery_result.json"
    media_result = _reuse_before("media_discovery", media_result_path, options, from_index, logger, state)
    if media_result is None:
        config = rendered_config(
            run_context,
            config_documents["media_discovery"].value,
            project_root=project_root,
            output_root=output_root,
        )
        config["output_dir"] = str(media_dir)
        media_input = {
            "run": {"run_id": run_id, "generated_at": now_iso()},
            "config": config,
            "input": {"visual_scene_planning": planning_result},
        }
        write_json(inputs_dir / f"{run_id}_visual_media_discovery_input.json", media_input)
        write_json(media_dir / "visual_media_discovery_input.json", media_input)
        write_module_config_snapshot(
            media_dir,
            stage=STAGE,
            module="media_discovery",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=config_documents["media_discovery"],
            effective_config=config,
        )
        media_result = logger.run_module("media_discovery", run_media_discovery, media_input)
        write_jsonl(media_dir / "llm_calls.jsonl", media_result.get("llm_calls", []))
        _record(state, "media_discovery", media_result_path, media_result)
    require_ready(media_result, "media_discovery", handoff_key="ready_for_visual_asset_resolution")

    resolver_dir = visuals_dir / "asset_resolution"
    resolver_result_path = resolver_dir / "visual_asset_resolution_result.json"
    resolver_result = _reuse_before("asset_resolver", resolver_result_path, options, from_index, logger, state)
    if resolver_result is None:
        config = rendered_config(
            run_context,
            config_documents["asset_resolver"].value,
            project_root=project_root,
            output_root=output_root,
        )
        config["output_dir"] = str(resolver_dir)
        config.setdefault("logos", {})
        if not config["logos"].get("local_logo_dir"):
            config["logos"]["local_logo_dir"] = str(project_root / "src" / "pipeline" / "visuals" / "remotion_engine" / "assets" / "logos")
        resolver_input = {
            "run": {"run_id": run_id, "generated_at": now_iso()},
            "config": config,
            "input": {
                "visual_scene_planning": planning_result,
                "visual_media_discovery": media_result,
            },
        }
        write_json(inputs_dir / f"{run_id}_visual_asset_resolution_input.json", resolver_input)
        write_json(resolver_dir / "visual_asset_resolution_input.json", resolver_input)
        write_module_config_snapshot(
            resolver_dir,
            stage=STAGE,
            module="asset_resolver",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=config_documents["asset_resolver"],
            effective_config=config,
        )
        resolver_result = logger.run_module("asset_resolver", run_asset_resolver, resolver_input)
        _record(state, "asset_resolver", resolver_result_path, resolver_result)
    require_ready(
        resolver_result,
        "asset_resolver",
        allowed_statuses=("ok", "partial"),
        handoff_key="ready_for_visual_render",
    )

    render_dir = visuals_dir / ("render" if options.render_mode == "final" else "render_preview")
    render_result_path = render_dir / "visual_render_result.json"
    render_result = _reuse_before("visual_render", render_result_path, options, from_index, logger, state)
    if render_result is None:
        base = rendered_config(
            run_context,
            config_documents["visual_render"].value,
            project_root=project_root,
            output_root=output_root,
        )
        profiles = base.pop("profiles", {})
        base.pop("active_mode", None)
        if options.render_mode not in profiles:
            raise KeyError(f"visuals.render.profiles is missing {options.render_mode!r}")
        base.update(profiles[options.render_mode])
        if options.render_backend:
            base["backend"] = options.render_backend
        base["output_dir"] = str(render_dir)
        base["render_mode"] = options.render_mode
        base["selected_scene_ids"] = list(options.selected_scene_ids)
        base["selected_story_ids"] = list(options.selected_story_ids)
        if not base.get("remotion_engine_dir"):
            base["remotion_engine_dir"] = str(project_root / "src" / "pipeline" / "visuals" / "remotion_engine")
        if not base.get("hyperframes_engine_dir"):
            base["hyperframes_engine_dir"] = str(project_root / "src" / "pipeline" / "visuals" / "hyperframes_engine")
        render_input = {
            "run": {"run_id": run_id, "generated_at": now_iso()},
            "config": base,
            "input": {"visual_asset_resolution": resolver_result},
        }
        write_json(inputs_dir / f"{run_id}_visual_render_{options.render_mode}_input.json", render_input)
        write_json(render_dir / "visual_render_input.json", render_input)
        write_module_config_snapshot(
            render_dir,
            stage=STAGE,
            module="visual_render",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=config_documents["visual_render"],
            effective_config=base,
        )
        render_result = logger.run_module("visual_render", run_visual_render, render_input)
        _record(state, "visual_render", render_result_path, render_result)
    require_ready(render_result, "visual_render", allowed_statuses=("ok", "partial"))
    render_summary = render_result.get("summary", {})
    if int(render_summary.get("failed_scene_count", 0)):
        raise RuntimeError(f"visual_render failed scenes: {render_summary}")
    if not render_summary.get("render_scope_complete", True):
        raise RuntimeError("Focused scene/story render is not eligible for assembly")

    assembly_dir = visuals_dir / ("assembly" if options.render_mode == "final" else "assembly_preview")
    assembly_result_path = assembly_dir / "video_assembly_result.json"
    assembly_result = _reuse_before("video_assembly", assembly_result_path, options, from_index, logger, state)
    if assembly_result is None:
        config = rendered_config(
            run_context,
            config_documents["video_assembly"].value,
            project_root=project_root,
            output_root=output_root,
        )
        config["output_dir"] = str(assembly_dir)
        assembly_input = {
            "run": {"run_id": run_id, "generated_at": now_iso()},
            "config": config,
            "input": {"visual_render": render_result, "voiceover": voiceover_package},
        }
        write_json(inputs_dir / f"{run_id}_visual_assembly_{options.render_mode}_input.json", assembly_input)
        write_json(assembly_dir / "video_assembly_input.json", assembly_input)
        write_module_config_snapshot(
            assembly_dir,
            stage=STAGE,
            module="video_assembly",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=config_documents["video_assembly"],
            effective_config=config,
        )
        assembly_result = logger.run_module("video_assembly", run_video_assembly, assembly_input)
        _record(state, "video_assembly", assembly_result_path, assembly_result)
    require_ready(assembly_result, "video_assembly", handoff_key="ready_for_manual_review")

    review_dir = visuals_dir / ("review" if options.render_mode == "final" else "review_preview")
    review_result_path = review_dir / "visual_review_result.json"
    review_result = _reuse_before("visual_review", review_result_path, options, from_index, logger, state)
    if review_result is None:
        config = rendered_config(
            run_context,
            config_documents["visual_review"].value,
            project_root=project_root,
            output_root=output_root,
        )
        config["output_dir"] = str(review_dir)
        review_input = {
            "run": {"run_id": run_id, "generated_at": now_iso()},
            "config": config,
            "input": {"video_assembly": assembly_result},
        }
        write_json(inputs_dir / f"{run_id}_visual_review_{options.render_mode}_input.json", review_input)
        write_json(review_dir / "visual_review_input.json", review_input)
        write_module_config_snapshot(
            review_dir,
            stage=STAGE,
            module="visual_review",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=config_documents["visual_review"],
            effective_config=config,
        )
        review_result = logger.run_module("visual_review", run_visual_review, review_input)
        _record(state, "visual_review", review_result_path, review_result)
    require_ready(review_result, "visual_review", handoff_key="ready_for_human_visual_review")

    publish_path = ""
    if options.render_mode == "final" and options.create_publish_handoff:
        metadata_result = load_json(run_dir / "metadata_finalizer" / "metadata_finalizer_result.json")
        publish_input = {
            "run": {"run_id": run_id, "generated_at": now_iso()},
            "config": deepcopy(config_documents["publish_handoff"].value),
            "input": {
                "run_context": run_context,
                "video_packaging": video_packaging_result,
                "script_generation": script_result,
                "metadata_finalizer": metadata_result,
                "voiceover": voiceover_result,
                "video_assembly": assembly_result,
                "visual_review": review_result,
            },
        }
        publish_result = logger.run_module("publish_handoff", run_publish_handoff, publish_input)
        publish_dir = run_dir / "handoffs" / "publish_review"
        write_module_config_snapshot(
            publish_dir,
            stage=STAGE,
            module="publish_handoff",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=config_documents["publish_handoff"],
            effective_config=publish_input["config"],
        )
        write_json(publish_dir / "publish_handoff_input.json", publish_input)
        write_json(publish_dir / "publish_handoff_result.json", publish_result)
        _record(state, "publish_handoff", publish_dir / "publish_handoff_result.json", publish_result)
        require_ready(publish_result, "publish_handoff")
        written = write_handoff_files(publish_result["data"]["publish_handoff_package"]["files"], publish_dir)
        publish_path = written[0] if written else ""

    assembly_summary = assembly_result.get("summary", {})
    render_summary = render_result.get("summary", {})
    return {
        "status": "ok",
        "data": {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "stage": STAGE,
            "visual_plan_path": str(planning_result_path),
            "render_result_path": str(render_result_path),
            "video_assembly_result_path": str(assembly_result_path),
            "final_video_path": assembly_summary.get("final_video_path", ""),
            "contact_sheet_path": (review_result.get("summary") or {}).get("contact_sheet_path", ""),
            "publish_handoff_path": publish_path,
        },
        "summary": {
            "plan_source": options.plan_source,
            "render_mode": options.render_mode,
            "scene_count": (planning_result.get("summary") or {}).get("scene_count", 0),
            "rendered_scene_count": render_summary.get("rendered_scene_count", 0),
            "cached_scene_count": render_summary.get("cached_scene_count", 0),
            "final_duration_seconds": assembly_summary.get("final_duration_seconds", 0),
        },
        "handoff": {"ready_for_manual_review": True, "publish_handoff_created": bool(publish_path)},
    }


def _reuse_before(
    module: str,
    path: Path,
    options: VisualsOptions,
    from_index: int | None,
    logger,
    state: RunStateStore,
) -> dict[str, Any] | None:
    index = MODULES.index(module)
    can_reuse = options.resume_completed and (from_index is None or index < from_index)
    if not can_reuse or not path.exists():
        return None
    result = load_json(path)
    if result.get("status") not in {"ok", "partial"}:
        return None
    logger.logger.info("REUSE module=%s result=%s", module, path)
    logger.event("module.reused", module=module, status=str(result.get("status")), details={"result_path": str(path)})
    state.record_module(
        STAGE,
        module,
        status=str(result.get("status")),
        result_path=str(path),
        summary=result.get("summary", {}),
        reused=True,
    )
    return result


def _record(state: RunStateStore, module: str, path: Path, result: dict[str, Any]) -> None:
    state.record_module(
        STAGE,
        module,
        status=str(result.get("status")),
        result_path=str(path),
        summary=result.get("summary", {}),
    )


def _module_output_dir(run_dir: Path, options: VisualsOptions, module: str) -> Path:
    visuals_dir = run_dir / "visuals"
    if module == "asset_catalog":
        return visuals_dir / "asset_catalog"
    if module == "visual_planner":
        return visuals_dir / "planning" / options.plan_source
    if module == "media_discovery":
        return visuals_dir / "media_discovery"
    if module == "asset_resolver":
        return visuals_dir / "asset_resolution"
    if module == "visual_render":
        return visuals_dir / ("render" if options.render_mode == "final" else "render_preview")
    if module == "video_assembly":
        return visuals_dir / ("assembly" if options.render_mode == "final" else "assembly_preview")
    if module == "visual_review":
        return visuals_dir / ("review" if options.render_mode == "final" else "review_preview")
    if module == "publish_handoff":
        return run_dir / "handoffs" / "publish_review"
    raise KeyError(module)


def _module_result_path(run_dir: Path, options: VisualsOptions, module: str) -> Path:
    names = {
        "asset_catalog": "visual_asset_catalog_result.json",
        "visual_planner": "visual_scene_planning_result.json",
        "media_discovery": "visual_media_discovery_result.json",
        "asset_resolver": "visual_asset_resolution_result.json",
        "visual_render": "visual_render_result.json",
        "video_assembly": "video_assembly_result.json",
        "visual_review": "visual_review_result.json",
        "publish_handoff": "publish_handoff_result.json",
    }
    return _module_output_dir(run_dir, options, module) / names[module]


def _module_config_snapshot_path(run_dir: Path, options: VisualsOptions, module: str) -> Path:
    return _module_output_dir(run_dir, options, module) / "config_snapshot.json"
