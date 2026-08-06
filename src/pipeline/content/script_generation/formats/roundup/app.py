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
    SCRIPT_LLM_ROLES,
    STORY_REVIEWER_PROMPT_MODULE,
    SOURCE_RESEARCHER_PROMPT_MODULE,
    STORY_WRITER_PROMPT_MODULE,
    SUPPORTED_FORMAT,
)
from .contract import ScriptGenerationRequest, ScriptGenerationResponse
from src.pipeline.llm import make_llm
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
        "source_researcher": load_prompt_bundle(SOURCE_RESEARCHER_PROMPT_MODULE, config["prompt_version"]),
        "director": load_prompt_bundle(DIRECTOR_PROMPT_MODULE, config["prompt_version"]),
        "story_writer": load_prompt_bundle(STORY_WRITER_PROMPT_MODULE, config["prompt_version"]),
        "story_reviewer": load_prompt_bundle(STORY_REVIEWER_PROMPT_MODULE, config["prompt_version"]),
        "bookend_writer": load_prompt_bundle(BOOKEND_WRITER_PROMPT_MODULE, config["prompt_version"]),
        "bookend_reviewer": load_prompt_bundle(BOOKEND_REVIEWER_PROMPT_MODULE, config["prompt_version"]),
    }
    try:
        llm_runtimes = _build_llm_runtimes(config)
        generated = generate_roundup_script(
            video_packet=video_packet,
            section_plan=section_plan,
            script_cfg=config,
            prompt_bundles=prompt_bundles,
            llm_runtimes=llm_runtimes,
            llm_calls=llm_calls,
        )
    except Exception as exc:
        return _failed_response(
            run_id=run_id,
            generated_at=generated_at,
            video_packet=video_packet,
            config=config,
            reason=f"{type(exc).__name__}: {exc}",
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
    checks = check_script_package(script_package, video_packet, config)
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
        "story_truth_indexes": generated["story_truth_indexes"],
        "story_context_packets": generated["story_context_packets"],
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
        "story_truth_indexes": [],
        "story_context_packets": [],
        "bookends": {},
        "review": {
            "enabled": bool(config.get("review", {}).get("enabled", True)),
            "story_reviews": [],
            "bookend_reviews": [],
            "review_call_count": 0,
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
    context_packets = [
        packet
        for packet in script_package.get("story_context_packets", [])
        if isinstance(packet, dict)
    ]
    token_usage = {
        "prompt_tokens": sum(int((call.get("usage") or {}).get("prompt_tokens", 0) or 0) for call in llm_calls),
        "completion_tokens": sum(
            int((call.get("usage") or {}).get("completion_tokens", 0) or 0)
            for call in llm_calls
        ),
        "total_tokens": sum(int((call.get("usage") or {}).get("total_tokens", 0) or 0) for call in llm_calls),
    }
    usage_by_model = _usage_by_model(llm_calls)
    worker_count = int(config.get("worker_count", 1))
    parallelized_steps = []
    serial_steps = ["roundup_director", "roundup_bookend_writer"]
    if worker_count > 1:
        parallelized_steps.extend(["roundup_source_researcher", "roundup_story_writer"])
    else:
        serial_steps[:0] = ["roundup_source_researcher", "roundup_story_writer"]
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
            "worker_count": worker_count,
            "review_enabled": bool(config.get("review", {}).get("enabled", True)),
            "max_revision_passes": int(config.get("review", {}).get("max_revision_passes", 1)),
            "retry_policy": config.get("llm_retry", {}),
            "role_routes": _llm_route_summary(config),
            "token_usage": token_usage,
            "usage_by_model": usage_by_model,
            "provider_failover": _provider_failover_summary(llm_calls),
            "source_context": {
                "mode": "complete_records_plus_semantic_brief",
                "story_packet_count": len(context_packets),
                "record_count": sum(
                    int((packet.get("telemetry") or {}).get("record_count", 0))
                    for packet in context_packets
                ),
                "serialized_char_count": sum(
                    int((packet.get("telemetry") or {}).get("serialized_char_count", 0))
                    for packet in context_packets
                ),
                "records_truncated": False,
                "resource_limits": config.get("source_context", {}),
            },
            "parallelized_steps": parallelized_steps,
            "serial_steps": serial_steps,
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


def _build_llm_runtimes(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    runtimes: dict[str, dict[str, Any]] = {}
    for role, role_config in _resolved_llm_configs(config).items():
        runtimes[role] = {
            "config": role_config,
            "llm": make_llm(
                provider=role_config["provider"],
                model=role_config["model"],
                temperature=float(role_config["temperature"]),
                base_url=role_config.get("base_url"),
                max_retries=0,
                provider_options=role_config.get("provider_options"),
            ),
        }
        fallback_config = role_config.get("content_filter_fallback")
        if fallback_config:
            runtimes[role]["content_filter_fallback"] = {
                "config": fallback_config,
                "llm": make_llm(
                    provider=fallback_config["provider"],
                    model=fallback_config["model"],
                    temperature=float(fallback_config["temperature"]),
                    base_url=fallback_config.get("base_url"),
                    max_retries=0,
                    provider_options=fallback_config.get("provider_options"),
                ),
            }
    return runtimes


def _resolved_llm_configs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    default_config = {
        "provider": config["provider"],
        "model": config["model"],
        "temperature": float(config["temperature"]),
        "base_url": config.get("base_url"),
        "provider_options": dict(config.get("provider_options") or {}),
        "structured_output": dict(config.get("structured_output") or {}),
        "llm_retry": dict(config.get("llm_retry") or {}),
        "content_filter_fallback": None,
    }
    overrides = dict(config.get("llm_roles") or {})
    resolved: dict[str, dict[str, Any]] = {}
    for role in SCRIPT_LLM_ROLES:
        override = dict(overrides.get(role) or {})
        if not override:
            resolved[role] = {
                key: dict(value) if isinstance(value, dict) else value
                for key, value in default_config.items()
            }
            continue
        role_config = {
            "provider": override["provider"],
            "model": override["model"],
            "temperature": float(override["temperature"]),
            "base_url": override.get("base_url"),
            "provider_options": dict(override.get("provider_options") or {}),
            "structured_output": dict(override.get("structured_output") or {}),
            "llm_retry": dict(override.get("llm_retry") or default_config["llm_retry"]),
            "content_filter_fallback": _resolved_content_filter_fallback(
                override.get("content_filter_fallback"),
                default_retry=default_config["llm_retry"],
            ),
        }
        resolved[role] = role_config
    return resolved


def _llm_route_summary(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        role: {
            "provider": role_config["provider"],
            "model": role_config["model"],
            "structured_output": role_config["structured_output"],
            "request_timeout_seconds": (
                role_config.get("provider_options") or {}
            ).get("request_timeout_seconds"),
            "content_filter_fallback": _fallback_route_summary(
                role_config.get("content_filter_fallback")
            ),
        }
        for role, role_config in _resolved_llm_configs(config).items()
    }


def _resolved_content_filter_fallback(
    raw_config: Any,
    *,
    default_retry: dict[str, Any],
) -> dict[str, Any] | None:
    if not raw_config:
        return None
    fallback = dict(raw_config)
    return {
        "provider": fallback["provider"],
        "model": fallback["model"],
        "temperature": float(fallback["temperature"]),
        "base_url": fallback.get("base_url"),
        "provider_options": dict(fallback.get("provider_options") or {}),
        "structured_output": dict(fallback.get("structured_output") or {}),
        "llm_retry": dict(fallback.get("llm_retry") or default_retry),
    }


def _fallback_route_summary(fallback: Any) -> dict[str, Any] | None:
    if not fallback:
        return None
    return {
        "trigger": "content_filter",
        "provider": fallback["provider"],
        "model": fallback["model"],
        "structured_output": fallback["structured_output"],
        "request_timeout_seconds": (
            fallback.get("provider_options") or {}
        ).get("request_timeout_seconds"),
    }


def _usage_by_model(llm_calls: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    usage: dict[str, dict[str, int]] = {}
    for call in llm_calls:
        key = f"{call.get('provider', '')}/{call.get('model', '')}"
        bucket = usage.setdefault(
            key,
            {"call_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        call_usage = call.get("usage") or {}
        bucket["call_count"] += 1
        bucket["prompt_tokens"] += int(call_usage.get("prompt_tokens", 0) or 0)
        bucket["completion_tokens"] += int(call_usage.get("completion_tokens", 0) or 0)
        bucket["total_tokens"] += int(call_usage.get("total_tokens", 0) or 0)
    return usage


def _provider_failover_summary(llm_calls: list[dict[str, Any]]) -> dict[str, Any]:
    events = []
    for call in llm_calls:
        metadata = call.get("metadata") or {}
        if metadata.get("route_attempt") != "content_filter_fallback":
            continue
        events.append(
            {
                "module_name": call.get("module_name", ""),
                "story_id": metadata.get("story_id"),
                "trigger": metadata.get("fallback_trigger", "content_filter"),
                "from_provider": metadata.get("fallback_from_provider", ""),
                "from_model": metadata.get("fallback_from_model", ""),
                "to_provider": call.get("provider", ""),
                "to_model": call.get("model", ""),
            }
        )
    return {
        "content_filter_fallback_call_count": len(events),
        "events": events,
    }


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
