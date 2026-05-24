from __future__ import annotations

import hashlib
import re

from src.llm.client import OpenAIJSONClient
from src.pipeline.L1_collection.common import clean_text


VALID_FACT_TYPES = {
    "event_fact",
    "timeline_fact",
    "product_fact",
    "model_capability",
    "feature_claim",
    "benchmark_claim",
    "research_claim",
    "business_claim",
    "partnership_claim",
    "pricing_claim",
    "quote_claim",
    "statistic_claim",
    "limitation_claim",
    "risk_claim",
    "community_signal_claim",
    "interpretive_claim",
    "prediction_claim",
    "opinion_claim",
}
VALID_SUPPORT_LEVELS = {"direct", "indirect", "partial"}
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}
DEDUP_THRESHOLD = 0.72


def extract_story_facts(
    story_input: dict,
    *,
    layer4_cfg: dict,
    llm_client: OpenAIJSONClient,
    system_prompt: str,
    log_path,
) -> dict:
    overflow_char_limit = int(layer4_cfg["overflow_char_limit"])
    selected_records = story_input["selected_supporting_records"]

    record_fact_sets: list[dict] = []
    raw_fact_count = 0

    for record in selected_records:
        content = clean_text(record.get("content", ""))
        chunks = _chunk_text(content, overflow_char_limit)
        raw_candidates: list[dict] = []
        for chunk_index, chunk_text in enumerate(chunks):
            user_prompt = _build_user_prompt(story_input, record, chunk_text, chunk_index, len(chunks))
            response_json = llm_client.generate_json(
                module_name="claim_extractor",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                log_path=log_path,
                metadata={
                    "story_id": story_input["story_id"],
                    "story_title": story_input["story_title"],
                    "record_key": record.get("record_key", ""),
                    "source_group": record.get("source_group", ""),
                    "chunk_index": chunk_index,
                    "chunk_count": len(chunks),
                },
            )
            for raw_fact in response_json.get("claims", []):
                validated = _validate_fact(raw_fact, record)
                if validated is not None:
                    raw_candidates.append(validated)

        deduped_record_facts = _deduplicate_record_facts(raw_candidates)
        raw_fact_count += len(deduped_record_facts)
        record_fact_sets.append(
            {
                "record_key": record["record_key"],
                "record": record,
                "chunk_count": len(chunks),
                "facts": deduped_record_facts,
            }
        )

    return {
        "story_id": story_input["story_id"],
        "story_title": story_input["story_title"],
        "story_type_hint": story_input["story_type_hint"],
        "story_identity": story_input.get("story_identity", {}),
        "rank": story_input["rank"],
        "priority_bucket": story_input["priority_bucket"],
        "source_groups": story_input["source_groups"],
        "story_signals": story_input["story_signals"],
        "match_reasons": story_input["match_reasons"],
        "selected_supporting_records": selected_records,
        "record_fact_sets": record_fact_sets,
        "raw_fact_count": raw_fact_count,
    }


def _build_user_prompt(story_input: dict, record: dict, chunk_text: str, chunk_index: int, chunk_count: int) -> str:
    return (
        f"Story title: {story_input['story_title']}\n"
        f"Story type: {story_input['story_type_hint']}\n"
        f"Story rank: {story_input['rank']}\n"
        f"Record key: {record.get('record_key', '')}\n"
        f"Source group: {record.get('source_group', '')}\n"
        f"Source name: {record.get('source_name', record.get('provider', record.get('source', '')))}\n"
        f"Record title: {record.get('title', '')}\n"
        f"Published at: {record.get('published_at', '')}\n"
        f"Chunk: {chunk_index + 1}/{chunk_count}\n"
        "Extract at most 6 high-value facts from this chunk. Return fewer if only a few facts matter. "
        "Do not extract publication-date-only facts, setup steps, prerequisites, or generic capabilities.\n\n"
        f"Document text:\n{chunk_text}\n"
    )


def _validate_fact(raw_fact: dict, record: dict) -> dict | None:
    fact_text = clean_text(raw_fact.get("claim_text", ""))
    if not fact_text:
        return None

    fact_type = raw_fact.get("claim_type", "event_fact")
    if fact_type not in VALID_FACT_TYPES:
        fact_type = "event_fact"

    support_level = raw_fact.get("support_level", "indirect")
    if support_level not in VALID_SUPPORT_LEVELS:
        support_level = "indirect"

    quote_anchor = clean_text(raw_fact.get("quote_anchor", ""))[:500]

    return {
        "candidate_id": _candidate_id(record["record_key"], fact_text, fact_type),
        "record_key": record["record_key"],
        "source_group": record.get("source_group", ""),
        "source_url": record.get("url", ""),
        "source_name": record.get("source_name", record.get("provider", record.get("source", ""))),
        "published_at": record.get("published_at", ""),
        "trust_tier": record.get("trust_tier", 4),
        "fact_text": fact_text,
        "fact_type": fact_type,
        "support_level": support_level,
        "quote_anchor": quote_anchor,
    }


def _chunk_text(text: str, char_limit: int) -> list[str]:
    if len(text) <= char_limit:
        return [text]

    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
    if not sentences:
        return [text[:char_limit]]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
            continue
        if len(current) + 1 + len(sentence) <= char_limit:
            current = f"{current} {sentence}"
            continue
        chunks.append(current)
        current = sentence
    if current:
        chunks.append(current)
    return chunks


def _deduplicate_record_facts(facts: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    token_sets: list[frozenset[str]] = []
    for fact in facts:
        fact_tokens = _tokens(fact["fact_text"])
        merged = False
        for index, existing in enumerate(deduped):
            if existing["fact_type"] != fact["fact_type"]:
                continue
            if _jaccard(token_sets[index], fact_tokens) < DEDUP_THRESHOLD:
                continue
            if _support_rank(fact["support_level"]) > _support_rank(existing["support_level"]):
                deduped[index] = fact
                token_sets[index] = fact_tokens
            merged = True
            break
        if not merged:
            deduped.append(fact)
            token_sets.append(fact_tokens)
    return deduped


def _candidate_id(record_key: str, fact_text: str, fact_type: str) -> str:
    basis = f"{record_key}|{fact_type}|{fact_text}"
    return f"candidate_{hashlib.sha1(basis.encode('utf-8')).hexdigest()[:12]}"


def _tokens(text: str) -> frozenset[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(token for token in tokens if token not in STOPWORDS)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _support_rank(level: str) -> int:
    return {
        "partial": 0,
        "indirect": 1,
        "direct": 2,
    }.get(level, 0)
