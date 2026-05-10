"""
Module: run_request_parser
Layer: 0 — Channel Strategy + Run Control
Purpose: Normalize any trigger (manual, scheduled, API) into a clean RunRequest dict with a stable run_id.
"""

from datetime import datetime, timezone
from typing import Optional

VALID_FORMATS = {"auto", "roundup", "deep_dive", "evergreen", "comparison", "follow_up"}
VALID_DEPTHS = {"light", "standard", "deep"}
VALID_TRIGGER_TYPES = {"manual", "scheduled", "api"}

_MAX_LOOKBACK_HOURS = 720  # 30 days
_MIN_LOOKBACK_HOURS = 1


def parse_run_request(
    trigger_type: str = "manual",
    requested_at: Optional[str] = None,
    target_format: str = "auto",
    lookback_hours: Optional[int] = None,
    topic_focus: Optional[str] = None,
    depth: str = "standard",
    max_videos: int = 1,
    defaults: Optional[dict] = None,
) -> dict:
    """
    Converts raw trigger parameters into a normalized RunRequest dict.

    Returns:
        dict with keys: run_id, trigger_type, run_mode, target_format,
        lookback_hours, topic_focus, depth, max_videos, requested_at
    """
    defaults = defaults or {}

    # Normalize timestamp
    if requested_at is None:
        dt = datetime.now(timezone.utc)
        requested_at = dt.isoformat()
    else:
        try:
            dt = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
            requested_at = dt.isoformat()
        except ValueError:
            dt = datetime.now(timezone.utc)
            requested_at = dt.isoformat()

    if trigger_type not in VALID_TRIGGER_TYPES:
        trigger_type = "manual"

    if target_format not in VALID_FORMATS:
        target_format = defaults.get("target_format", "auto")

    if lookback_hours is None:
        lookback_hours = int(defaults.get("lookback_hours", 48))
    lookback_hours = max(_MIN_LOOKBACK_HOURS, min(_MAX_LOOKBACK_HOURS, lookback_hours))

    if depth not in VALID_DEPTHS:
        depth = defaults.get("depth", "standard")

    max_videos = max(1, max_videos)

    if not topic_focus:
        topic_focus = defaults.get("topic_focus", "AI news")

    # run_id format: run_YYYY_MM_DD_Nh_<format>
    date_str = dt.strftime("%Y_%m_%d")
    run_id = f"run_{date_str}_{lookback_hours}h_{target_format}"

    return {
        "run_id": run_id,
        "trigger_type": trigger_type,
        "run_mode": "auto",
        "target_format": target_format,
        "lookback_hours": lookback_hours,
        "topic_focus": topic_focus,
        "depth": depth,
        "max_videos": max_videos,
        "requested_at": requested_at,
    }
