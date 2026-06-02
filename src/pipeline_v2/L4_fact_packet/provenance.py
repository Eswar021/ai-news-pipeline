from __future__ import annotations

import re
from urllib.parse import urlparse

from src.pipeline.L1_collection.common import clean_text


def resolve_story_provenance(story_extraction: dict) -> dict:
    resolved_record_sets: list[dict] = []
    resolved_fact_count = 0

    for record_set in story_extraction["record_fact_sets"]:
        record = record_set["record"]
        blocks = _split_content_blocks(record.get("content", ""))
        resolved_facts: list[dict] = []
        for fact in record_set["facts"]:
            support_records = _resolve_support_records(fact, record, blocks)
            resolved_facts.append(
                {
                    **fact,
                    "support_records": support_records,
                }
            )
            resolved_fact_count += 1
        resolved_record_sets.append(
            {
                "record_key": record_set["record_key"],
                "record": record,
                "chunk_count": record_set["chunk_count"],
                "facts": resolved_facts,
            }
        )

    return {
        **story_extraction,
        "record_fact_sets": resolved_record_sets,
        "resolved_fact_count": resolved_fact_count,
    }


def _resolve_support_records(fact: dict, record: dict, blocks: list[str]) -> list[dict]:
    anchor = clean_text(fact.get("quote_anchor", ""))
    if not anchor:
        return []

    matches: list[dict] = []
    for index, block in enumerate(blocks):
        if not _block_matches(anchor, block):
            continue
        source_relationship = _source_relationship(record)
        matches.append(
            {
                "record_key": record["record_key"],
                "source_url": record.get("url", ""),
                "source_name": record.get("source_name", record.get("provider", record.get("source", ""))),
                "source_group": record.get("source_group", ""),
                "source_relationship": source_relationship,
                "hosted_author_or_org": record.get("hosted_author_or_org", "") or _hosted_author_or_org(record),
                "published_at": record.get("published_at", ""),
                "trust_tier": record.get("trust_tier", 4),
                "support_level": fact.get("support_level", "indirect"),
                "quote_anchor": anchor,
                "matched_snippet": block[:500],
                "paragraph_index": index,
            }
        )
    return matches[:3]


def _source_relationship(record: dict) -> str:
    existing = clean_text(record.get("source_relationship", ""))
    if existing:
        return existing

    source_group = clean_text(record.get("source_group", ""))
    if source_group == "tech_news_apis":
        return "third_party"
    if source_group == "research_papers":
        return "research"
    if source_group == "youtube_podcast_transcripts":
        return "channel_or_creator"
    if source_group == "community_signals":
        return "community"

    parsed = urlparse(clean_text(record.get("url", "")))
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    if host == "huggingface.co" and len(path_parts) >= 3 and path_parts[0] == "blog":
        return "hosted_vendor_post"
    if source_group == "ai_company_blogs":
        return "first_party"
    return "unknown"


def _hosted_author_or_org(record: dict) -> str:
    parsed = urlparse(clean_text(record.get("url", "")))
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.netloc.lower().removeprefix("www.") == "huggingface.co" and len(path_parts) >= 3 and path_parts[0] == "blog":
        return path_parts[1]
    return ""


def _split_content_blocks(text: str, max_chars: int = 500) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", cleaned) if sentence.strip()]
    if not sentences:
        return [cleaned]

    blocks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
            continue
        if len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
            continue
        blocks.append(current)
        current = sentence
    if current:
        blocks.append(current)
    return blocks


def _block_matches(anchor: str, block: str) -> bool:
    norm_anchor = _normalize(anchor)
    norm_block = _normalize(block)
    if not norm_anchor or not norm_block:
        return False
    if norm_anchor in norm_block:
        return True

    anchor_tokens = _token_set(norm_anchor)
    block_tokens = _token_set(norm_block)
    if not anchor_tokens or not block_tokens:
        return False
    overlap = len(anchor_tokens & block_tokens) / len(anchor_tokens)
    return overlap >= 0.6


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", clean_text(text).lower()).strip()


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))
