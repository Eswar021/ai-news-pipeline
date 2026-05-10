"""
Layer 4 — Module 9: Story Fact Sheet Builder

Assembles the final fact sheet per story from all Layer 4 pipeline outputs.

Fact sheet sections:
  safe_facts     — verified claims with confidence=high (can state directly)
  cautious_facts — partially_supported or uncertain claims with qualifiers
  do_not_use     — rejected/unsupported claims
  contradictions — conflict records from contradiction_detector
  evidence_gaps  — missing evidence from evidence_density_scorer

Format safety (from density score):
  roundup:    safe / insufficient
  deep_dive:  safe / insufficient
  evergreen:  safe / needs_more_context
  comparison: safe / not_applicable

Handoff recommendation for Layer 5:
  caution_level: low / medium / high

Key function:
    build_all(verified_results, contradiction_results, density_results)
        → list of StoryFactSheet

Usage:
    python story_fact_sheet_builder.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_SAFE_STATUSES  = {"verified"}
_CAUTION_STATUSES = {"partially_supported", "uncertain"}


def _safe_facts(verified_claims: list[dict]) -> list[dict]:
    return [
        {
            "claim_id":       c["claim_id"],
            "claim_text":     c["claim_text"],
            "claim_type":     c["claim_type"],
            "confidence":     c["confidence_label"],
            "importance":     c.get("claim_importance", "medium"),
            "source_span_ids": c.get("evidence", {}).get("source_span_ids", []),
            "source_urls":    c.get("evidence", {}).get("source_urls", []),
        }
        for c in verified_claims
        if c.get("verification_status") in _SAFE_STATUSES
        and c.get("confidence_label") == "high"
    ]


def _cautious_facts(verified_claims: list[dict]) -> list[dict]:
    return [
        {
            "claim_id":            c["claim_id"],
            "claim_text":          c["claim_text"],
            "claim_type":          c["claim_type"],
            "confidence":          c["confidence_label"],
            "verification_status": c["verification_status"],
            "required_qualifier":  c.get("recommended_qualifier", ""),
            "source_span_ids":     c.get("evidence", {}).get("source_span_ids", []),
        }
        for c in verified_claims
        if (c.get("verification_status") in _CAUTION_STATUSES
            or c.get("confidence_label") in ("medium",)
            and c.get("verification_status") in _SAFE_STATUSES)
        and c.get("verification_status") not in ("rejected", "community_signal_only")
    ]


def _do_not_use(rejected_claims: list[dict]) -> list[dict]:
    return [
        {
            "claim_id":        c["claim_id"],
            "claim_text":      c["claim_text"],
            "rejection_reason": c.get("rejection_reason", "unsupported"),
            "required_action": "do_not_use",
        }
        for c in rejected_claims
    ]


def _format_safety(density: dict, contradictions: list[dict]) -> dict:
    high_sev = sum(1 for c in contradictions if c.get("severity") == "high")
    return {
        "roundup":    "safe"              if density.get("safe_for_roundup")   else "insufficient",
        "deep_dive":  "safe"              if density.get("safe_for_deep_dive") else "insufficient",
        "evergreen":  "safe"              if density.get("safe_for_evergreen") else "needs_more_context",
        "comparison": "safe"              if density.get("safe_for_comparison") else "not_applicable",
        "high_severity_contradictions": high_sev,
    }


def _handoff_recommendation(density: dict, gaps: list[dict],
                             contradictions: list[dict]) -> dict:
    high_gaps = sum(1 for g in gaps if g.get("severity") == "high")
    high_sev  = sum(1 for c in contradictions if c.get("severity") == "high")

    if high_sev >= 2 or high_gaps >= 2:
        caution = "high"
    elif high_sev >= 1 or high_gaps >= 1 or not density.get("safe_for_roundup"):
        caution = "medium"
    else:
        caution = "low"

    return {
        "safe_for_roundup":   density.get("safe_for_roundup", False),
        "safe_for_deep_dive": density.get("safe_for_deep_dive", False),
        "needs_more_research": len(gaps) > 0,
        "caution_level":      caution,
        "format_suitability": density.get("format_suitability", "insufficient_evidence"),
    }


def build(story_result: dict, contradiction_entry: dict,
          density_entry: dict) -> dict:
    """Build a fact sheet for one story."""
    sid = story_result["story_id"]
    verified = story_result.get("verified_claims", [])
    rejected = story_result.get("rejected_claims", [])
    contradictions = contradiction_entry.get("contradictions", [])
    density = density_entry.get("density", {})
    gaps = density_entry.get("evidence_gaps", [])

    sf = _safe_facts(verified)
    cf = _cautious_facts(verified)
    dnu = _do_not_use(rejected)
    fmt = _format_safety(density, contradictions)
    hoff = _handoff_recommendation(density, gaps, contradictions)

    return {
        "story_id":             sid,
        "canonical_story_title": story_result.get("story_title", ""),
        "story_type":           story_result.get("story_type", ""),
        "safe_facts":           sf,
        "cautious_facts":       cf,
        "do_not_use":           dnu,
        "contradictions":       contradictions,
        "evidence_gaps":        gaps,
        "evidence_summary": {
            "primary_source_count":     density.get("primary_source_count", 0),
            "independent_source_count": density.get("independent_source_count", 0),
            "research_source_count":    density.get("research_source_count", 0),
            "verified_claim_count":     density.get("verified_claim_count", 0),
            "evidence_density_score":   density.get("evidence_density_score", 0),
        },
        "format_safety":            fmt,
        "handoff_recommendation":   hoff,
    }


def build_all(verified_results: list[dict], contradiction_results: list[dict],
              density_results: list[dict]) -> list[dict]:
    """Build fact sheets for all stories."""
    contra_by_sid = {d["story_id"]: d for d in contradiction_results}
    density_by_sid = {d["story_id"]: d for d in density_results}

    return [
        build(
            story_result       = r,
            contradiction_entry = contra_by_sid.get(r["story_id"], {"contradictions": []}),
            density_entry       = density_by_sid.get(r["story_id"], {"density": {}, "evidence_gaps": []}),
        )
        for r in verified_results
    ]


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

    from pipelines.layer_4_evidence_intelligence.evidence_loader        import load
    from pipelines.layer_4_evidence_intelligence.span_selector          import select_all
    from pipelines.layer_4_evidence_intelligence.claim_extractor         import extract_all
    from pipelines.layer_4_evidence_intelligence.claim_evidence_linker   import link_all
    from pipelines.layer_4_evidence_intelligence.claim_deduplicator      import deduplicate_all
    from pipelines.layer_4_evidence_intelligence.claim_verifier          import verify_all
    from pipelines.layer_4_evidence_intelligence.contradiction_detector  import detect_all
    from pipelines.layer_4_evidence_intelligence.evidence_density_scorer import score_all

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result  = load(run_id, layer3_dir, layer2_dir)
    selections     = select_all(loader_result["evidence_bundles"], loader_result["spans_by_id"])
    story_results  = extract_all(selections[:3], run_id)
    linked         = link_all(story_results, loader_result["spans_by_id"], loader_result["docs_by_id"])
    deduped        = deduplicate_all(linked["enriched_story_results"])
    verified       = verify_all(deduped["deduped_results"])
    contras        = detect_all(verified)
    density_scores = score_all(verified, contras, loader_result["evidence_bundles"][:3])
    fact_sheets    = build_all(verified, contras, density_scores)

    print(f"\nStory Fact Sheet Builder — {run_id}")
    for fs in fact_sheets:
        print(f"\n  Story: {fs['canonical_story_title'][:60]}")
        print(f"    safe_facts    : {len(fs['safe_facts'])}")
        print(f"    cautious_facts: {len(fs['cautious_facts'])}")
        print(f"    do_not_use    : {len(fs['do_not_use'])}")
        print(f"    contradictions: {len(fs['contradictions'])}")
        print(f"    format_safety : roundup={fs['format_safety']['roundup']} "
              f"deep_dive={fs['format_safety']['deep_dive']}")
        print(f"    caution_level : {fs['handoff_recommendation']['caution_level']}")
        if fs["safe_facts"]:
            print(f"    Sample safe fact: {fs['safe_facts'][0]['claim_text'][:70]}")
