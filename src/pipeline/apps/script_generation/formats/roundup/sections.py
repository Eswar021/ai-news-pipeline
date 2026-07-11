from __future__ import annotations

from typing import Any

from .utils import clean_text, source_record_keys, story_id, story_title, safe_int, word_budget


def build_roundup_section_inputs(video_packet: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    stories = sorted(
        list(video_packet.get("stories", [])),
        key=lambda story: safe_int((story.get("video_segment") or {}).get("segment_order"), 999999),
    )
    if not stories:
        raise ValueError("video_packet.stories must contain selected stories before script generation")

    words_per_minute = int(config["words_per_minute"])
    sections = [_intro_section(video_packet, stories, words_per_minute, config)]
    for index, story in enumerate(stories):
        sections.append(
            _story_section(
                video_packet,
                story,
                words_per_minute,
                previous_story=stories[index - 1] if index > 0 else None,
                next_story=stories[index + 1] if index + 1 < len(stories) else None,
                config=config,
            )
        )
    sections.append(_closing_section(video_packet, stories, words_per_minute, config))
    return sections


def _intro_section(
    video_packet: dict[str, Any],
    stories: list[dict[str, Any]],
    words_per_minute: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    target_seconds = int(video_packet.get("intro_seconds", 0))
    return {
        "section_id": "section_00_intro",
        "section_type": "intro",
        "section_order": 0,
        "story_id": "",
        "story_title": "",
        "role": "",
        "target_seconds": target_seconds,
        "word_budget": word_budget(target_seconds, words_per_minute),
        "allowed_story_ids": [story_id(story) for story in stories],
        "allowed_source_record_keys": _all_source_record_keys(stories),
        "prompt_payload": {
            "task": "Write the opening section for a roundup video.",
            "section_goal": (
                "Open with a concrete viewer-facing tension, preview the lead and the episode story mix, "
                "and promise useful takeaways without mechanically listing every selected story."
            ),
            "script_style": config["script_style"],
            "video_packet": _video_context(video_packet),
            "selected_stories": stories,
        },
    }


def _story_section(
    video_packet: dict[str, Any],
    story: dict[str, Any],
    words_per_minute: int,
    *,
    previous_story: dict[str, Any] | None,
    next_story: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    segment = story.get("video_segment") or {}
    order = safe_int(segment.get("segment_order"))
    if order < 1:
        raise ValueError(f"Selected story is missing video_segment.segment_order: {story_id(story)}")
    target_seconds = safe_int(segment.get("target_seconds"))
    if target_seconds < 1:
        raise ValueError(f"Selected story is missing video_segment.target_seconds: {story_id(story)}")

    sid = story_id(story)
    return {
        "section_id": f"section_{order:02d}_{sid}",
        "section_type": "story",
        "section_order": order,
        "story_id": sid,
        "story_title": story_title(story),
        "role": clean_text(segment.get("role", "")),
        "target_seconds": target_seconds,
        "word_budget": word_budget(target_seconds, words_per_minute),
        "allowed_story_ids": [sid],
        "allowed_source_record_keys": source_record_keys(story),
        "prompt_payload": {
            "task": "Write one story segment for the roundup video.",
            "section_goal": _story_goal(story),
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
    words_per_minute: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    target_seconds = int(video_packet.get("closing_seconds", 0))
    return {
        "section_id": "section_99_closing",
        "section_type": "closing",
        "section_order": len(stories) + 1,
        "story_id": "",
        "story_title": "",
        "role": "",
        "target_seconds": target_seconds,
        "word_budget": word_budget(target_seconds, words_per_minute),
        "allowed_story_ids": [story_id(story) for story in stories],
        "allowed_source_record_keys": _all_source_record_keys(stories),
        "prompt_payload": {
            "task": "Write the closing section for the roundup video.",
            "section_goal": (
                "Land the episode theme in plain language, recap the practical thread, "
                "and end with a short natural signoff."
            ),
            "script_style": config["script_style"],
            "video_packet": _video_context(video_packet),
            "selected_stories": stories,
        },
    }


def _video_context(video_packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_type": video_packet.get("packet_type", ""),
        "selected_format": video_packet.get("selected_format", ""),
        "target_duration_seconds": video_packet.get("target_duration_seconds", 0),
        "intro_seconds": video_packet.get("intro_seconds", 0),
        "closing_seconds": video_packet.get("closing_seconds", 0),
        "segment_seconds": video_packet.get("segment_seconds", 0),
        "story_count": video_packet.get("story_count", len(video_packet.get("stories", []))),
        "selected_story_ids": list(video_packet.get("selected_story_ids", [])),
        "format_contract": video_packet.get("format_contract", {}),
    }


def _story_preview(story: dict[str, Any] | None) -> dict[str, Any]:
    if not story:
        return {}
    segment = story.get("video_segment") or {}
    return {
        "story_id": story_id(story),
        "story_title": story_title(story),
        "rank": story.get("rank"),
        "priority_bucket": story.get("priority_bucket"),
        "role": segment.get("role", ""),
        "story_identity": story.get("story_identity", {}),
    }


def _story_goal(story: dict[str, Any]) -> str:
    role = clean_text((story.get("video_segment") or {}).get("role", "")).lower()
    if role == "lead":
        return (
            "Make this feel worth leading with: start from the practical change, explain why it matters, "
            "then give one grounded caveat or watch item."
        )
    if role == "major":
        return (
            "Give a clear mini-arc: what changed, why it matters now, and what the viewer should be careful about."
        )
    return "Keep it tight: one memorable change, one reason it matters, and one grounded caveat."


def _all_source_record_keys(stories: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for story in stories:
        keys.extend(source_record_keys(story))
    seen: set[str] = set()
    kept: list[str] = []
    for key in keys:
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(key)
    return kept
