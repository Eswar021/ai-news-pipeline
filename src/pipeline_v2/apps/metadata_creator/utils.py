from __future__ import annotations

import re
from typing import Any

from .config import ACRONYM_TAGS, BLOCKED_TAG_VALUES


WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str:
    return WHITESPACE_RE.sub(" ", str(value or "")).strip()


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    kept = []
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


def format_timestamp(seconds: int | float) -> str:
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def shorten_title(title: str, limit: int = 64) -> str:
    cleaned = clean_text(title)
    if len(cleaned) <= limit:
        return cleaned
    for separator in (" - ", " — ", ": ", " with ", " for "):
        head = cleaned.split(separator, 1)[0]
        if 12 <= len(head) <= limit:
            return head
    shortened = ""
    for word in cleaned.split():
        candidate = f"{shortened} {word}".strip()
        if len(candidate) > limit:
            break
        shortened = candidate
    return shortened or cleaned[:limit].rstrip()


def clean_thumbnail_text(value: str) -> str:
    cleaned = clean_text(value).upper()
    if not cleaned:
        return ""
    return " ".join(cleaned.split()[:4])


def clean_tag(value: Any) -> str:
    cleaned = clean_text(value).replace("_", " ")
    if not cleaned:
        return ""
    compact = " ".join(cleaned.split())
    if compact.lower() in BLOCKED_TAG_VALUES:
        return ""
    return " ".join(_format_tag_word(word) for word in compact.split())[:60]


def source_url_from_record(record: dict[str, Any]) -> str:
    for key in ("url", "source_url", "canonical_url", "resolved_url"):
        value = clean_text(record.get(key, ""))
        if value.startswith(("http://", "https://")):
            return value
    return ""


def _format_tag_word(word: str) -> str:
    lower = word.lower()
    if lower in ACRONYM_TAGS:
        return ACRONYM_TAGS[lower]
    if "-" in word:
        parts = [ACRONYM_TAGS.get(part.lower(), part[:1].upper() + part[1:]) for part in word.split("-")]
        return "-".join(parts)
    if word.isupper() and len(word) <= 5:
        return word
    return word[:1].upper() + word[1:]
