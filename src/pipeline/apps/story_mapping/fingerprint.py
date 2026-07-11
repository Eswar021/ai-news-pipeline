from __future__ import annotations

import re

from .utils import clean_text


TRANSCRIPT_BOILERPLATE_PATTERNS = [
    r"\bwelcome back\b",
    r"\bwelcome to the channel\b",
    r"\blike and subscribe\b",
    r"\bsubscribe to the channel\b",
    r"\bthanks for watching\b",
    r"\bthis video is sponsored by\b",
    r"\btoday['’]s sponsor\b",
]

URL_RE = re.compile(r"https?://\S+")
MULTISPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def build_fingerprint_text(record: dict) -> str:
    source_group = record.get("source_group", "")
    provider = record.get("provider", "")
    identity_parts = _identity_parts(record)

    if source_group == "research_papers":
        return _compose(
            identity_parts
            + [
                record.get("title", ""),
                record.get("category", ""),
                _clip_sentences(record.get("content", ""), max_sentences=8, max_chars=1600),
            ]
        )

    if source_group == "youtube_podcast_transcripts":
        cleaned = _strip_transcript_boilerplate(record.get("content", ""))
        return _compose(
            identity_parts
            + [
                record.get("title", ""),
                record.get("channel_name", ""),
                _clip_sentences(cleaned, max_sentences=8, max_chars=1000),
            ]
        )

    if source_group == "community_signals" and provider == "github":
        readme_lead = _clean_github_readme(record.get("content", ""))
        return _compose(
            identity_parts
            + [
                record.get("title", ""),
                record.get("description", ""),
                ", ".join(record.get("topics", []) or []),
                _clip_sentences(readme_lead, max_sentences=8, max_chars=1200),
            ]
        )

    if source_group == "community_signals" and provider == "hackernews":
        base = identity_parts + [
            record.get("title", ""),
        ]
        if record.get("url"):
            base.append(_clip_sentences(record.get("content", ""), max_sentences=8, max_chars=1000))
        else:
            base.append(_clip_sentences(record.get("content", ""), max_sentences=6, max_chars=800))
        return _compose(base)

    return _compose(
        identity_parts
        + [
            record.get("title", ""),
            record.get("description", "") or record.get("summary", ""),
            _clip_sentences(record.get("content", ""), max_sentences=8, max_chars=1200),
        ]
    )


def tokenize_title(title: str) -> set[str]:
    stopwords = {
        "a", "an", "and", "are", "at", "for", "from", "how", "in", "into", "is",
        "of", "on", "or", "the", "to", "with", "your",
    }
    tokens = set()
    for token in re.findall(r"[a-z0-9\+\-\.]+", clean_text(title).lower()):
        if len(token) < 3 and token != "ai":
            continue
        if token in stopwords:
            continue
        tokens.add(token)
    return tokens


def _identity_parts(record: dict) -> list[str]:
    identity = record.get("story_identity") or {}
    if not isinstance(identity, dict):
        return []
    return [
        identity.get("merge_identity", ""),
        identity.get("primary_entity", ""),
        identity.get("owning_org", ""),
        identity.get("product_or_project", ""),
        identity.get("story_action", ""),
        identity.get("story_type", ""),
        identity.get("one_sentence_story", ""),
        identity.get("why_it_matters", ""),
    ]


def _compose(parts: list[str]) -> str:
    seen: set[str] = set()
    cleaned_parts: list[str] = []
    for part in parts:
        value = clean_text(part)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_parts.append(value)
    return clean_text(" ".join(cleaned_parts))


def _clip_sentences(text: str, *, max_sentences: int, max_chars: int) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(cleaned) if len(s.strip()) >= 40]
    if not sentences:
        return cleaned[:max_chars]

    parts: list[str] = []
    length = 0
    for sentence in sentences:
        if len(parts) >= max_sentences:
            break
        next_len = length + len(sentence) + (1 if parts else 0)
        if next_len > max_chars:
            remaining = max_chars - length
            if remaining > 80:
                parts.append(sentence[:remaining].rstrip())
            break
        parts.append(sentence)
        length = next_len
    return clean_text(" ".join(parts))


def _strip_transcript_boilerplate(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    for pattern in TRANSCRIPT_BOILERPLATE_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            cleaned = cleaned[match.end():].lstrip(" .:-")
            lowered = cleaned.lower()
    return cleaned


def _clean_github_readme(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    cleaned = URL_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:png|jpg|jpeg|gif|svg|webp)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"`{1,3}[^`]+`{1,3}", " ", cleaned)
    cleaned = re.sub(r"\b(?:npm|pip|cargo|brew|docker)\s+[^\.\n]{0,80}", " ", cleaned, flags=re.IGNORECASE)
    cleaned = MULTISPACE_RE.sub(" ", cleaned).strip()
    return cleaned
