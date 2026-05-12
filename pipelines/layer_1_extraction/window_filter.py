"""
Module: window_filter
Layer: 1 — Source Extraction
Purpose: Apply manifest-driven publish-time windows to Layer 1 raw documents.

This is intentionally lightweight:
- if a document has a parseable published_at, we enforce the window
- if the date is missing or unparseable, we keep the document and report it
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_datetime(raw: str | None) -> datetime | None:
    """
    Parse the common Layer 1 published_at formats into UTC datetimes.
    """
    if not raw or not str(raw).strip():
        return None

    value = str(raw).strip()

    try:
        return _to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    try:
        return _to_utc(parsedate_to_datetime(value))
    except (TypeError, ValueError, IndexError):
        return None


def filter_raw_documents_by_window(
    docs: list[dict],
    *,
    start_at: str | None = None,
    end_at: str | None = None,
) -> tuple[list[dict], dict]:
    """
    Filter Layer 1 raw documents by the manifest window.

    Documents without a usable published_at are kept but counted so the caller can
    surface that the window could not be applied strictly to those records.
    """
    start_dt = parse_datetime(start_at)
    end_dt = parse_datetime(end_at)

    if start_dt is None and end_dt is None:
        return docs, {
            "input_count": len(docs),
            "kept_count": len(docs),
            "outside_window_count": 0,
            "undated_or_unparseable_count": 0,
        }

    kept = []
    outside_window_count = 0
    undated_or_unparseable_count = 0

    for doc in docs:
        raw_date = (
            doc.get("item", {}).get("published_at")
            or doc.get("published_at")
            or ""
        )
        published_dt = parse_datetime(raw_date)

        if published_dt is None:
            kept.append(doc)
            undated_or_unparseable_count += 1
            continue

        if start_dt and published_dt < start_dt:
            outside_window_count += 1
            continue
        if end_dt and published_dt > end_dt:
            outside_window_count += 1
            continue

        kept.append(doc)

    return kept, {
        "input_count": len(docs),
        "kept_count": len(kept),
        "outside_window_count": outside_window_count,
        "undated_or_unparseable_count": undated_or_unparseable_count,
    }


def window_days_for_fetch(window: dict) -> int | None:
    """
    Convert a manifest window into an integer day span for collectors that support
    days_back-style filtering.
    """
    if not window:
        return None

    if window.get("lookback_days"):
        return max(1, int(window["lookback_days"]))

    if window.get("lookback_hours"):
        hours = int(window["lookback_hours"])
        return max(1, (hours + 23) // 24)

    start_dt = parse_datetime(window.get("start"))
    end_dt = parse_datetime(window.get("end"))
    if start_dt and end_dt and end_dt >= start_dt:
        seconds = (end_dt - start_dt).total_seconds()
        days = int((seconds + 86399) // 86400)
        return max(1, days)

    return None
