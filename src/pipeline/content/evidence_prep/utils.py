from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


PLACEHOLDER_BODIES = {
    "ONLY AVAILABLE IN PAID PLANS",
    "ONLY AVAILABLE IN PAID PLANS.",
}
HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript", "svg"}:
            self.suppressed_depth += 1
            return
        if not self.suppressed_depth and lowered in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript", "svg"} and self.suppressed_depth:
            self.suppressed_depth -= 1
            return
        if not self.suppressed_depth and lowered in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = unescape(str(value))
    text = repair_mojibake(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_article_content(
    value: str,
    *,
    url: str,
    config: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    raw_value = str(value or "")
    original = clean_text(raw_value)
    html_tag_count = len(HTML_TAG_RE.findall(raw_value))
    result = {
        "enabled": bool(config.get("enabled", True)),
        "applied_rule": "",
        "modified": False,
        "original_chars": len(original),
        "cleaned_chars": len(original),
        "removed_chars": 0,
        "html_markup_removed": False,
        "html_tag_count": html_tag_count,
    }
    if not original:
        return original, result

    non_text_kind = detect_non_text_payload(raw_value)
    if non_text_kind:
        result.update(
            {
                "applied_rule": "non_text_payload_removed",
                "modified": True,
                "cleaned_chars": 0,
                "removed_chars": len(original),
                "non_text_payload_detected": True,
                "non_text_payload_kind": non_text_kind,
                "decoded_payload_sha256": hashlib.sha256(
                    raw_value.encode("utf-8", errors="replace")
                ).hexdigest(),
            }
        )
        return "", result
    if not result["enabled"]:
        return original, result

    cleaned = original
    if bool(config.get("strip_html_markup", True)) and html_tag_count:
        parser = _HTMLTextExtractor()
        parser.feed(raw_value)
        parser.close()
        cleaned = clean_text(parser.text())
        result["html_markup_removed"] = cleaned != original

    hostname = (urlparse(url).hostname or "").casefold().removeprefix("www.")
    rule = next(
        (
            item
            for item in config.get("rules", [])
            if _hostname_matches(hostname, item.get("domain_suffixes", []))
        ),
        None,
    )
    if isinstance(rule, dict):
        leading_matches = [
            (cleaned.casefold().find(clean_text(marker).casefold()), clean_text(marker))
            for marker in rule.get("leading_markers", [])
            if clean_text(marker)
        ]
        leading_matches = [item for item in leading_matches if item[0] >= 0]
        if leading_matches:
            index, marker = min(leading_matches, key=lambda item: item[0])
            cleaned = cleaned[index + len(marker) :]

        trailing_matches = [
            cleaned.casefold().find(clean_text(marker).casefold())
            for marker in rule.get("trailing_markers", [])
            if clean_text(marker)
        ]
        trailing_matches = [index for index in trailing_matches if index >= 0]
        if trailing_matches:
            cleaned = cleaned[: min(trailing_matches)]
        for phrase in rule.get("remove_phrases", []):
            cleaned = re.sub(re.escape(clean_text(phrase)), " ", cleaned, flags=re.IGNORECASE)
        for pattern in rule.get("remove_patterns", []):
            cleaned = re.sub(str(pattern), " ", cleaned, flags=re.IGNORECASE)

    cleaned = clean_text(cleaned)
    result.update(
        {
            "applied_rule": clean_text(rule.get("name")) if isinstance(rule, dict) else "generic_html_to_text",
            "modified": cleaned != original,
            "cleaned_chars": len(cleaned),
            "removed_chars": max(0, len(original) - len(cleaned)),
        }
    )
    return cleaned, result


def detect_non_text_payload(value: str) -> str:
    """Identify objective transport-format payloads that are not readable source text."""

    raw = str(value or "")
    if not raw:
        return ""
    if raw.lstrip().startswith("%PDF-"):
        return "pdf_binary"
    if "\x00" in raw:
        return "binary_with_null_bytes"
    replacement_count = raw.count("\ufffd")
    if replacement_count >= 32 and replacement_count / max(1, len(raw)) >= 0.005:
        return "binary_decode_replacements"
    return ""


def _hostname_matches(hostname: str, suffixes: list[str]) -> bool:
    return any(
        hostname == clean_text(suffix).casefold().removeprefix("www.")
        or hostname.endswith(f".{clean_text(suffix).casefold().removeprefix('www.')}")
        for suffix in suffixes
        if clean_text(suffix)
    )


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
