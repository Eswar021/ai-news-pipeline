"""
Layer 3 — Module 2: Document Eligibility Filter

Decides which documents can:
  - create a story (seed clustering)
  - support an existing story
  - only act as a ranking/trend signal

Rules:
  Tier 1  (primary_evidence)    → creator + supporter + signal
  Tier 1.5 (research_evidence) → creator + supporter + signal
  Tier 2  (secondary_evidence)  → creator (if has URL + date), supporter, signal
  Tier 2.5 (technical_artifact) → creator, supporter, signal
  Tier 3  (trend_signal_only)   → supporter + signal only; NOT a creator

  Title-only or metadata_only content with trust > 2.5 → signal only.

Usage:
    python eligibility_filter.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def classify(doc: dict) -> dict:
    """
    Classify a single canonical document for story eligibility.

    Returns:
        {
            "canonical_document_id": str,
            "eligible_for_story_creation": bool,
            "eligible_for_story_support": bool,
            "eligible_for_ranking_signal": bool,
            "reason": str,
        }
    """
    doc_id      = doc["canonical_document_id"]
    trust_tier  = doc.get("trust_tier", 4)
    source_role = doc.get("source_role", "unknown")
    completeness = doc.get("content_completeness", "unknown")
    quality_score = doc.get("content_quality_score", 0.0)
    has_url     = bool(doc.get("canonical_url"))
    has_date    = bool(doc.get("published_at"))
    usable_clustering = doc.get("usable_for_story_clustering", False)

    # Metadata/title-only docs: signal only regardless of tier
    if completeness in ("title_only", "metadata_only") or not usable_clustering:
        return {
            "canonical_document_id":       doc_id,
            "eligible_for_story_creation": False,
            "eligible_for_story_support":  trust_tier <= 2.5,
            "eligible_for_ranking_signal": True,
            "reason": f"weak_content_{completeness}",
        }

    # Trend-signal-only sources: can support but not create
    if source_role == "trend_signal_only" or trust_tier >= 3:
        return {
            "canonical_document_id":       doc_id,
            "eligible_for_story_creation": False,
            "eligible_for_story_support":  True,
            "eligible_for_ranking_signal": True,
            "reason": "community_or_trend_signal_only",
        }

    # Tier 1 — official company sources
    if trust_tier == 1:
        return {
            "canonical_document_id":       doc_id,
            "eligible_for_story_creation": True,
            "eligible_for_story_support":  True,
            "eligible_for_ranking_signal": True,
            "reason": "primary_evidence_source",
        }

    # Tier 1.5 — research papers
    if trust_tier == 1.5:
        return {
            "canonical_document_id":       doc_id,
            "eligible_for_story_creation": True,
            "eligible_for_story_support":  True,
            "eligible_for_ranking_signal": True,
            "reason": "research_evidence_source",
        }

    # Tier 2 — news/secondary sources
    if trust_tier == 2:
        can_create = has_url and has_date and quality_score >= 0.4
        return {
            "canonical_document_id":       doc_id,
            "eligible_for_story_creation": can_create,
            "eligible_for_story_support":  True,
            "eligible_for_ranking_signal": True,
            "reason": "secondary_evidence_source" if can_create else "secondary_evidence_weak",
        }

    # Tier 2.5 — technical artifacts (GitHub repos)
    if trust_tier == 2.5:
        return {
            "canonical_document_id":       doc_id,
            "eligible_for_story_creation": True,
            "eligible_for_story_support":  True,
            "eligible_for_ranking_signal": True,
            "reason": "technical_artifact_source",
        }

    # Fallback
    return {
        "canonical_document_id":       doc_id,
        "eligible_for_story_creation": False,
        "eligible_for_story_support":  False,
        "eligible_for_ranking_signal": False,
        "reason": f"unknown_tier_{trust_tier}",
    }


def filter_all(docs: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Run eligibility classification on all documents.

    Returns:
        (eligible_records, all_records) where each record is
        {doc, eligibility} merged with the doc dict.
    """
    results = []
    for doc in docs:
        eligibility = classify(doc)
        results.append({**doc, "eligibility": eligibility})
    return results


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        run_dirs = sorted(RUNS_DIR.glob("*/run_manifest.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = run_dirs[0].parent.name
        # fallback to run with layer_2
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_2" / "canonical_documents.jsonl").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    docs = [json.loads(l)
            for l in (RUNS_DIR / run_id / "layer_2" / "canonical_documents.jsonl")
            .read_text().splitlines() if l.strip()]

    results = filter_all(docs)
    creators  = [r for r in results if r["eligibility"]["eligible_for_story_creation"]]
    supporters = [r for r in results if r["eligibility"]["eligible_for_story_support"]
                  and not r["eligibility"]["eligible_for_story_creation"]]
    signals   = [r for r in results if not r["eligibility"]["eligible_for_story_support"]]

    print(f"\nEligibility Filter — {run_id}")
    print(f"  Story creators  : {len(creators)}")
    print(f"  Story supporters: {len(supporters)}")
    print(f"  Signal only     : {len(signals)}")
    print("\n  Creator breakdown by source_group:")
    from collections import Counter
    cc = Counter(r["source_group"] for r in creators)
    for k, v in cc.most_common():
        print(f"    {k}: {v}")
    print("\n  Supporter breakdown:")
    sc = Counter(r["source_group"] for r in supporters)
    for k, v in sc.most_common():
        print(f"    {k}: {v}")
