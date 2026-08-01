from __future__ import annotations

from typing import Any

from ..config import DEEP_DIVE_FORMAT_CONTRACT, SCRIPT_APP_BY_FORMAT
from ..utils import clean_text, count_values
from .roundup import build_packaged_stories


def build_deep_dive_packet(
    editorial_slate: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Package a single story for a deep-dive video.

    Reuses the upstream roundup editorial slate and expands ONE story (the lead
    by default). The script-generation deep_dive app plans the angle sections
    from this story's complete records; packaging stays deterministic.
    """
    selected = list(editorial_slate.get("selected_stories") or [])
    chosen = _select_story(selected, config)
    packaged_stories = build_packaged_stories([chosen]) if chosen else []
    _validate_packaged(packaged_stories)

    duration_ceiling = config.get("duration_ceiling_seconds")

    packet = {
        "packet_type": "deep_dive",
        "selected_format": "deep_dive",
        "script_app": SCRIPT_APP_BY_FORMAT["deep_dive"],
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
            # Stories not expanded remain available for other derived formats.
            "unexpanded_selected_story_ids": [
                _story_id(story) for story in selected if _story_id(story) not in {_story_id(s) for s in packaged_stories}
            ],
        },
        "format_contract": dict(DEEP_DIVE_FORMAT_CONTRACT),
    }
    selection_stats = {
        "input_story_count": (
            len(selected)
            + len(editorial_slate.get("reserve", []))
            + len(editorial_slate.get("rejected", []))
        ),
        "candidate_story_count": len(selected),
        "selected_story_count": len(packaged_stories),
        "rejected_story_count": len(editorial_slate.get("rejected", [])),
        "selection_reason_counts": {},
        "rejected_story_ids": {},
        "selected_story_ids": [_story_id(story) for story in packaged_stories],
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


def _select_story(
    selected: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Choose the story to expand. Default: the lead (first with role 'lead',
    else the first selected). Config `story_selection` gates the strategy so it
    stays config-driven rather than hardcoded to position."""
    if not selected:
        return None
    strategy = clean_text(config.get("story_selection")) or "lead"
    if strategy == "lead":
        for story in selected:
            if clean_text((story.get("editorial_selection") or {}).get("role")) == "lead":
                return story
        return selected[0]
    return selected[0]


def _validate_packaged(stories: list[dict[str, Any]]) -> None:
    if len(stories) != 1:
        raise ValueError(f"deep_dive requires exactly one story to expand; got {len(stories)}")
    story = stories[0]
    if _story_id(story) == "unknown_story":
        raise ValueError("deep_dive selected story is missing a story_id")
    if not list(story.get("records") or []):
        raise ValueError("deep_dive story must carry its source records")


def _story_id(story: dict[str, Any]) -> str:
    return clean_text(story.get("story_id", "")) or "unknown_story"
