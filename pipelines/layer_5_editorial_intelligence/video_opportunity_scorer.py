"""
Layer 5 — Module 8: Video Opportunity Scorer

Computes the overall YouTube video opportunity score for each story.
Also estimates market gap signal (merged from design module 5.9) since
no external competitor data is available — uses channel positioning and
story type to derive a differentiation score.

Score weights (from design doc video_opportunity_rules):
  audience_fit    0.20
  viewer_value    0.20
  impact          0.15  — developer_impact from audience_fit result
  novelty         0.15
  market_gap      0.10  — channel differentiation potential
  evidence_safety 0.15  — 100 if any format safe, 0 if blocked
  visual_potential 0.05 — estimated from story type

Recommendation thresholds:
  >= 80 → strong_video_candidate
  >= 70 → acceptable_candidate
  >= 50 → weak_candidate
  < 50  → not_recommended

Key function:
    score_all(candidates, safety, audience_fits, viewer_values, novelty_results)
        → list of video_opportunity_score dicts

Usage:
    python video_opportunity_scorer.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

# Market saturation by story type (affects channel differentiation)
# High saturation = everyone covers it = higher differentiation opportunity for evidence-first channel
_MARKET_GAP_SCORE = {
    "model_release":               82,  # popular topic, evidence angle differentiates
    "product_launch":              80,
    "feature_release":             78,
    "pricing_or_plan_change":      75,
    "research_paper":              88,  # fewer channels cover rigorously → high gap
    "infrastructure_or_chip_news": 82,
    "ai_safety":                   85,
    "partnership":                 70,
    "funding_or_acquisition":      68,
    "tutorial_or_demo":            65,
    "regulatory":                  80,
    "unknown":                     65,
}

_VISUAL_POTENTIAL = {
    "model_release":               75,
    "product_launch":              80,
    "feature_release":             78,
    "pricing_or_plan_change":      70,
    "research_paper":              60,
    "infrastructure_or_chip_news": 65,
    "ai_safety":                   65,
    "partnership":                 70,
    "funding_or_acquisition":      65,
    "tutorial_or_demo":            85,
    "regulatory":                  60,
    "unknown":                     60,
}

_MARKET_SATURATION = {
    "model_release":               "high",
    "product_launch":              "medium",
    "pricing_or_plan_change":      "medium",
    "research_paper":              "low",
    "infrastructure_or_chip_news": "low",
    "ai_safety":                   "low",
    "regulatory":                  "low",
    "partnership":                 "medium",
    "funding_or_acquisition":      "medium",
    "tutorial_or_demo":            "medium",
    "unknown":                     "medium",
}


def score(candidate: dict, evidence_safety: dict, audience_fit: dict,
          viewer_value: dict, novelty: dict) -> dict:
    story_type = candidate.get("story_type", "unknown") or "unknown"

    audience_s   = audience_fit.get("audience_fit_score", 70)
    viewer_s     = viewer_value.get("viewer_value_score", 65)
    impact_s     = audience_fit.get("impact_dimensions", {}).get("developer_impact", 65)
    novelty_s    = novelty.get("novelty_score", 70)
    market_gap_s = _MARKET_GAP_SCORE.get(story_type, 70)
    visual_s     = _VISUAL_POTENTIAL.get(story_type, 65)
    safety_s     = 100 if evidence_safety.get("overall_status") == "safe" else 0

    opportunity_score = int(
        audience_s   * 0.20 +
        viewer_s     * 0.20 +
        impact_s     * 0.15 +
        novelty_s    * 0.15 +
        market_gap_s * 0.10 +
        safety_s     * 0.15 +
        visual_s     * 0.05
    )
    opportunity_score = max(0, min(100, opportunity_score))

    if opportunity_score >= 80:
        recommendation = "strong_video_candidate"
    elif opportunity_score >= 70:
        recommendation = "acceptable_candidate"
    elif opportunity_score >= 50:
        recommendation = "weak_candidate"
    else:
        recommendation = "not_recommended"

    saturation = _MARKET_SATURATION.get(story_type, "medium")
    gap_angle  = (
        "Evidence-based, practical take on a heavily-covered topic."
        if saturation == "high" else
        "Under-covered story type — strong differentiation opportunity."
        if saturation == "low" else
        "Moderate coverage; channel evidence-first angle differentiates."
    )

    return {
        "story_id":               candidate["story_id"],
        "video_opportunity_score": opportunity_score,
        "score_components": {
            "audience_fit":     audience_s,
            "viewer_value":     viewer_s,
            "developer_impact": impact_s,
            "novelty":          novelty_s,
            "market_gap":       market_gap_s,
            "evidence_safety":  safety_s,
            "visual_potential": visual_s,
        },
        "market_gap": {
            "market_saturation":     saturation,
            "gap_angle":             gap_angle,
            "gap_strength_score":    market_gap_s,
            "differentiation_strategy": "evidence-first, practical, low-hype",
        },
        "overall_recommendation": recommendation,
    }


def score_all(candidates: list[dict], safety_decisions: list[dict],
              audience_fits: list[dict], viewer_values: list[dict],
              novelty_results: list[dict]) -> list[dict]:
    return [
        score(cand, sd, af, vv, nv)
        for cand, sd, af, vv, nv
        in zip(candidates, safety_decisions, audience_fits, viewer_values, novelty_results)
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
            if (rp.parent / "layer_4" / "story_fact_sheets.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_5_editorial_intelligence.editorial_candidate_loader import load
    from pipelines.layer_5_editorial_intelligence.evidence_safety_gate   import gate_all
    from pipelines.layer_5_editorial_intelligence.audience_fit_analyzer  import analyze_all as af_all
    from pipelines.layer_5_editorial_intelligence.viewer_value_analyzer  import analyze_all as vv_all
    from pipelines.layer_5_editorial_intelligence.novelty_checker        import check_all

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result     = load(run_id, layer3_dir, layer4_dir)
    candidates = result["editorial_candidates"]

    safety  = gate_all(candidates)
    af      = af_all(candidates)
    print("  Running LLM for viewer value...")
    vv      = vv_all(candidates)
    novelty = check_all(candidates)

    opp_scores = score_all(candidates, safety, af, vv, novelty)
    print(f"\nVideo Opportunity Scorer — {run_id}")
    for cand, os_ in zip(candidates, opp_scores):
        print(f"  [{os_['video_opportunity_score']:3d}] {cand['story_title'][:52]:52s}  "
              f"{os_['overall_recommendation']}")
