"""
Module: time_window_resolver
Layer: 0 — Channel Strategy + Run Control
Purpose: Compute collection window timestamps from the selected run profile.
"""

from __future__ import annotations

from datetime import timedelta

from config.time_utils import parse_to_project_timezone


def _window_payload(start_dt, end_dt, *, lookback_hours: int | None = None, lookback_days: int | None = None) -> dict:
    payload = {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }
    if lookback_days is not None:
        payload["lookback_days"] = int(lookback_days)
    if lookback_hours is not None:
        payload["lookback_hours"] = int(lookback_hours)
    return payload


def _resolve_window_for_group(
    *,
    base_start,
    base_end,
    base_lookback_hours: int,
    group_override: dict | None,
) -> dict:
    override = group_override or {}

    if "lookback_days" in override:
        days = int(override["lookback_days"])
        return _window_payload(
            base_end - timedelta(days=days),
            base_end,
            lookback_days=days,
        )

    if "lookback_hours" in override:
        hours = int(override["lookback_hours"])
        return _window_payload(
            base_end - timedelta(hours=hours),
            base_end,
            lookback_hours=hours,
        )

    if "extra_lookback_hours" in override:
        hours = base_lookback_hours + int(override["extra_lookback_hours"])
        return _window_payload(
            base_end - timedelta(hours=hours),
            base_end,
            lookback_hours=hours,
        )

    return _window_payload(base_start, base_end, lookback_hours=base_lookback_hours)


def resolve_time_window(
    *,
    requested_at: str,
    lookback_hours: int,
    enabled_source_groups: list[str],
    collection_windows: dict,
    memory_windows: dict,
) -> dict:
    """
    Compute base collection window plus per-source-group windows from a run profile.
    """
    end_dt = parse_to_project_timezone(requested_at)
    start_dt = end_dt - timedelta(hours=lookback_hours)

    window_policy = collection_windows or {}
    overrides = window_policy.get("overrides", {}) or {}

    source_specific_windows = {}
    for group_name in enabled_source_groups:
        source_specific_windows[group_name] = _resolve_window_for_group(
            base_start=start_dt,
            base_end=end_dt,
            base_lookback_hours=lookback_hours,
            group_override=overrides.get(group_name),
        )

    return {
        "collection_window": _window_payload(start_dt, end_dt, lookback_hours=lookback_hours),
        "source_specific_windows": source_specific_windows,
        "memory_windows": memory_windows or {},
    }
