from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse


WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]+")
SLUG_RE = re.compile(r"[^a-z0-9]+")
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "but",
    "can",
    "for",
    "from",
    "has",
    "have",
    "into",
    "its",
    "not",
    "that",
    "the",
    "this",
    "with",
    "will",
}


def clean_text(value: Any) -> str:
    return WHITESPACE_RE.sub(" ", str(value or "")).strip()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def slugify(value: str, *, fallback: str = "item") -> str:
    cleaned = SLUG_RE.sub("-", clean_text(value).lower()).strip("-")
    return cleaned or fallback


def short_text(text: str, limit: int) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip(" ,.;:") + "..."


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if not cleaned:
            continue
        lookup = cleaned.lower()
        if lookup in seen:
            continue
        seen.add(lookup)
        kept.append(cleaned)
    return kept


def counter_dict(values: list[str]) -> dict[str, int]:
    return dict(Counter(value for value in values if value))


def source_domain(url: str) -> str:
    host = urlparse(clean_text(url)).netloc.lower()
    return host.removeprefix("www.")


def meaningful_words(text: str) -> list[str]:
    words = [word.lower().strip("'") for word in WORD_RE.findall(text or "")]
    return [word for word in words if len(word) > 2 and word not in STOPWORDS]


def first_url(record: dict[str, Any]) -> str:
    for key in ("url", "source_url", "canonical_url", "resolved_url"):
        value = clean_text(record.get(key, ""))
        if value.startswith(("http://", "https://")):
            return value
    return ""


def format_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def split_script_units(
    script_text: str,
    *,
    words_per_minute: int,
    target_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    paragraphs = [clean_text(part) for part in re.split(r"\n\s*\n+", script_text or "") if clean_text(part)]
    if not paragraphs:
        paragraphs = [clean_text(part) for part in SENTENCE_SPLIT_RE.split(script_text or "") if clean_text(part)]
    if not paragraphs:
        paragraphs = [clean_text(script_text)]

    units: list[dict[str, Any]] = []
    total_words = max(1, count_words(script_text))
    total_seconds = target_duration_seconds or total_words / max(1, words_per_minute) * 60.0
    cursor = 0.0
    for index, paragraph in enumerate(paragraphs, start=1):
        words = count_words(paragraph)
        duration = max(2.0, total_seconds * words / total_words)
        units.append(
            {
                "unit_id": f"script_unit_{index:03d}",
                "order": index,
                "text": paragraph,
                "word_count": words,
                "start_seconds": round(cursor, 2),
                "end_seconds": round(cursor + duration, 2),
                "duration_seconds": round(duration, 2),
            }
        )
        cursor += duration
    return units


def normalize_voiceover_package(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value:
        return None
    if "data" in value and isinstance(value.get("data"), dict):
        package = value["data"].get("voiceover_package")
        if isinstance(package, dict):
            return package
    if value.get("package_type") == "voiceover_package":
        return value
    package = value.get("voiceover_package")
    if isinstance(package, dict):
        return package
    return value


def voiceover_chunks(voiceover_package: dict[str, Any] | None) -> list[dict[str, Any]]:
    package = normalize_voiceover_package(voiceover_package)
    if not package:
        return []
    chunks = package.get("chunks")
    if not isinstance(chunks, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            continue
        text = clean_text(chunk.get("text", ""))
        start = safe_float(chunk.get("start_seconds"), 0.0)
        end = safe_float(chunk.get("end_seconds"), start)
        duration = safe_float(chunk.get("duration_seconds"), max(0.0, end - start))
        normalized.append(
            {
                "unit_id": clean_text(chunk.get("chunk_id")) or f"voice_chunk_{index:03d}",
                "order": safe_int(chunk.get("order"), index),
                "text": text,
                "word_count": safe_int(chunk.get("word_count"), count_words(text)),
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "duration_seconds": round(duration, 2),
            }
        )
    return sorted(normalized, key=lambda item: item["order"])


def record_text(record: dict[str, Any], *, max_chars: int) -> str:
    content = clean_text(record.get("content") or record.get("text") or "")
    summary = clean_text(record.get("summary") or record.get("description") or "")
    body = content or summary
    if content and summary and not content.lower().startswith(summary[:80].lower()):
        body = f"{summary} {content}"
    return body[:max_chars].rstrip()


def screenshot_target_candidates(record: dict[str, Any]) -> list[str]:
    candidates = [
        clean_text(record.get("title", "")),
        clean_text(record.get("summary") or record.get("description") or ""),
    ]
    content = clean_text(record.get("content") or record.get("text") or "")
    if content:
        candidates.extend(part.strip() for part in content.split(". ") if len(part.strip()) >= 30)
    return dedupe([candidate[:240].rstrip() for candidate in candidates if candidate])
