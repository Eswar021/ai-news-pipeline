"""
Module: run_request_parser
Layer: 0 — Channel Strategy + Run Control
Purpose: Normalize any trigger (manual, scheduled, API) into a clean RunRequest dict with a stable run_id.
"""

from typing import Optional

from config.time_utils import now_project, parse_to_project_timezone
from config.paths import RUNS_DIR

VALID_FORMATS = {"auto", "roundup", "deep_dive", "evergreen", "comparison", "follow_up"}
VALID_DEPTHS = {"light", "standard", "deep"}
VALID_TRIGGER_TYPES = {"manual", "scheduled", "api"}

_MAX_LOOKBACK_HOURS = 720  # 30 days
_MIN_LOOKBACK_HOURS = 1


def _safe_slug(text: str) -> str:
    cleaned = []
    last_was_sep = False
    for ch in (text or "").strip().lower():
        if ch.isalnum():
            cleaned.append(ch)
            last_was_sep = False
        else:
            if not last_was_sep:
                cleaned.append("_")
                last_was_sep = True
    slug = "".join(cleaned).strip("_")
    return slug or "run"


def _build_unique_run_id(
    *,
    dt,
    run_profile: Optional[str],
    lookback_hours: int,
    target_format: str,
) -> str:
    """
    Build a readable run ID that is:
    - timestamped to seconds
    - profile-aware when a named run profile is present
    - collision-safe if a same-second directory already exists
    """
    timestamp = dt.strftime("%Y_%m_%d_%H%M%S")
    profile_or_selector = run_profile or f"{lookback_hours}h_{target_format}"
    base_id = f"run_{timestamp}_{_safe_slug(profile_or_selector)}"

    candidate = base_id
    counter = 2
    while (RUNS_DIR / candidate).exists():
        candidate = f"{base_id}_{counter:02d}"
        counter += 1

    return candidate


def parse_run_request(
    trigger_type: str = "manual",
    requested_at: Optional[str] = None,
    run_profile: Optional[str] = None,
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
        dict with keys: run_id, trigger_type, run_profile, run_mode, target_format,
        lookback_hours, topic_focus, depth, max_videos, requested_at
    """
    defaults = defaults or {}

    # Normalize timestamp
    if requested_at is None:
        dt = now_project()
        requested_at = dt.isoformat()
    else:
        dt = parse_to_project_timezone(requested_at)
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

    run_id = _build_unique_run_id(
        dt=dt,
        run_profile=run_profile,
        lookback_hours=lookback_hours,
        target_format=target_format,
    )

    return {
        "run_id": run_id,
        "trigger_type": trigger_type,
        "run_profile": run_profile,
        "run_mode": "auto",
        "target_format": target_format,
        "lookback_hours": lookback_hours,
        "topic_focus": topic_focus,
        "depth": depth,
        "max_videos": max_videos,
        "requested_at": requested_at,
    }
