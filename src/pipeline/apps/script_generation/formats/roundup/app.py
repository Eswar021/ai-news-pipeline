from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.pipeline.contracts import build_script_provenance

from .assembler import assemble_script
from .checks import check_script_package
from .config import (
    BOOKEND_REVIEWER_PROMPT_MODULE,
    BOOKEND_WRITER_PROMPT_MODULE,
    DIRECTOR_PROMPT_MODULE,
    SCRIPT_APP,
    STORY_REVIEWER_PROMPT_MODULE,
    STORY_WRITER_PROMPT_MODULE,
    SUPPORTED_FORMAT,
)
from .contract import ScriptGenerationRequest, ScriptGenerationResponse
from .llm_client import make_llm
from .prompt_loader import load_prompt_bundle
from .sections import build_roundup_section_inputs
from .writer import generate_roundup_script


IST = timezone(timedelta(hours=5, minutes=30))


def run(input_json: dict) -> dict:
    request = ScriptGenerationRequest.model_validate(input_json)
    run_id = request.run.run_id
    generated_at = _iso_now()
    config = request.config.model_dump(mode="json")
    video_packaging = request.input.video_packaging
    video_packet = video_packaging.data.video_packet.model_dump(mode="json")
    llm_calls: list[dict[str, Any]] = []

    _validate_roundup_packet(video_packet)

    if video_packaging.status != "ok" or not bool(video_packaging.handoff.get("ready_for_script_generation", False)):
        return _failed_response(
            run_id=run_id,
            generated_at=generated_at,
            video_packet=video_packet,
            config=config,
            reason="Upstream video_packaging result is not ready for script generation.",
            llm_calls=llm_calls,
        )

    section_plan = build_roundup_section_inputs(video_packet, config)
    prompt_bundles = {
        "director": load_prompt_bundle(DIRECTOR_PROMPT_MODULE, config["prompt_version"]),
        "story_writer": load_prompt_bundle(STORY_WRITER_PROMPT_MODULE, config["prompt_version"]),
        "story_reviewer": load_prompt_bundle(STORY_REVIEWER_PROMPT_MODULE, config["prompt_version"]),
        "bookend_writer": load_prompt_bundle(BOOKEND_WRITER_PROMPT_MODULE, config["prompt_version"]),
        "bookend_reviewer": load_prompt_bundle(BOOKEND_REVIEWER_PROMPT_MODULE, config["prompt_version"]),
    }
    llm = make_llm(
        provider=config["provider"],
        model=config["model"],
        temperature=float(config["temperature"]),
        base_url=config.get("base_url"),
        max_retries=0,
    )
    generated = generate_roundup_script(
        video_packet=video_packet,
        section_plan=section_plan,
        script_cfg=config,
        prompt_bundles=prompt_bundles,
        llm=llm,
        llm_calls=llm_calls,
    )
    assembled = assemble_script(
        section_plan=section_plan,
        director=generated["director"],
        story_segments=generated["story_segments"],
        bookends=generated["bookends"],
        words_per_minute=int(config["diagnostic_words_per_minute"]),
        title_card_seconds=float(config["title_card_seconds"]),
    )
    script_package = _build_script_package(
        video_packet=video_packet,
        section_plan=section_plan,
        generated=generated,
        assembled=assembled,
    )
    script_package["provenance"] = build_script_provenance(
        script_package,
        run_id=run_id,
        script_source="native_app",
    )
    checks = check_script_package(script_package, video_packet)
    script_package["checks"] = checks
    status = "ok" if checks["passed"] else "failed"
    failure_reason = "" if status == "ok" else "; ".join(checks["errors"])
    response = ScriptGenerationResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": SUPPORTED_FORMAT,
            "script_package": script_package,
        },
        summary=_build_summary(
            run_id=run_id,
            generated_at=generated_at,
            status=status,
            script_package=script_package,
            config=config,
            llm_calls=llm_calls,
            failure_reason=failure_reason,
        ),
        handoff={
            "ready_for_metadata_creation": status == "ok",
            "ready_for_voiceover": status == "ok",
            "ready_for_visual_planning": status == "ok",
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _validate_roundup_packet(video_packet: dict[str, Any]) -> None:
    packet_format = video_packet.get("selected_format") or video_packet.get("packet_type")
    if packet_format != SUPPORTED_FORMAT or video_packet.get("packet_type") != SUPPORTED_FORMAT:
        raise NotImplementedError(
            f"script_generation roundup app only supports packet_type/selected_format '{SUPPORTED_FORMAT}'. "
            f"Received packet_type={video_packet.get('packet_type')!r}, selected_format={packet_format!r}."
        )
    if video_packet.get("script_app") != SCRIPT_APP:
        raise ValueError(
            f"video_packet.script_app must be '{SCRIPT_APP}' for this app. "
            f"Received {video_packet.get('script_app')!r}."
        )
    if not video_packet.get("stories"):
        raise ValueError("video_packet.stories must contain selected stories")


def _build_script_package(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    generated: dict[str, Any],
    assembled: dict[str, Any],
) -> dict[str, Any]:
    return {
        "package_type": "roundup_script",
        "selected_format": SUPPORTED_FORMAT,
        "generation_source": "native_app",
        "duration_policy": _duration_policy(video_packet),
        "story_count": len(video_packet.get("stories", [])),
        "selected_story_ids": list(video_packet.get("selected_story_ids", [])),
        "section_plan": _compact_section_plan(section_plan),
        "generation_strategy": assembled["generation_strategy"],
        "episode_direction": assembled["episode_direction"],
        "story_segments": generated["story_segments"],
        "story_asset_hints": generated["story_asset_hints"],
        "bookends": generated["bookends"],
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
            "story_title": section.get("story_title", ""),
            "role": section.get("role", ""),
            "writing_guidance": section.get("writing_guidance", {}),
            "allowed_story_ids": section["allowed_story_ids"],
            "allowed_source_record_keys": section["allowed_source_record_keys"],
        }
        for section in section_plan
    ]


