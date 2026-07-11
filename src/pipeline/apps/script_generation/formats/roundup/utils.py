from __future__ import annotations

import json
import re
from typing import Any


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", clean_text(text)))


def estimated_seconds(text: str, words_per_minute: int) -> float:
    if words_per_minute <= 0:
        return 0.0
    return round(word_count(text) * 60.0 / words_per_minute, 1)


def word_budget(target_seconds: int, words_per_minute: int) -> int:
    if target_seconds <= 0:
        return 0
    return max(1, round(target_seconds * words_per_minute / 60.0))


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        kept.append(cleaned)
    return kept


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def story_id(story: dict[str, Any]) -> str:
    return clean_text(story.get("story_id", "")) or "unknown_story"


def story_title(story: dict[str, Any]) -> str:
    return clean_text(story.get("story_title", "")) or clean_text(story.get("title", ""))


def source_record_keys(story: dict[str, Any]) -> list[str]:
    keys = list((story.get("video_segment") or {}).get("source_record_keys") or [])
    if not keys:
        keys = [clean_text(record.get("record_key", "")) for record in story.get("records", [])]
    return dedupe(keys)
