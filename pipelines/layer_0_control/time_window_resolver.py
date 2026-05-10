"""
Module: time_window_resolver
Layer: 0 — Channel Strategy + Run Control
Purpose: Compute collection window timestamps and source-specific / memory lookback windows.
"""

from datetime import datetime, timedelta, timezone

# Source groups that need a longer or different window than the primary news window.
# Research papers and GitHub signals are not breaking news — a 7-day window is appropriate
# even for a 48h news run. Community signals use a slightly longer window to catch trending
# discussions that may have started before the primary collection window.
_SOURCE_GROUP_WINDOW_OVERRIDES = {
    "research_papers":            {"lookback_days": 7},
    "youtube_podcast_transcripts": {"lookback_days": 7},
    "github_open_source_signals": {"lookback_days": 7},
    "community_signals":          {"extra_lookback_hours": 24},
}

# Memory windows are intentionally much longer than the collection window.
# We check video similarity over 60 days to avoid repeating recent content.
_MEMORY_WINDOWS_BY_FORMAT = {
    "deep_dive": {
        "published_video_similarity_days": 90,
        "entity_context_days": 180,
        "claim_history_days": 365,
        "followup_window_days": 90,
    },
    "evergreen": {
        "published_video_similarity_days": 365,
        "entity_context_days": 365,
        "claim_history_days": 365,
        "followup_window_days": 90,
    },
}
_DEFAULT_MEMORY_WINDOWS = {
    "published_video_similarity_days": 60,
    "entity_context_days": 180,
    "claim_history_days": 365,
    "followup_window_days": 90,
}


def resolve_time_window(
    requested_at: str,
    lookback_hours: int,
    target_format: str = "auto",
) -> dict:
    """
    Computes the primary collection window and source-specific / memory windows.

    Returns:
        dict with: collection_window, source_specific_windows, memory_windows
    """
    end_dt = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
    start_dt = end_dt - timedelta(hours=lookback_hours)

    source_specific_windows = {}

    all_groups = [
        "ai_company_blogs",
        "tech_news_apis",
        "research_papers",
        "youtube_podcast_transcripts",
        "community_signals",
        "github_open_source_signals",
    ]

    for group in all_groups:
        override = _SOURCE_GROUP_WINDOW_OVERRIDES.get(group)
        if override and "lookback_days" in override:
            days = override["lookback_days"]
            group_start = end_dt - timedelta(days=days)
            source_specific_windows[group] = {
                "start": group_start.isoformat(),
                "end": end_dt.isoformat(),
                "lookback_days": days,
            }
        elif override and "extra_lookback_hours" in override:
            extra = override["extra_lookback_hours"]
            group_start = start_dt - timedelta(hours=extra)
            source_specific_windows[group] = {
                "start": group_start.isoformat(),
                "end": end_dt.isoformat(),
                "lookback_hours": lookback_hours + extra,
            }
        else:
            source_specific_windows[group] = {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "lookback_hours": lookback_hours,
            }

    memory_windows = _MEMORY_WINDOWS_BY_FORMAT.get(target_format, _DEFAULT_MEMORY_WINDOWS)

    return {
        "collection_window": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "lookback_hours": lookback_hours,
        },
        "source_specific_windows": source_specific_windows,
        "memory_windows": memory_windows,
    }
