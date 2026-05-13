"""
Layer 4 — Module 3: Claim Provenance Resolver

Maps document-scoped claim quote anchors back to Layer 2 source spans.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _span_matches(anchor: str, span_text: str) -> bool:
    norm_anchor = _normalize(anchor)
    norm_span = _normalize(span_text)
    if not norm_anchor or not norm_span:
        return False
    if norm_anchor in norm_span:
        return True

    anchor_tokens = _token_set(norm_anchor)
    span_tokens = _token_set(norm_span)
    if not anchor_tokens or not span_tokens:
        return False
    overlap = len(anchor_tokens & span_tokens) / len(anchor_tokens)
    return overlap >= 0.6


def _resolve_span_ids(claim: dict, spans_for_document: list[dict]) -> list[str]:
    anchor = claim.get("quote_anchor", "") or claim.get("claim_text", "")
    matches = []
    for span in spans_for_document:
        if _span_matches(anchor, span.get("text", "")):
            matches.append(span["span_id"])
    return matches


def link(claim: dict, spans_by_document_id: dict, docs_by_id: dict) -> dict:
    document_id = claim.get("canonical_document_id", "")
    document = docs_by_id.get(document_id, {})
    spans_for_document = spans_by_document_id.get(document_id, [])
    source_span_ids = _resolve_span_ids(claim, spans_for_document)
    resolved_spans = [span for span in spans_for_document if span.get("span_id") in set(source_span_ids)]

    source_urls = [document.get("canonical_url") or document.get("original_url") or claim.get("source_url", "")]
    trust_tiers = [claim.get("trust_tier", document.get("trust_tier", 4))]
    source_roles = [claim.get("source_role", document.get("source_role", ""))]

    return {
        **claim,
        "source_span_ids": source_span_ids,
        "source_urls": [url for url in source_urls if url],
        "canonical_document_ids": [document_id] if document_id else [],
        "trust_tiers": trust_tiers,
        "source_roles": source_roles,
        "resolved_span_count": len(source_span_ids),
        "unresolved_provenance": len(source_span_ids) == 0,
        "matched_quote_anchor": claim.get("quote_anchor", ""),
        "matched_span_texts": [span.get("text", "")[:500] for span in resolved_spans],
    }


def link_all(story_results: list[dict], spans_by_document_id: dict, docs_by_id: dict) -> list[dict]:
    enriched_results = []
    for story_result in story_results:
        enriched_claims = [
            link(claim, spans_by_document_id, docs_by_id)
            for claim in story_result.get("atomic_claims", [])
        ]
        enriched_results.append({**story_result, "atomic_claims": enriched_claims})
    return enriched_results


if __name__ == "__main__":
    run_id = None
    for manifest_path in sorted(RUNS_DIR.glob("*/run_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        if (manifest_path.parent / "layer_3" / "ranked_stories.json").exists():
            run_id = manifest_path.parent.name
            break
    print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_4_evidence_intelligence.claim_extractor import extract_all
    from pipelines.layer_4_evidence_intelligence.evidence_loader import load

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer3_dir, layer2_dir)
    story_results = extract_all(loader_result["evidence_bundles"][:1], run_id)
    linked = link_all(story_results, loader_result["spans_by_document_id"], loader_result["docs_by_id"])
    print(f"Linked stories: {len(linked)}")
