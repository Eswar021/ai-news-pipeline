from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.pipeline.contracts import build_script_provenance

from ...shared.runtimes import build_llm_runtimes, llm_route_summary
from ...shared.utils import story_id
from .assembler import assemble_script
from .checks import check_script_package
from .config import (
    BOOKEND_REVIEWER_PROMPT_MODULE,
    BOOKEND_WRITER_PROMPT_MODULE,
    DIRECTOR_PROMPT_MODULE,
    SCRIPT_APP,
    SCRIPT_LLM_ROLES,
    SECTION_REVIEWER_PROMPT_MODULE,
    SECTION_WRITER_PROMPT_MODULE,
    SOURCE_RESEARCHER_PROMPT_MODULE,
    SUPPORTED_FORMAT,
)
from .contract import ScriptGenerationRequest, ScriptGenerationResponse
from .prompt_loader import load_prompt_bundle
from .research_merge import merge_dossier_into_story
from .writer import generate_deep_dive_script


IST = timezone(timedelta(hours=5, minutes=30))

_PROMPT_MODULES = {
    "source_researcher": SOURCE_RESEARCHER_PROMPT_MODULE,
    "director": DIRECTOR_PROMPT_MODULE,
    "section_writer": SECTION_WRITER_PROMPT_MODULE,
    "section_reviewer": SECTION_REVIEWER_PROMPT_MODULE,
    "bookend_writer": BOOKEND_WRITER_PROMPT_MODULE,
    "bookend_reviewer": BOOKEND_REVIEWER_PROMPT_MODULE,
}


def run(input_json: dict) -> dict:
    request = ScriptGenerationRequest.model_validate(input_json)
    run_id = request.run.run_id
    generated_at = _iso_now()
    config = request.config.model_dump(mode="json")
    video_packaging = request.input.video_packaging
    video_packet = video_packaging.data.video_packet.model_dump(mode="json")
    llm_calls: list[dict[str, Any]] = []

    _validate_deep_dive_packet(video_packet)
    if video_packaging.status != "ok" or not bool(video_packaging.handoff.get("ready_for_script_generation", False)):
        return _failed_response(run_id, generated_at, video_packet, config, "Upstream video_packaging result is not ready for script generation.", llm_calls)

    story = video_packet["stories"][0]

    # Researched deep-dives fold the grounded dossier into the story as synthetic
    # source records (so every dossier fact is citable through the same truth-index
    # the writer already enforces); the dossier's framing becomes the director brief.
    # Absent or un-researched topic_research → the story's own records, unchanged.
    research_brief: dict[str, Any] = {}
    topic_research = request.input.topic_research
    if topic_research is not None and topic_research.data.researched:
        story, research_brief = merge_dossier_into_story(story, topic_research.data.research_dossier or {})

    prompt_bundles = {
        role: load_prompt_bundle(module, config["prompt_version"])
        for role, module in _PROMPT_MODULES.items()
    }
    try:
        llm_runtimes = build_llm_runtimes(config, SCRIPT_LLM_ROLES)
        generated = generate_deep_dive_script(
            video_packet=video_packet,
            story=story,
            config=config,
            prompt_bundles=prompt_bundles,
            llm_runtimes=llm_runtimes,
            llm_calls=llm_calls,
            research_brief=research_brief,
        )
    except Exception as exc:
        return _failed_response(run_id, generated_at, video_packet, config, f"{type(exc).__name__}: {exc}", llm_calls)

    assembled = assemble_script(
        section_plan=generated["section_plan"],
        director=generated["director"],
        angle_segments=generated["angle_segments"],
        bookends=generated["bookends"],
        words_per_minute=int(config["diagnostic_words_per_minute"]),
        title_card_seconds=float(config["title_card_seconds"]),
    )
    script_package = _build_script_package(video_packet, story, generated, assembled)
    script_package["provenance"] = build_script_provenance(script_package, run_id=run_id, script_source="native_app")
    checks = check_script_package(script_package, video_packet, config)
    script_package["checks"] = checks
    status = "ok" if checks["passed"] else "failed"
    failure_reason = "" if status == "ok" else "; ".join(checks["errors"])

    response = ScriptGenerationResponse(
        status=status,
        data={"run_id": run_id, "generated_at": generated_at, "selected_format": SUPPORTED_FORMAT, "script_package": script_package},
        summary=_build_summary(run_id, generated_at, status, script_package, config, llm_calls, failure_reason),
        handoff={"ready_for_metadata_creation": status == "ok", "ready_for_voiceover": status == "ok"},
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _validate_deep_dive_packet(video_packet: dict[str, Any]) -> None:
    if video_packet.get("packet_type") != SUPPORTED_FORMAT or video_packet.get("selected_format") != SUPPORTED_FORMAT:
        raise NotImplementedError(
            f"script_generation deep_dive app only supports packet_type/selected_format '{SUPPORTED_FORMAT}'. "
            f"Received packet_type={video_packet.get('packet_type')!r}, selected_format={video_packet.get('selected_format')!r}."
        )
    if video_packet.get("script_app") != SCRIPT_APP:
        raise ValueError(f"video_packet.script_app must be '{SCRIPT_APP}'. Received {video_packet.get('script_app')!r}.")
    stories = video_packet.get("stories") or []
    if len(stories) != 1:
        raise ValueError(f"deep_dive expects exactly one story to expand; got {len(stories)}")


def _build_script_package(video_packet: dict[str, Any], story: dict[str, Any], generated: dict[str, Any], assembled: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_type": "deep_dive_script",
        "selected_format": SUPPORTED_FORMAT,
        "generation_source": "native_app",
        "duration_policy": _duration_policy(video_packet),
        "topic_story_id": story_id(story),
        "angle_count": len(generated["angle_segments"]),
        "selected_story_ids": list(video_packet.get("selected_story_ids", [])),
        "section_plan": _compact_section_plan(generated["section_plan"]),
        "story_truth_indexes": [generated["story_truth_index"]],
        "story_context_packets": [generated["story_context_packet"]],
        "generation_strategy": assembled["generation_strategy"],
        "episode_direction": assembled["episode_direction"],
        "angle_segments": generated["angle_segments"],
        "bookends": generated["bookends"],
        "source_brief": generated["source_brief"],
        "review": generated["review"],
        "sections": assembled["sections"],
        "full_script": assembled["full_script"],
        "full_script_stats": assembled["full_script_stats"],
        "audio_plan": assembled["audio_plan"],
        "checks": {},
    }


def _compact_section_plan(section_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "section_id": section["section_id"],
            "section_type": section["section_type"],
            "section_order": section["section_order"],
            "story_id": section.get("story_id", ""),
            "angle_id": section.get("angle_id", ""),
            "angle_label": section.get("angle_label", ""),
            "role": section.get("role", ""),
            "writing_guidance": section.get("writing_guidance", {}),
            "allowed_story_ids": section["allowed_story_ids"],
            "allowed_source_record_keys": section["allowed_source_record_keys"],
        }
        for section in section_plan
    ]


