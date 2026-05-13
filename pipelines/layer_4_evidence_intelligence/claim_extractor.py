"""
Layer 4 — Module 2: Document Claim Extractor

Extracts atomic claims from document-scoped evidence, not span-scoped evidence.
Large documents are internally chunked only to fit within the model budget.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from config.time_utils import now_project_iso
from llm.async_llm_runtime import execute_chat_request
from llm.prompt_loader import load_prompt_bundle

MAX_CONCURRENT = 12
MAX_CLAIMS_PER_STORY = 24
_DEFAULT_OVERFLOW_CHAR_LIMIT = 12000
_DEDUP_THRESHOLD = 0.7
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "has", "have", "had", "be",
    "been", "being", "will", "would", "could", "should", "may", "might", "it",
    "its", "to", "of", "and", "or", "in", "on", "at", "for", "with", "that",
    "this", "by", "from",
}

_VALID_TYPES = {
    "event_fact", "timeline_fact", "product_fact", "model_capability",
    "feature_claim", "benchmark_claim", "research_claim", "business_claim",
    "partnership_claim", "pricing_claim", "quote_claim", "statistic_claim",
    "limitation_claim", "risk_claim", "community_signal_claim",
    "interpretive_claim", "prediction_claim", "opinion_claim",
}
_VALID_SUPPORT = {"direct", "indirect", "partial"}
_SUPPORT_CONFIDENCE = {"direct": 0.90, "indirect": 0.65, "partial": 0.42}

def _story_hash(story_id: str) -> str:
    parts = story_id.split("_")
    return parts[-1] if len(parts[-1]) >= 4 else story_id[-8:]


def _make_claim_id(story_id: str, counter: int) -> str:
    return f"claim_{_story_hash(story_id)}_{counter:04d}"


def _split_paragraphs(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    return parts or [text.strip()]


def _chunk_document_text(text: str, char_limit: int) -> list[str]:
    text = text.strip()
    if len(text) <= char_limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in _split_paragraphs(text):
        if not current:
            current = paragraph
            continue
        if len(current) + 2 + len(paragraph) <= char_limit:
            current = f"{current}\n\n{paragraph}"
            continue
        chunks.append(current)
        if len(paragraph) <= char_limit:
            current = paragraph
            continue

        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        current_sentence_chunk = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if not current_sentence_chunk:
                current_sentence_chunk = sentence
            elif len(current_sentence_chunk) + 1 + len(sentence) <= char_limit:
                current_sentence_chunk = f"{current_sentence_chunk} {sentence}"
            else:
                chunks.append(current_sentence_chunk)
                current_sentence_chunk = sentence
        current = current_sentence_chunk

    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def _tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(word for word in words if word not in _STOPWORDS)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _validate_claim(raw: dict) -> dict | None:
    claim_text = (raw.get("claim_text") or "").strip()
    if not claim_text:
        return None
    claim_type = raw.get("claim_type", "event_fact")
    if claim_type not in _VALID_TYPES:
        claim_type = "event_fact"
    support_level = raw.get("support_level", "indirect")
    if support_level not in _VALID_SUPPORT:
        support_level = "indirect"
    quote_anchor = (raw.get("quote_anchor") or claim_text)[:500].strip()
    if not quote_anchor:
        quote_anchor = claim_text[:500]
    return {
        "claim_text": claim_text,
        "claim_type": claim_type,
        "support_level": support_level,
        "quote_anchor": quote_anchor,
    }


def _deduplicate_claims(claims: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    token_sets: list[frozenset[str]] = []

    for claim in claims:
        claim_tokens = _tokens(claim["claim_text"])
        merged = False
        for index, existing in enumerate(deduped):
            if existing["claim_type"] != claim["claim_type"]:
                continue
            if _jaccard(token_sets[index], claim_tokens) < _DEDUP_THRESHOLD:
                continue
            if claim.get("extraction_confidence", 0.0) > existing.get("extraction_confidence", 0.0):
                merged_quote = existing.get("quote_anchor", "")
                deduped[index] = {**claim}
                if not deduped[index].get("quote_anchor") and merged_quote:
                    deduped[index]["quote_anchor"] = merged_quote
            merged = True
            break
        if not merged:
            deduped.append(dict(claim))
            token_sets.append(claim_tokens)

    return deduped


async def _call_llm(run_id: str, document: dict, text_chunk: str, chunk_index: int, semaphore) -> list[dict]:
    prompt_bundle = load_prompt_bundle("claim_extractor", run_id=run_id)
    user_msg = (
        f"Story: {document['story_title']} (type: {document['story_type']})\n"
        f"Document title: {document['title']}\n"
        f"Document ID: {document['canonical_document_id']}\n"
        f"Source role: {document['source_role']} | trust tier: {document['trust_tier']}\n"
        f"Document chunk index: {chunk_index}\n\n"
        f"Document text:\n{text_chunk}\n\n"
        "Extract atomic claims from the document text above."
    )
    messages = [
        {"role": "system", "content": prompt_bundle["system"]},
        {"role": "user", "content": user_msg},
    ]

    async with semaphore:
        try:
            data = await execute_chat_request(
                module_name="claim_extractor",
                run_id=run_id,
                messages=messages,
                request_name=f"{document['canonical_document_id']}_{chunk_index:02d}",
                metadata={
                    "story_id": document["story_id"],
                    "story_title": document["story_title"],
                    "story_type": document["story_type"],
                    "canonical_document_id": document["canonical_document_id"],
                    "source_url": document["source_url"],
                },
                parse_json=True,
            )
            return data.get("claims", [])
        except Exception:
            return []


async def _extract_document(run_id: str, document: dict, overflow_char_limit: int, semaphore) -> dict:
    chunks = _chunk_document_text(document["clean_text"], overflow_char_limit)
    tasks = [
        _call_llm(run_id, document, text_chunk, chunk_index, semaphore)
        for chunk_index, text_chunk in enumerate(chunks)
    ]
    raw_results = await asyncio.gather(*tasks)

    claims: list[dict] = []
    for raw_claims in raw_results:
        for raw in raw_claims:
            validated = _validate_claim(raw)
            if not validated:
                continue
            claims.append(
                {
                    "story_id": document["story_id"],
                    "story_title": document["story_title"],
                    "story_type": document["story_type"],
                    "canonical_document_id": document["canonical_document_id"],
                    "source_role": document["source_role"],
                    "trust_tier": document["trust_tier"],
                    "source_url": document["source_url"],
                    "claim_text": validated["claim_text"],
                    "claim_type": validated["claim_type"],
                    "support_level": validated["support_level"],
                    "quote_anchor": validated["quote_anchor"],
                    "extraction_confidence": _SUPPORT_CONFIDENCE[validated["support_level"]],
                    "verification_status": "pending",
                    "extracted_at": now_project_iso(),
                }
            )

    deduped_claims = _deduplicate_claims(claims)
    return {
        "canonical_document_id": document["canonical_document_id"],
        "chunk_count": len(chunks),
        "claims": deduped_claims,
    }


async def _extract_story(run_id: str, bundle: dict, overflow_char_limit: int, semaphore) -> dict:
    story_id = bundle["story_id"]
    story_title = bundle["story_title"]
    story_type = bundle.get("story_type", "unknown")
    eligible_documents = bundle.get("eligible_documents", [])

    document_records = [
        {
            "story_id": story_id,
            "story_title": story_title,
            "story_type": story_type,
            "canonical_document_id": entry["document"]["canonical_document_id"],
            "title": entry["document"].get("title", ""),
            "source_role": entry["document"].get("source_role", ""),
            "trust_tier": entry["document"].get("trust_tier", 4),
            "source_url": entry["document"].get("canonical_url") or entry["document"].get("original_url", ""),
            "clean_text": entry["clean_text"],
        }
        for entry in eligible_documents
    ]

    document_results = await asyncio.gather(
        *[_extract_document(run_id, document, overflow_char_limit, semaphore) for document in document_records]
    )

    atomic_claims: list[dict] = []
    claim_counter = 1
    documents_with_claims = 0
    total_chunks = 0
    for result in document_results:
        total_chunks += result["chunk_count"]
        if result["claims"]:
            documents_with_claims += 1
        for claim in result["claims"]:
            atomic_claims.append(
                {
                    **claim,
                    "claim_id": _make_claim_id(story_id, claim_counter),
                }
            )
            claim_counter += 1

    atomic_claims = _deduplicate_claims(atomic_claims)[:MAX_CLAIMS_PER_STORY]

    return {
        "story_id": story_id,
        "story_title": story_title,
        "story_type": story_type,
        "atomic_claims": atomic_claims,
        "counts": {
            "documents_processed": len(document_records),
            "documents_with_claims": documents_with_claims,
            "chunks_processed": total_chunks,
            "claims_extracted": len(atomic_claims),
        },
    }


def extract_all(evidence_bundles: list[dict], run_id: str, overflow_char_limit: int = _DEFAULT_OVERFLOW_CHAR_LIMIT) -> list[dict]:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_all():
        results = []
        for bundle in evidence_bundles:
            results.append(await _extract_story(run_id, bundle, overflow_char_limit, semaphore))
        return results

    return asyncio.run(_run_all())


if __name__ == "__main__":
    run_id = None
    for manifest_path in sorted(RUNS_DIR.glob("*/run_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        if (manifest_path.parent / "layer_3" / "ranked_stories.json").exists():
            run_id = manifest_path.parent.name
            break
    print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_4_evidence_intelligence.evidence_loader import load

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer3_dir, layer2_dir)
    results = extract_all(loader_result["evidence_bundles"][:2], run_id)

    print(f"\nClaim Extractor — {run_id}")
    print(f"  Stories: {len(results)}")
    print(f"  Claims : {sum(r['counts']['claims_extracted'] for r in results)}")
    for result in results:
        print(
            f"  {result['story_title'][:50]:50s} "
            f"docs={result['counts']['documents_processed']} "
            f"chunks={result['counts']['chunks_processed']} "
            f"claims={result['counts']['claims_extracted']}"
        )
