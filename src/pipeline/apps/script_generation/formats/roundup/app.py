from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .checks import build_full_script, check_script_package
from .config import (
    FULL_SCRIPT_PROMPT_MODULE,
    REFLECTION_PROMPT_MODULE,
    REVISION_PROMPT_MODULE,
    SCRIPT_APP,
    STORY_USAGE_PROMPT_MODULE,
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
        "story_usage": load_prompt_bundle(STORY_USAGE_PROMPT_MODULE, config["prompt_version"]),
        "full_script": load_prompt_bundle(FULL_SCRIPT_PROMPT_MODULE, config["prompt_version"]),
        "reflection": load_prompt_bundle(REFLECTION_PROMPT_MODULE, config["prompt_version"]),
        "revision": load_prompt_bundle(REVISION_PROMPT_MODULE, config["prompt_version"]),
    }
    llm = make_llm(
        provider=config["provider"],
        model=config["model"],
        temperature=float(config["temperature"]),
        base_url=config.get("base_url"),
    )
    generated = generate_roundup_script(
        video_packet=video_packet,
        section_plan=section_plan,
        script_cfg=config,
        prompt_bundles=prompt_bundles,
        llm=llm,
        llm_calls=llm_calls,
    )
    sections = generated["sections"]
    full_script = build_full_script(sections, int(config["words_per_minute"]))
    script_package = _build_script_package(
        video_packet=video_packet,
        section_plan=section_plan,
        generated=generated,
        sections=sections,
        full_script=full_script,
    )
    checks = check_script_package(
        script_package,
        video_packet,
        duration_tolerance_seconds=int(config["duration_tolerance_seconds"]),
    )
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
        handoff={"ready_for_metadata_creation": status == "ok"},
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
    sections: list[dict[str, Any]],
    full_script: dict[str, Any],
) -> dict[str, Any]:
    return {
        "package_type": "roundup_script",
        "selected_format": SUPPORTED_FORMAT,
        "generation_source": "native_app",
        "target_duration_seconds": int(video_packet["target_duration_seconds"]),
        "intro_seconds": int(video_packet["intro_seconds"]),
        "closing_seconds": int(video_packet["closing_seconds"]),
        "story_count": len(video_packet.get("stories", [])),
        "selected_story_ids": list(video_packet.get("selected_story_ids", [])),
        "section_plan": _compact_section_plan(section_plan),
        "story_usage_cards": generated["story_usage_cards"],
        "script_strategy": generated.get("script_strategy", ""),
        "revision_notes_applied": generated.get("revision_notes_applied", []),
        "reflection": generated["reflection"],
        "sections": sections,
        "full_script": full_script["narration_text"],
        "full_script_stats": {
            "total_word_count": int(full_script["total_word_count"]),
            "estimated_duration_seconds": float(full_script["estimated_duration_seconds"]),
            "section_order": full_script["section_order"],
        },
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
            "target_seconds": section["target_seconds"],
            "word_budget": section["word_budget"],
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
        "target_duration_seconds": int(video_packet.get("target_duration_seconds", 0) or 0),
        "sections": [],
        "section_plan": [],
        "story_usage_cards": [],
        "script_strategy": "",
        "revision_notes_applied": [],
        "reflection": {
            "enabled": bool(config.get("reflection", {}).get("enabled", True)),
            "iterations": [],
            "revision_count": 0,
            "final_score": None,
        },
        "full_script": "",
        "full_script_stats": {
            "total_word_count": 0,
            "estimated_duration_seconds": 0.0,
            "section_order": [],
        },
        "checks": {
            "passed": False,
            "errors": [reason],
            "warnings": [],
        },
    }
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
        handoff={"ready_for_metadata_creation": False},
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
            "reflection_enabled": bool(config.get("reflection", {}).get("enabled", True)),
            "max_revision_passes": int(config.get("reflection", {}).get("max_revision_passes", 1)),
            "target_score": int(config.get("reflection", {}).get("target_score", 8)),
            "parallelized_steps": ["story_usage_analyzer"] if int(config.get("worker_count", 1)) > 1 else [],
            "serial_steps": [
                "story_usage_analyzer",
                "roundup_full_script_writer",
                "roundup_script_reflector",
                "roundup_script_reviser",
            ],
        },
        "reflection": script_package.get("reflection", {}),
        "checks": script_package.get("checks", {}),
    }


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
