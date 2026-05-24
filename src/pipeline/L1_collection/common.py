from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser

from dotenv import load_dotenv
import requests


load_dotenv()


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PLACEHOLDER_BODIES = {
    "ONLY AVAILABLE IN PAID PLANS",
    "ONLY AVAILABLE IN PAID PLANS.",
}


class _TextStripper(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "head", "nav", "footer", "aside", "form"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            value = clean_text(data)
            if value:
                self._parts.append(value)

    def text(self) -> str:
        return clean_text(" ".join(self._parts))


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = unescape(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_html(value: str | None) -> str:
    parser = _TextStripper()
    parser.feed(value or "")
    return parser.text()


def extract_article_text(html: str) -> str:
    for tag in ("article", "main"):
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.DOTALL | re.IGNORECASE)
        if match:
            text = strip_html(match.group(1))
            if len(text) > 200:
                return text
    return strip_html(html)


def extract_published_at_from_html(html: str) -> str:
    patterns = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']publish-date["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return clean_text(match.group(1))

    text = strip_html(html)
    match = re.search(
        r"\b(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|September|Oct|October|Nov|November|Dec|December)\s+\d{1,2},\s+\d{4}\b",
        text,
    )
    if match:
        return clean_text(match.group(0))
    return ""


def request_text(url: str, timeout: int, params: dict | None = None) -> str:
    response = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
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
    if parsed is None:
        return False
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    return start <= parsed.astimezone(start.tzinfo) <= end


def resolve_env(keys: list[str]) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    raise RuntimeError(f"Required environment variable missing. Tried: {', '.join(keys)}")


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


def build_record(
    *,
    source: str,
    source_group: str,
    source_type: str,
    title: str,
    url: str,
    published_at: str,
    content: str,
    extra_fields: dict | None = None,
) -> dict:
    record = {
        "source": source,
        "source_group": source_group,
        "source_type": source_type,
        "title": clean_text(title),
        "url": url,
        "published_at": published_at,
        "content": clean_text(content),
    }
    for key, value in (extra_fields or {}).items():
        if isinstance(value, str):
            record[key] = clean_text(value)
        elif isinstance(value, list):
            record[key] = [clean_text(item) if isinstance(item, str) else item for item in value]
        else:
            record[key] = value
    return record
