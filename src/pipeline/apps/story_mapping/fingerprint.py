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
    """Return the complete retrieval text; callers should embed it in chunks."""

    return _compose([*_identity_and_metadata_parts(record), _semantic_body(record)])


def build_fingerprint_chunks(
    record: dict,
    *,
    chunk_chars: int,
    max_chunks: int,
) -> list[str]:
    """Represent the complete semantic body without an early-article cutoff."""

    prefix = _compose(_identity_and_metadata_parts(record))
    body_chunks = _chunk_complete_text(_semantic_body(record), chunk_chars=chunk_chars)
    chunks = [_compose([prefix, chunk]) for chunk in body_chunks] or [prefix]
    chunks = [chunk for chunk in chunks if chunk]
    if len(chunks) > max_chunks:
        raise ValueError(
            "Complete story-mapping fingerprint exceeds "
            "clustering.max_fingerprint_chunks_per_record; no source text was truncated. "
            f"record_key={clean_text(record.get('record_key'))!r}, "
            f"chunk_count={len(chunks)}, configured_limit={max_chunks}"
        )
    return chunks or [clean_text(record.get("title")) or clean_text(record.get("record_key"))]


def _identity_and_metadata_parts(record: dict) -> list[str]:
    source_group = record.get("source_group", "")
    provider = record.get("provider", "")
    identity_parts = _identity_parts(record)

    if source_group == "research_papers":
        return identity_parts + [record.get("title", ""), record.get("category", "")]

    if source_group == "youtube_podcast_transcripts":
        return identity_parts + [record.get("title", ""), record.get("channel_name", "")]

    if source_group == "community_signals" and provider == "github":
        return identity_parts + [
            record.get("title", ""),
            record.get("description", ""),
            ", ".join(record.get("topics", []) or []),
        ]

    if source_group == "community_signals" and provider == "hackernews":
        return identity_parts + [record.get("title", "")]

    return identity_parts + [
        record.get("title", ""),
        record.get("description", "") or record.get("summary", ""),
    ]


def _semantic_body(record: dict) -> str:
    for field in (
        "cleaned_content",
        "content",
        "transcript",
        "semantic_content",
        "raw_content",
    ):
        value = str(record.get(field) or "").strip()
        if value:
            return value
    return _compose(
        [
            record.get("title", ""),
            record.get("summary", ""),
            record.get("description", ""),
        ]
    )


def _chunk_complete_text(text: str, *, chunk_chars: int) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    chunks: list[str] = []
    cursor = 0
    while cursor < len(cleaned):
        end = min(len(cleaned), cursor + chunk_chars)
        if end < len(cleaned):
            boundary = cleaned.rfind(" ", cursor, end)
            if boundary > cursor + chunk_chars // 2:
                end = boundary
        chunk = cleaned[cursor:end].strip()
        if chunk:
            chunks.append(chunk)
        cursor = end
        while cursor < len(cleaned) and cleaned[cursor].isspace():
            cursor += 1
    return chunks


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
