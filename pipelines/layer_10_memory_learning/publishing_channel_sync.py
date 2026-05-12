"""
Sync authenticated publishing-channel state and published video inventory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path

from pipelines.layer_10_memory_learning.performance_memory_writer import upsert_record
from pipelines.layer_10_memory_learning.youtube_publishing_client import (
    get_video_performance,
    list_uploaded_videos,
)


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


def _load_video_memory_map(memory_dir: Path) -> dict[str, dict]:
    records = _load_jsonl(memory_dir / "video_memory.jsonl")
    mapped = {}
    for record in records:
        yt_id = record.get("publishing", {}).get("youtube_video_id", "")
        if yt_id:
            mapped[yt_id] = record
    return mapped


def _load_editorial_pattern_map(memory_dir: Path) -> dict[str, dict]:
    return {
        rec.get("video_id", ""): rec
        for rec in _load_jsonl(memory_dir / "editorial_pattern_memory.jsonl")
        if rec.get("video_id")
    }


def sync_channel_state(
    memory_dir: Path,
    interactive: bool = False,
    max_videos: int | None = None,
    sync_analytics_for_mapped_videos: bool = True,
) -> dict:
    channel, videos = list_uploaded_videos(
        interactive=interactive,
        max_videos=max_videos,
    )
    now = now_project_iso()
    mapped_video_memory = _load_video_memory_map(memory_dir)
    editorial_map = _load_editorial_pattern_map(memory_dir)
    inventory_path = memory_dir / "published_video_inventory.jsonl"
    state_path = memory_dir / "publishing_channel_state.json"
    existing_inventory = {
        rec.get("youtube_video_id", ""): rec
        for rec in _load_jsonl(inventory_path)
        if rec.get("youtube_video_id")
    }

    synced_inventory = []
    analytics_synced = 0

    for video in videos:
        yt_id = video.get("youtube_video_id", "")
        video_memory_record = mapped_video_memory.get(yt_id)
        mapped_video_id = video_memory_record.get("video_id", "") if video_memory_record else ""
        mapped_run_id = video_memory_record.get("run_id", "") if video_memory_record else ""

        record = {
            "youtube_video_id": yt_id,
            "channel_id": video.get("channel_id", ""),
            "channel_title": video.get("channel_title", ""),
            "title": video.get("title", ""),
            "published_at": video.get("published_at", ""),
            "url": video.get("url", ""),
            "thumbnail_url": video.get("thumbnail_url", ""),
            "statistics": video.get("statistics", {}),
            "status": video.get("status", {}),
            "content_details": video.get("content_details", {}),
            "mapped_video_id": mapped_video_id,
            "mapped_run_id": mapped_run_id,
            "last_synced_at": now,
        }
        existing_inventory[yt_id] = record
        synced_inventory.append(record)

        if sync_analytics_for_mapped_videos and video_memory_record and video.get("published_at"):
            analytics = get_video_performance(
                youtube_video_id=yt_id,
                published_at=video["published_at"],
                interactive=interactive,
            )
            upsert_record(
                memory_dir=memory_dir,
                video_record=video_memory_record,
                analytics_payload=analytics,
                editorial_record=editorial_map.get(video_memory_record.get("video_id", "")),
            )
            analytics_synced += 1

    ordered_inventory = sorted(
        existing_inventory.values(),
        key=lambda rec: rec.get("published_at") or "",
        reverse=True,
    )
    _write_jsonl(inventory_path, ordered_inventory)

    state = {
        "last_synced_at": now,
        "channel_id": channel.get("channel_id", ""),
        "title": channel.get("title", ""),
        "custom_url": channel.get("custom_url", ""),
        "published_at": channel.get("published_at", ""),
        "uploads_playlist_id": channel.get("uploads_playlist_id", ""),
        "statistics": channel.get("statistics", {}),
        "inventory_video_count": len(ordered_inventory),
        "synced_video_count_this_run": len(synced_inventory),
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    return {
        "status": "synced",
        "channel_id": state["channel_id"],
        "inventory_records": len(ordered_inventory),
        "videos_seen_this_sync": len(synced_inventory),
        "analytics_records_synced": analytics_synced,
        "state_path": str(state_path),
        "inventory_path": str(inventory_path),
    }
