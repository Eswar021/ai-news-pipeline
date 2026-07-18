from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..config import ROUNDUP_FORMAT_CONTRACT, SCRIPT_APP_BY_FORMAT
from ..utils import clean_text, count_values


ALLOWED_ROLES = {"lead", "major", "brief"}


def build_roundup_packet(
    editorial_slate: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    selected = list(editorial_slate.get("selected_stories") or [])
    _validate_selected_slate(selected, config)
    packaged_stories = build_packaged_stories(selected)
    duration_ceiling = config.get("duration_ceiling_seconds")
    if duration_ceiling is None:
        duration_ceiling = config.get("target_duration_seconds")

    packet = {
        "packet_type": "roundup",
        "selected_format": "roundup",
        "script_app": SCRIPT_APP_BY_FORMAT["roundup"],
        "duration_policy": {
            "mode": "content_driven",
            "configured_ceiling_seconds": int(duration_ceiling) if duration_ceiling else None,
            "timing_source_of_truth": "voiceover",
        },
        "story_count": len(packaged_stories),
        "selected_story_ids": [_story_id(story) for story in packaged_stories],
        "stories": packaged_stories,
        "editorial_context": {
            "episode_shape": clean_text(editorial_slate.get("episode_shape")),
            "episode_thesis": clean_text(editorial_slate.get("episode_thesis")),
            "ordering_rationale": clean_text(editorial_slate.get("ordering_rationale")),
            "reserve_story_ids": [
                clean_text(item.get("story_id"))
                for item in editorial_slate.get("reserve", [])
                if clean_text(item.get("story_id"))
            ],
        },
        "format_contract": dict(ROUNDUP_FORMAT_CONTRACT),
    }
    selection_stats = {
        "input_story_count": (
            len(selected)
            + len(editorial_slate.get("reserve", []))
            + len(editorial_slate.get("rejected", []))
        ),
        "candidate_story_count": (
            len(selected)
            + len(editorial_slate.get("reserve", []))
            + len(editorial_slate.get("rejected", []))
        ),
        "selected_story_count": len(selected),
        "rejected_story_count": len(editorial_slate.get("rejected", [])),
        "selection_reason_counts": {},
        "rejected_story_ids": {
            clean_text(item.get("story_id")): [clean_text(item.get("reason"))]
            for item in editorial_slate.get("rejected", [])
            if clean_text(item.get("story_id"))
        },
        "selected_story_ids": [_story_id(story) for story in selected],
        "reserve_story_ids": [
            clean_text(item.get("story_id"))
            for item in editorial_slate.get("reserve", [])
            if clean_text(item.get("story_id"))
        ],
        "selection_authority": "editorial_selection_llm",
    }
    return {
        "packet": packet,
        "selection_stats": selection_stats,
        "role_counts": count_values(
            [story["video_segment"]["role"] for story in packaged_stories]
        ),
    }


def build_packaged_stories(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    packaged = []
    for index, story in enumerate(stories, start=1):
        packaged_story = deepcopy(story)
        story_id = _story_id(story)
        selection = story.get("editorial_selection") or {}
        role = clean_text(selection.get("role"))
        records = story.get("records", [])
        packaged_story["video_segment"] = {
            "segment_id": f"segment_{index:02d}_{story_id}",
            "segment_order": index,
            "role": role,
            "source_record_keys": [
                clean_text(record.get("record_key", ""))
                for record in records
                if clean_text(record.get("record_key", ""))
            ],
        }
        packaged.append(packaged_story)
    return packaged


def _validate_selected_slate(stories: list[dict[str, Any]], config: dict[str, Any]) -> None:
    minimum = int(config["min_stories"])
    maximum = int(config["max_stories"])
    if not minimum <= len(stories) <= maximum:
        raise ValueError(
            f"editorial slate must contain {minimum}..{maximum} selected stories; got {len(stories)}"
        )
    ids = [_story_id(story) for story in stories]
    if any(story_id == "unknown_story" for story_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("editorial slate contains missing or duplicate story IDs")
    roles = [clean_text((story.get("editorial_selection") or {}).get("role")) for story in stories]
    if any(role not in ALLOWED_ROLES for role in roles):
        raise ValueError("editorial slate contains an unsupported or missing story role")
    if roles[0] != "lead" or roles.count("lead") != 1:
        raise ValueError("editorial slate must contain exactly one lead in first position")
    if any(not list(story.get("records") or []) for story in stories):
        raise ValueError("every selected story must carry its source records")


def _story_id(story: dict[str, Any]) -> str:
    return clean_text(story.get("story_id", "")) or "unknown_story"
