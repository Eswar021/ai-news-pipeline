"""
Upsert performance records for published YouTube videos.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def _retention_quality(avd: float | None) -> str:
    if avd is None:
        return "unknown"
    if avd >= 300:
        return "excellent"
    if avd >= 180:
        return "good"
    if avd >= 90:
        return "fair"
    return "weak"


def _engagement_quality(likes: int | None, comments: int | None, views: int | None) -> str:
    if views in (None, 0):
        return "unknown"
    likes = likes or 0
    comments = comments or 0
    engagement_rate = (likes + comments) / views
    if engagement_rate >= 0.06:
        return "excellent"
    if engagement_rate >= 0.03:
        return "good"
    if engagement_rate >= 0.01:
        return "fair"
    return "weak"


def _positive_signals(record: dict) -> list[str]:
    perf = record.get("performance", {})
    attrs = record.get("content_attributes", {})
    signals = []

    if perf.get("views_48h") and perf["views_48h"] >= 10000:
        signals.append("strong 48-hour view velocity")
    if perf.get("ctr") and perf["ctr"] >= 0.06:
        signals.append("title and thumbnail achieved strong CTR")
    if perf.get("average_view_duration_seconds") and perf["average_view_duration_seconds"] >= 180:
        signals.append("viewer retention was strong")

    if attrs.get("format") and perf.get("views_48h"):
        signals.append(f"{attrs['format']} format has real performance data")
    if attrs.get("topics"):
        signals.append(f"{attrs['topics'][0]} topic now has published performance history")
    if attrs.get("title_angle"):
        signals.append(f"{attrs['title_angle']} title angle now has performance history")

    return signals


def upsert_record(
    memory_dir: Path,
    video_record: dict,
    analytics_payload: dict,
    editorial_record: dict | None = None,
) -> dict:
    path = memory_dir / "performance_memory.jsonl"
    existing = _load_jsonl(path)
    existing_map = {
        rec.get("video_id", ""): rec
        for rec in existing
        if rec.get("video_id")
    }

    video_id = video_record["video_id"]
    publishing = video_record.get("publishing", {})
    coverage = video_record.get("coverage", {})
    perf = analytics_payload.get("performance", {})

    approved_angles = (
        (editorial_record or {}).get("titles", {}).get("approved_title_angles", [])
    )
    title_angle = approved_angles[0].get("angle_type", "") if approved_angles else ""
    hook_type = (editorial_record or {}).get("hook", {}).get("hook_type", "")

    record = {
        "video_id": video_id,
        "published_video_id": publishing.get("youtube_video_id", ""),
        "channel_id": publishing.get("channel_id", ""),
        "published_at": video_record.get("timestamps", {}).get("published_at"),
        "collected_at": analytics_payload.get("collected_at", now_project_iso()),
        "window_hours": analytics_payload.get("window_hours", 48),
        "window_complete": analytics_payload.get("window_complete", False),
        "analytics_status": analytics_payload.get("analytics_status", "unknown"),
        "performance": {
            "views_48h": perf.get("views_48h"),
            "ctr": perf.get("ctr"),
            "average_view_duration_seconds": perf.get("average_view_duration_seconds"),
            "like_count": perf.get("like_count"),
            "comment_count": perf.get("comment_count"),
            "subscribers_gained": perf.get("subscribers_gained"),
            "retention_quality": _retention_quality(perf.get("average_view_duration_seconds")),
            "engagement_quality": _engagement_quality(
                perf.get("like_count"),
                perf.get("comment_count"),
                perf.get("views_48h"),
            ),
        },
        "content_attributes": {
            "format": video_record.get("selected_format", ""),
            "topics": coverage.get("topics", []),
            "entities": coverage.get("entities", []),
            "hook_type": hook_type,
            "title_angle": title_angle,
        },
        "learning_value": {
            "use_for_future_ranking": True,
            "positive_signals": [],
        },
    }
    record["learning_value"]["positive_signals"] = _positive_signals(record)

    existing_map[video_id] = record
    ordered = sorted(existing_map.values(), key=lambda rec: rec.get("published_at") or "")
    _write_jsonl(path, ordered)
    return {
        "status": "upserted",
        "path": str(path),
        "video_id": video_id,
    }
