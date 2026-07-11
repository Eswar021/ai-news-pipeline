from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape


PLACEHOLDER_BODIES = {
    "ONLY AVAILABLE IN PAID PLANS",
    "ONLY AVAILABLE IN PAID PLANS.",
}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = unescape(str(value))
    text = repair_mojibake(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def repair_mojibake(value: str) -> str:
    best = value
    best_score = _mojibake_score(best)
    for encoding in ("cp1252", "latin1"):
        try:
            candidate = value.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue
        candidate_score = _mojibake_score(candidate)
        if candidate_score < best_score:
            best = candidate
            best_score = candidate_score
    return best


def _mojibake_score(value: str) -> int:
    markers = ("\u00c2", "\u00c3", "\u00e2", "\ufffd")
    score = sum(value.count(marker) for marker in markers)
    score += sum(1 for char in value if 0x80 <= ord(char) <= 0x9F)
    return score


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = clean_text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = parsedate_to_datetime(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def within_window(published_at: str | None, start_iso: str, end_iso: str) -> bool:
    parsed = parse_datetime(published_at)
    start = parse_datetime(start_iso)
    end = parse_datetime(end_iso)
    if parsed is None or start is None or end is None:
        return False
    return start <= parsed.astimezone(start.tzinfo) <= end


def normalize_content(content: str, fallback: str = "") -> tuple[str, str]:
    cleaned = clean_text(content)
    if cleaned.upper() in PLACEHOLDER_BODIES:
        return clean_text(fallback), "partial"
    if len(cleaned) > 50:
        return cleaned, "full"
    if fallback:
        fallback_clean = clean_text(fallback)
        if len(fallback_clean) > len(cleaned):
            return fallback_clean, "partial"
    return cleaned or clean_text(fallback), "title_only"