def _failed_response(
    *,
    run_id: str,
    generated_at: str,
    video_packet: dict[str, Any],
    config: dict[str, Any],
    reason: str,
    llm_calls: list[dict[str, Any]],
) -> dict:
    script_package = {
        "package_type": "roundup_script",
        "selected_format": SUPPORTED_FORMAT,
        "generation_source": "native_app",
        "duration_policy": _duration_policy(video_packet),
        "sections": [],
        "section_plan": [],
        "generation_strategy": "director_plus_per_story_beats_plus_bookends",
        "episode_direction": {},
        "story_segments": [],
        "story_asset_hints": [],
        "bookends": {},
        "review": {
            "enabled": bool(config.get("review", {}).get("enabled", True)),
            "story_reviews": [],
            "bookend_reviews": [],
            "bookend_final_gate_issues": [],
            "revision_count": 0,
        },
        "full_script": "",
        "full_script_stats": {
            "total_word_count": 0,
            "estimated_duration_seconds": 0.0,
            "section_order": [],
            "beat_count": 0,
        },
        "audio_plan": {"unit_strategy": "one_audio_unit_per_section_with_beat_anchors", "units": []},
        "checks": {
            "passed": False,
            "errors": [reason],
            "warnings": [],
        },
    }
    script_package["provenance"] = build_script_provenance(
        script_package,
        run_id=run_id,
        script_source="native_app",
    )
    response = ScriptGenerationResponse(
        status="failed",
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": SUPPORTED_FORMAT,
            "script_package": script_package,
        },
        summary=_build_summary(
            run_id=run_id,
            generated_at=generated_at,
            status="failed",
            script_package=script_package,
            config=config,
            llm_calls=llm_calls,
            failure_reason=reason,
        ),
        handoff={
            "ready_for_metadata_creation": False,
            "ready_for_voiceover": False,
            "ready_for_visual_planning": False,
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _build_summary(
    *,
    run_id: str,
    generated_at: str,
    status: str,
    script_package: dict[str, Any],
    config: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    failure_reason: str,
) -> dict[str, Any]:
    sections = script_package.get("sections", [])
    stats = script_package.get("full_script_stats", {})
    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "status": status,
        "selected_format": SUPPORTED_FORMAT,
        "section_count": len(sections),
        "story_section_count": sum(1 for section in sections if section.get("section_type") == "story"),
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
            "max_revision_passes": int(config.get("review", {}).get("max_revision_passes", 1)),
            "retry_policy": config.get("llm_retry", {}),
            "parallelized_steps": ["roundup_story_writer"] if int(config.get("worker_count", 1)) > 1 else [],
            "serial_steps": [
                "roundup_director",
                "roundup_bookend_writer",
            ],
        },
        "content_policy": {
            "mode": "content_driven",
            "word_counts_are_approval_gates": False,
            "duration_is_an_approval_gate": False,
            "timing_source_of_truth": "voiceover",
            "diagnostic_words_per_minute": int(config.get("diagnostic_words_per_minute", 0)),
            "writing_guidance": config.get("writing_guidance", {}),
        },
        "review": script_package.get("review", {}),
        "checks": script_package.get("checks", {}),
    }


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


def _duration_policy(video_packet: dict[str, Any]) -> dict[str, Any]:
    policy = dict(video_packet.get("duration_policy") or {})
    if not policy:
        policy = {
            "mode": "content_driven",
            "configured_ceiling_seconds": video_packet.get("target_duration_seconds"),
            "timing_source_of_truth": "voiceover",
        }
    policy.setdefault("mode", "content_driven")
    policy.setdefault("timing_source_of_truth", "voiceover")
    return policy
