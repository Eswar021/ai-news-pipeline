"""
Durable rebuild memory store for Layer 9.

The store is intentionally compact and idempotent by run_id.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


IST = timezone(timedelta(hours=5, minutes=30))


def apply_memory_update(memory_update: dict, memory_path: Path) -> dict:
    memory = _load_memory(memory_path)
    run_id = memory_update["run_id"]

    memory["videos_by_run_id"][run_id] = memory_update["video_memory"]
    _upsert_stories(memory, memory_update)
    _upsert_sources(memory, memory_update)
    _replace_recent_title_angles(memory, memory_update)

    memory["updated_at"] = _iso_now()
    memory["stats"] = _build_stats(memory)

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")
    return memory


def _load_memory(memory_path: Path) -> dict:
    if not memory_path.exists():
        now = _iso_now()
        return {
            "schema_version": "v1",
            "created_at": now,
            "updated_at": now,
            "videos_by_run_id": {},
            "stories_by_story_id": {},
            "source_urls": {},
            "recent_title_angles": [],
            "stats": {
                "video_count": 0,
                "approved_not_published_count": 0,
                "published_count": 0,
                "story_count": 0,
                "source_url_count": 0,
                "recent_title_angle_count": 0,
            },
        }

    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    required = [
        "videos_by_run_id",
        "stories_by_story_id",
        "source_urls",
        "recent_title_angles",
    ]
    missing = [key for key in required if key not in memory]
    if missing:
        raise KeyError(f"Rebuild memory store missing required keys: {missing}")
    return memory


def _upsert_stories(memory: dict, memory_update: dict) -> None:
    run_id = memory_update["run_id"]
    video = memory_update["video_memory"]
    for story in memory_update["story_memory"]:
        story_id = story.get("story_id")
        if not story_id:
            continue
        existing = memory["stories_by_story_id"].get(story_id, {})
        run_ids = _without(existing.get("run_ids", []), run_id) + [run_id]
        memory["stories_by_story_id"][story_id] = {
            **existing,
            **story,
            "latest_run_id": run_id,
            "memory_status": memory_update["memory_status"],
            "selected_format": video.get("selected_format"),
            "run_ids": run_ids,
            "updated_at": _iso_now(),
        }


def _upsert_sources(memory: dict, memory_update: dict) -> None:
    run_id = memory_update["run_id"]
    for source in memory_update["source_memory"]:
        url = source.get("source_url")
        if not url:
            continue
        existing = memory["source_urls"].get(url, {})
        run_ids = _without(existing.get("run_ids", []), run_id) + [run_id]
        memory["source_urls"][url] = {
            **existing,
            **source,
            "latest_run_id": run_id,
            "run_ids": run_ids,
            "updated_at": _iso_now(),
        }


def _replace_recent_title_angles(memory: dict, memory_update: dict) -> None:
    run_id = memory_update["run_id"]
    kept = [item for item in memory["recent_title_angles"] if item.get("run_id") != run_id]
    titles = memory_update["video_memory"].get("title_options", [])
    for index, title_item in enumerate(titles[:8], start=1):
        title = title_item.get("title") if isinstance(title_item, dict) else str(title_item)
        kept.append(
            {
                "run_id": run_id,
                "memory_status": memory_update["memory_status"],
                "rank": index,
                "title": title,
                "selected_format": memory_update["video_memory"].get("selected_format"),
                "generated_at": memory_update["generated_at"],
            }
        )
    memory["recent_title_angles"] = kept[-100:]


def _build_stats(memory: dict) -> dict:
    videos = memory["videos_by_run_id"].values()
    return {
        "video_count": len(memory["videos_by_run_id"]),
        "approved_not_published_count": sum(
            1 for item in videos if item.get("memory_status") == "approved_not_published"
        ),
        "published_count": sum(1 for item in videos if item.get("memory_status") == "published"),
        "story_count": len(memory["stories_by_story_id"]),
        "source_url_count": len(memory["source_urls"]),
        "recent_title_angle_count": len(memory["recent_title_angles"]),
    }


def _without(items: list, value: str) -> list:
    return [item for item in items if item != value]


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
