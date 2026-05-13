"""
Layer 4 — Module 8: Evidence Density Scorer + Evidence Gap Detector

Scores evidence sufficiency for each story (0-100) and determines
which video formats can safely use this story.

Scoring (max 100):
  verified_claim_score  = min(verified_claims * 5, 50)   — 10 claims = 50pts
  primary_source_bonus  = 20 if has_primary_source else 0
  independent_bonus     = min(independent_sources * 5, 15)
  high_conf_bonus       = min(high_confidence_claims * 2, 10)
  contradiction_penalty = -10 per high-severity + -5 per medium-severity
  uncertainty_penalty   = -2 per uncertain claim (max -10)

Format safety thresholds (from design doc 11/evidence_density_rules.yaml):
  roundup   : verified_claims >= 2
  deep_dive : verified_claims >= 8 AND primary_source AND high_severity_contradictions == 0
  evergreen : verified_claims >= 10
  comparison: verified_claims >= 4

Evidence gap types:
  missing_primary_source           — no tier-1 source
  missing_independent_confirmation — no independent news/research source
  low_verified_claim_count         — fewer than 2 usable claims
  benchmark_without_research       — benchmark claims but no research source
  high_contradiction_count         — has high-severity contradictions

Also scores claim importance inline (folded from 4.14):
  core_fact           → importance=high    (event/product/feature/capability from tier1)
  supporting_fact     → importance=medium  (business/partnership/timeline)
  background_context  → importance=low     (interpretive, community_signal)

Key function:
    score_all(verified_results, contradiction_results, evidence_bundles)
        → list of {story_id, density_record, gap_records}

Usage:
    python evidence_density_scorer.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_CORE_TYPES = {
    "event_fact", "product_fact", "model_capability", "feature_claim",
    "timeline_fact", "statistic_claim", "benchmark_claim",
}
_SUPPORT_TYPES = {
    "business_claim", "partnership_claim", "pricing_claim",
    "research_claim", "quote_claim", "limitation_claim", "risk_claim",
}


def _importance(claim: dict) -> str:
    ctype = claim.get("claim_type", "event_fact")
    tier  = claim.get("trust_tier", 4)
    if ctype in _CORE_TYPES and tier <= 2:
        return "high"
    if ctype in _SUPPORT_TYPES:
        return "medium"
    return "low"


def score(story_result: dict, contradiction_entry: dict, evidence_bundle: dict, policy: dict) -> dict:
    """Score evidence density for one story."""
    sid = story_result["story_id"]
    verified_claims = story_result.get("verified_claims", [])
    rejected_claims = story_result.get("rejected_claims", [])
    contradictions  = contradiction_entry.get("contradictions", [])

    high_conf  = sum(1 for c in verified_claims if c.get("confidence_label") == "high")
    uncertain  = sum(1 for c in verified_claims if c.get("verification_status") == "uncertain")
    high_sev   = sum(1 for c in contradictions if c.get("severity") == "high")
    med_sev    = sum(1 for c in contradictions if c.get("severity") == "medium")

    # Source counts from cluster's source_mix
    cluster = evidence_bundle.get("cluster", {})
    source_mix = cluster.get("source_mix", {})
    primary_cnt     = source_mix.get("official_source_count", 0)
    independent_cnt = source_mix.get("independent_news_count", 0)
    research_cnt    = source_mix.get("research_source_count", 0)

    # Score
    claim_score   = min(len(verified_claims) * 5, 50)
    primary_bonus = 20 if primary_cnt > 0 else 0
    indep_bonus   = min(independent_cnt * 5, 15)
    conf_bonus    = min(high_conf * 2, 10)
    contra_penalty = high_sev * 10 + med_sev * 5
    uncertain_penalty = min(uncertain * 2, 10)

    density_score = max(
        claim_score + primary_bonus + indep_bonus + conf_bonus
        - contra_penalty - uncertain_penalty,
        0,
    )

    roundup_min_claims = int(policy.get("roundup_min_verified_claims", 2))
    deep_dive_min_claims = int(policy.get("deep_dive_min_verified_claims", 8))
    deep_dive_requires_primary = bool(policy.get("deep_dive_requires_primary_source", True))
    block_deep_dive_on_high_sev = bool(policy.get("high_severity_contradiction_blocks_deep_dive", True))

    # Format safety
    n_verified = len(verified_claims)
    safe_roundup = n_verified >= roundup_min_claims

    deep_dive_checks = [n_verified >= deep_dive_min_claims]
    if deep_dive_requires_primary:
        deep_dive_checks.append(primary_cnt >= 1)
    if block_deep_dive_on_high_sev:
        deep_dive_checks.append(high_sev == 0)
    safe_deep_dive = all(deep_dive_checks)

    safe_evergreen = n_verified >= 10
    safe_comparison = n_verified >= 4

    # Video format suitability label (for Layer 5)
    if safe_deep_dive:
        format_suitability = "deep_dive_ready"
    elif safe_roundup:
        format_suitability = "roundup_ready"
    else:
        format_suitability = "insufficient_evidence"

    # Evidence gaps
    gaps = []
    if primary_cnt == 0:
        gaps.append({
            "gap_type": "missing_primary_source",
            "severity": "high",
            "blocks_roundup": False,
            "blocks_deep_dive": True,
            "description": "No tier-1 official source found for this story.",
        })
    if independent_cnt == 0:
        gaps.append({
            "gap_type": "missing_independent_confirmation",
            "severity": "medium",
            "blocks_roundup": False,
            "blocks_deep_dive": n_verified < 8,
            "description": "No independent news or research source confirms the story.",
        })
    if n_verified < 2:
        gaps.append({
            "gap_type": "low_verified_claim_count",
            "severity": "high",
            "blocks_roundup": True,
            "blocks_deep_dive": True,
            "description": (
                f"Only {n_verified} verified claims — minimum {roundup_min_claims} "
                "required for roundup."
            ),
        })

    # Check benchmark claims without research source
    has_benchmark = any(c.get("claim_type") == "benchmark_claim" for c in verified_claims)
    if has_benchmark and research_cnt == 0:
        gaps.append({
            "gap_type": "benchmark_without_research",
            "severity": "medium",
            "blocks_roundup": False,
            "blocks_deep_dive": False,
            "description": "Benchmark claims present but no independent research source.",
        })

    if high_sev >= 2:
        gaps.append({
            "gap_type": "high_contradiction_count",
            "severity": "high",
            "blocks_roundup": False,
            "blocks_deep_dive": block_deep_dive_on_high_sev,
            "description": f"{high_sev} high-severity contradictions found.",
        })

    # Annotate verified claims with importance
    for claim in verified_claims:
        claim["claim_importance"] = _importance(claim)

    return {
        "story_id":    sid,
        "story_title": story_result.get("story_title", ""),
        "density": {
            "evidence_density_score":   density_score,
            "verified_claim_count":     n_verified,
            "rejected_claim_count":     len(rejected_claims),
            "high_confidence_count":    high_conf,
            "uncertain_count":          uncertain,
            "primary_source_count":     primary_cnt,
            "independent_source_count": independent_cnt,
            "research_source_count":    research_cnt,
            "contradiction_count":      len(contradictions),
            "high_sev_contradictions":  high_sev,
            "safe_for_roundup":         safe_roundup,
            "safe_for_deep_dive":       safe_deep_dive,
            "safe_for_evergreen":       safe_evergreen,
            "safe_for_comparison":      safe_comparison,
            "format_suitability":       format_suitability,
        },
        "evidence_gaps": gaps,
        "uncertainty_summary": {
            "uncertain_claim_count": uncertain,
            "high_confidence_count": high_conf,
        },
    }


def score_all(verified_results: list[dict], contradiction_results: list[dict],
              evidence_bundles: list[dict], policy: dict) -> list[dict]:
    """Score evidence density for all stories."""
    contra_by_sid = {d["story_id"]: d for d in contradiction_results}
    bundle_by_sid = {b["story_id"]: b for b in evidence_bundles}

    return [
        score(
            story_result    = r,
            contradiction_entry = contra_by_sid.get(r["story_id"], {"contradictions": []}),
            evidence_bundle = bundle_by_sid.get(r["story_id"], {}),
            policy=policy,
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

    from pipelines.layer_4_evidence_intelligence.evidence_loader       import load
    from pipelines.layer_4_evidence_intelligence.span_selector         import select_all
    from pipelines.layer_4_evidence_intelligence.claim_extractor        import extract_all
    from pipelines.layer_4_evidence_intelligence.claim_evidence_linker  import link_all
    from pipelines.layer_4_evidence_intelligence.claim_deduplicator     import deduplicate_all
    from pipelines.layer_4_evidence_intelligence.claim_verifier         import verify_all
    from pipelines.layer_4_evidence_intelligence.contradiction_detector import detect_all

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

    print(f"\nEvidence Density Scorer — {run_id}")
    for ds in density_scores:
        d = ds["density"]
        gaps = ds["evidence_gaps"]
        print(f"  {ds['story_title'][:45]:45s}  "
              f"score={d['evidence_density_score']:3}  "
              f"format={d['format_suitability']}  "
              f"gaps={len(gaps)}")
