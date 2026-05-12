"""
Mark a prepared pipeline run as a published YouTube video and rebuild
published-memory artifacts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path

from config.paths import MEMORY_DIR
from pipelines.layer_10_memory_learning.performance_memory_writer import upsert_record
from pipelines.layer_10_memory_learning.published_memory_rebuilder import rebuild_published_memory_artifacts
from pipelines.layer_10_memory_learning.youtube_publishing_client import (
    get_authenticated_channel,
    get_video_detail,
    get_video_performance,
    youtube_video_url,
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


def _find_video_record(records: list[dict], run_id: str) -> dict:
    expected_video_id = f"video_candidate_{run_id}"
    for record in records:
        if record.get("run_id") == run_id or record.get("video_id") == expected_video_id:
            return record
    raise RuntimeError(
        f"No video_memory record found for run '{run_id}'. "
        "Run Layer 10 first so the prepared-video memory exists before publication."
    )


def _update_story_coverage(memory_dir: Path, video_id: str, published_at: str) -> dict:
    path = memory_dir / "story_coverage_memory.jsonl"
    records = _load_jsonl(path)
    updated = 0
    for record in records:
        if record.get("video_id") == video_id:
            record["coverage_status"] = "covered_in_published_video"
            record["published_at"] = published_at
            updated += 1
    _write_jsonl(path, records)
    return {"updated_records": updated}


def _update_editorial_patterns(memory_dir: Path, video_id: str, published_at: str, published_video_id: str) -> dict:
    path = memory_dir / "editorial_pattern_memory.jsonl"
    records = _load_jsonl(path)
    updated = 0
    matched_record = None
    for record in records:
        if record.get("video_id") == video_id:
            record["published_at"] = published_at
            record["published_video_id"] = published_video_id
            updated += 1
            matched_record = record
    _write_jsonl(path, records)
    return {"updated_records": updated, "record": matched_record}


def mark_run_as_published(
    run_id: str,
    youtube_video_id: str,
    published_at: str | None = None,
    video_url: str | None = None,
    interactive: bool = False,
    memory_dir: Path = MEMORY_DIR,
    sync_analytics: bool = True,
) -> dict:
    video_memory_path = memory_dir / "video_memory.jsonl"
    video_records = _load_jsonl(video_memory_path)
    video_record = _find_video_record(video_records, run_id)
    channel = get_authenticated_channel(interactive=interactive)
    detail = get_video_detail(youtube_video_id, interactive=interactive)

    resolved_published_at = (
        published_at
        or detail.get("published_at")
        or video_record.get("timestamps", {}).get("published_at")
    )
    if not resolved_published_at:
        raise RuntimeError("Could not resolve published_at for the YouTube video.")

    resolved_url = video_url or detail.get("url") or youtube_video_url(youtube_video_id)
    synced_at = now_project_iso()

    for record in video_records:
        if record.get("video_id") != video_record["video_id"]:
            continue
        record["status"] = "published"
        record.setdefault("timestamps", {})
        record["timestamps"]["published_at"] = resolved_published_at
        record["publishing"] = {
            "platform": "youtube",
            "channel_id": channel.get("channel_id", "") or detail.get("channel_id", ""),
            "channel_title": channel.get("title", "") or detail.get("channel_title", ""),
            "youtube_video_id": youtube_video_id,
            "video_url": resolved_url,
            "last_synced_at": synced_at,
        }
        record["platform_metadata"] = {
            "title": detail.get("title", ""),
            "thumbnail_url": detail.get("thumbnail_url", ""),
            "privacy_status": detail.get("status", {}).get("privacyStatus", ""),
            "description_excerpt": (detail.get("description", "") or "")[:280],
            "duration": detail.get("content_details", {}).get("duration", ""),
        }
        video_record = record
        break

    _write_jsonl(video_memory_path, video_records)

    story_update = _update_story_coverage(memory_dir, video_record["video_id"], resolved_published_at)
    editorial_update = _update_editorial_patterns(
        memory_dir,
        video_record["video_id"],
        resolved_published_at,
        youtube_video_id,
    )

    performance_result = {"status": "skipped"}
    if sync_analytics:
        analytics_payload = get_video_performance(
            youtube_video_id=youtube_video_id,
            published_at=resolved_published_at,
            interactive=interactive,
        )
        performance_result = upsert_record(
            memory_dir=memory_dir,
            video_record=video_record,
            analytics_payload=analytics_payload,
            editorial_record=editorial_update.get("record"),
        )

    rebuild_result = rebuild_published_memory_artifacts(memory_dir)

    return {
        "status": "published",
        "video_id": video_record["video_id"],
        "run_id": run_id,
        "youtube_video_id": youtube_video_id,
        "published_at": resolved_published_at,
        "video_url": resolved_url,
        "story_coverage": story_update,
        "editorial_patterns": {
            "updated_records": editorial_update["updated_records"],
        },
        "performance": performance_result,
        "rebuild": rebuild_result,
    }
