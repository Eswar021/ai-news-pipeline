from __future__ import annotations

from typing import Any

from ...shared.utils import clean_text, safe_int, source_record_keys, story_id, story_title


def build_roundup_section_inputs(video_packet: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    stories = sorted(
        list(video_packet.get("stories", [])),
        key=lambda story: safe_int((story.get("video_segment") or {}).get("segment_order"), 999999),
    )
    if not stories:
        raise ValueError("video_packet.stories must contain selected stories before script generation")

    sections = [_intro_section(video_packet, stories, config)]
    for index, story in enumerate(stories):
        sections.append(
            _story_section(
                video_packet,
                story,
                previous_story=stories[index - 1] if index > 0 else None,
                next_story=stories[index + 1] if index + 1 < len(stories) else None,
                config=config,
            )
        )
    sections.append(_closing_section(video_packet, stories, config))
    return sections


def _intro_section(
    video_packet: dict[str, Any],
    stories: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "section_id": "section_00_intro",
        "section_type": "intro",
        "section_order": 0,
        "story_id": "",
        "story_title": "",
        "role": "",
        "writing_guidance": _writing_guidance(config, "intro"),
        "allowed_story_ids": [story_id(story) for story in stories],
        "allowed_source_record_keys": _all_source_record_keys(stories),
        "prompt_payload": {
            "task": "Write the opening section for a roundup video.",
            "section_goal": (
                "Open with a concrete viewer-facing tension, preview the lead and episode mix, "
                "and promise useful takeaways without mechanically listing every selected story."
            ),
            "writing_guidance": _writing_guidance(config, "intro"),
            "script_style": config["script_style"],
            "video_packet": _video_context(video_packet),
            "selected_stories": stories,
        },
    }


def _story_section(
    video_packet: dict[str, Any],
    story: dict[str, Any],
    *,
    previous_story: dict[str, Any] | None,
    next_story: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    segment = story.get("video_segment") or {}
    order = safe_int(segment.get("segment_order"))
    if order < 1:
        raise ValueError(f"Selected story is missing video_segment.segment_order: {story_id(story)}")

    sid = story_id(story)
    role = clean_text(segment.get("role")) or "major"
    guidance_key = role if role in {"lead", "major", "brief"} else "major"
    guidance = _writing_guidance(config, guidance_key)
    return {
        "section_id": f"section_{order:02d}_{sid}",
        "section_type": "story",
        "section_order": order,
        "story_id": sid,
        "story_title": story_title(story),
        "role": role,
        "writing_guidance": guidance,
        "allowed_story_ids": [sid],
        "allowed_source_record_keys": source_record_keys(story),
        "prompt_payload": {
            "task": "Write one story segment for the roundup video.",
            "section_goal": _story_goal(story),
            "writing_guidance": guidance,
            "script_style": config["script_style"],
            "video_packet": _video_context(video_packet),
            "assigned_story": story,
            "previous_story": _story_preview(previous_story),
            "next_story": _story_preview(next_story),
        },
    }


def _closing_section(
    video_packet: dict[str, Any],
    stories: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "section_id": "section_99_closing",
        "section_type": "closing",
        "section_order": len(stories) + 1,
        "story_id": "",
        "story_title": "",
        "role": "",
        "writing_guidance": _writing_guidance(config, "closing"),
        "allowed_story_ids": [story_id(story) for story in stories],
        "allowed_source_record_keys": _all_source_record_keys(stories),
        "prompt_payload": {
            "task": "Write the closing section for a roundup video.",
            "section_goal": (
                "Land the episode theme in plain language, recap the practical thread, "
                "and end with a short natural signoff."
            ),
            "writing_guidance": _writing_guidance(config, "closing"),
            "script_style": config["script_style"],
            "video_packet": _video_context(video_packet),
            "selected_stories": stories,
        },
    }


def _writing_guidance(config: dict[str, Any], key: str) -> dict[str, Any]:
    guidance = dict((config.get("writing_guidance") or {}).get(key) or {})
    guidance["enforcement"] = "soft_editorial_guidance_only"
    return guidance


def _video_context(video_packet: dict[str, Any]) -> dict[str, Any]:
    duration_policy = dict(video_packet.get("duration_policy") or {})
    if not duration_policy:
        duration_policy = {
            "mode": "content_driven",
            "configured_ceiling_seconds": video_packet.get("target_duration_seconds"),
            "timing_source_of_truth": "voiceover",
        }
    return {
        "packet_type": video_packet.get("packet_type", ""),
        "selected_format": video_packet.get("selected_format", ""),
        "duration_policy": duration_policy,
        "story_count": video_packet.get("story_count", len(video_packet.get("stories", []))),
        "selected_story_ids": list(video_packet.get("selected_story_ids", [])),
        "format_contract": video_packet.get("format_contract", {}),
    }


def _story_preview(story: dict[str, Any] | None) -> dict[str, Any]:
    if not story:
        return {}
    identity = story.get("story_identity") or {}
    segment = story.get("video_segment") or {}
    return {
        "story_id": story_id(story),
        "story_title": story_title(story),
        "role": clean_text(segment.get("role")),
        "primary_entity": clean_text(identity.get("primary_entity")),
        "product_or_project": clean_text(identity.get("product_or_project")),
        "story_action": clean_text(identity.get("story_action")),
    }


def _story_goal(story: dict[str, Any]) -> str:
    identity = story.get("story_identity") or {}
    one_sentence = clean_text(identity.get("one_sentence_story"))
    why = clean_text(identity.get("why_it_matters"))
    parts = [part for part in (one_sentence, why) if part]
    return " ".join(parts) or f"Explain {story_title(story)} clearly and accurately."


def _all_source_record_keys(stories: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for story in stories:
        for key in source_record_keys(story):
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys
