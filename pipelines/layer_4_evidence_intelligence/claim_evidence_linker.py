"""
Layer 4 — Module 4: Claim Evidence Linker

Attaches every claim to its source span, canonical document, URL,
trust tier, and source role. Pure dict lookups — no LLM.

Produces:
  - enriched claim records (source info added in-place)
  - claim_evidence_map records for claim_evidence_map.jsonl

Key function:
    link_all(story_results, spans_by_id, docs_by_id)
        → {enriched_story_results, evidence_map_records}

Usage:
    python claim_evidence_linker.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def link(claim: dict, spans_by_id: dict, docs_by_id: dict) -> dict:
    """
    Enrich one claim with full evidence provenance.
    Returns the enriched claim and a ClaimEvidenceMap record.
    """
    span_id = claim.get("extracted_from_span_id", "")
    span = spans_by_id.get(span_id, {})
    doc_id = span.get("canonical_document_id", "")
    doc = docs_by_id.get(doc_id, {})

    evidence = {
        "source_span_ids":        [span_id] if span_id else [],
        "canonical_document_ids": [doc_id] if doc_id else [],
        "source_urls":            [span.get("source_url") or doc.get("url", "")],
        "source_roles":           [span.get("source_role") or doc.get("source_role", "")],
        "trust_tiers":            [span.get("trust_tier") or doc.get("trust_tier", 4)],
    }

    enriched = {**claim, "evidence": evidence}

    evidence_map = {
        "claim_id":               claim["claim_id"],
        "story_id":               claim["story_id"],
        "source_span_ids":        evidence["source_span_ids"],
        "canonical_document_ids": evidence["canonical_document_ids"],
        "source_urls":            evidence["source_urls"],
        "source_roles":           evidence["source_roles"],
        "trust_tiers":            evidence["trust_tiers"],
    }
    return enriched, evidence_map


def link_all(story_results: list[dict], spans_by_id: dict,
             docs_by_id: dict) -> dict:
    """
    Link evidence for all claims across all story results.

    Returns:
        {
          "enriched_story_results": [...],   # story_results with evidence fields added
          "evidence_map_records":   [...],   # flat list for claim_evidence_map.jsonl
        }
    """
    enriched_results = []
    all_evidence_maps = []

    for story_result in story_results:
        enriched_claims = []
        for claim in story_result.get("atomic_claims", []):
            enriched_claim, ev_map = link(claim, spans_by_id, docs_by_id)
            enriched_claims.append(enriched_claim)
            all_evidence_maps.append(ev_map)

        enriched_results.append({**story_result, "atomic_claims": enriched_claims})

    return {
        "enriched_story_results": enriched_results,
        "evidence_map_records":   all_evidence_maps,
    }


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_3" / "ranked_stories.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_4_evidence_intelligence.evidence_loader import load
    from pipelines.layer_4_evidence_intelligence.span_selector   import select_all
    from pipelines.layer_4_evidence_intelligence.claim_extractor  import extract_all

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer3_dir, layer2_dir)
    selections    = select_all(loader_result["evidence_bundles"], loader_result["spans_by_id"])
    story_results = extract_all(selections, run_id)

    linker_result = link_all(story_results, loader_result["spans_by_id"], loader_result["docs_by_id"])

    total_claims = sum(len(r["atomic_claims"])
                       for r in linker_result["enriched_story_results"])
    print(f"\nClaim Evidence Linker — {run_id}")
    print(f"  Total claims linked    : {total_claims}")
    print(f"  Evidence map records   : {len(linker_result['evidence_map_records'])}")

    sample = linker_result["enriched_story_results"][0]["atomic_claims"][0]
    print(f"\n  Sample linked claim:")
    print(f"    claim_id  : {sample['claim_id']}")
    print(f"    claim_text: {sample['claim_text'][:70]}")
    print(f"    source_url: {sample['evidence']['source_urls'][0]}")
    print(f"    trust_tier: {sample['evidence']['trust_tiers'][0]}")