def _failed_response(run_id, generated_at, video_packet, config, reason, llm_calls) -> dict:
    script_package = {
        "package_type": "deep_dive_script",
        "selected_format": SUPPORTED_FORMAT,
        "generation_source": "native_app",
        "duration_policy": _duration_policy(video_packet),
        "topic_story_id": "",
        "angle_count": 0,
        "selected_story_ids": list(video_packet.get("selected_story_ids", [])),
        "section_plan": [],
        "story_truth_indexes": [],
        "story_context_packets": [],
        "generation_strategy": "deep_dive_director_plus_per_angle_beats_plus_bookends",
        "sections": [],
        "full_script": "",
        "full_script_stats": {"total_word_count": 0, "estimated_duration_seconds": 0.0, "section_order": [], "beat_count": 0},
        "audio_plan": {"unit_strategy": "one_audio_unit_per_section_with_beat_anchors", "units": []},
        "checks": {"passed": False, "errors": [reason], "warnings": []},
    }
    script_package["provenance"] = build_script_provenance(script_package, run_id=run_id, script_source="native_app")
    response = ScriptGenerationResponse(
        status="failed",
        data={"run_id": run_id, "generated_at": generated_at, "selected_format": SUPPORTED_FORMAT, "script_package": script_package},
        summary=_build_summary(run_id, generated_at, "failed", script_package, config, llm_calls, reason),
        handoff={"ready_for_metadata_creation": False, "ready_for_voiceover": False},
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _build_summary(run_id, generated_at, status, script_package, config, llm_calls, failure_reason) -> dict[str, Any]:
    sections = script_package.get("sections", [])
    stats = script_package.get("full_script_stats", {})
    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "status": status,
        "selected_format": SUPPORTED_FORMAT,
        "section_count": len(sections),
        "story_section_count": sum(1 for section in sections if section.get("section_type") == "story"),
        "angle_count": int(script_package.get("angle_count", 0)),
        "total_word_count": int(stats.get("total_word_count", 0) or 0),
        "estimated_duration_seconds": float(stats.get("estimated_duration_seconds", 0) or 0),
        "llm_call_count": len(llm_calls),
        "failure_reason": failure_reason,
        "llm_runtime": {
            "provider": config.get("provider", ""),
            "model": config.get("model", ""),
            "prompt_version": config.get("prompt_version", ""),
            "worker_count": int(config.get("worker_count", 1)),
            "review_enabled": bool(config.get("review", {}).get("enabled", True)),
            "role_routes": llm_route_summary(config, SCRIPT_LLM_ROLES),
        },
        "content_policy": {
            "mode": "content_driven",
            "timing_source_of_truth": "voiceover",
            "diagnostic_words_per_minute": int(config.get("diagnostic_words_per_minute", 0)),
        },
        "review": script_package.get("review", {}),
        "checks": script_package.get("checks", {}),
    }


def _duration_policy(video_packet: dict[str, Any]) -> dict[str, Any]:
    policy = dict(video_packet.get("duration_policy") or {})
    policy.setdefault("mode", "content_driven")
    policy.setdefault("timing_source_of_truth", "voiceover")
    return policy


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
