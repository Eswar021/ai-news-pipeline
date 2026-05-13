"""
Layer 5 — Module 6: Format Fit Scorer

Scores each story against each manifest-allowed format.
Consumes evidence safety, audience fit, viewer value, and novelty results.

Roundup score weights:
  evidence_safety  0.30  — blocked = 0, safe = 100
  audience_fit     0.20
  viewer_value     0.20
  timeliness       0.15  — product/model news scores high
  compressibility  0.15  — can it fit in 60–120s? (estimated)

Deep dive score weights:
  evidence_safety  0.25  — blocked = 0, safe = 100
  claim_density    0.20  — verified_claim_count relative to deep_dive min (8)
  audience_fit     0.20
  viewer_value     0.15
  novelty          0.10
  primary_source   0.10  — 100 if primary_source >= 1, else 50

Key function:
    score_all(candidates, safety, audience_fit, viewer_value, novelty)
        → list of format_fit_score dicts

Usage:
    python format_fit_scorer.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_DEEP_DIVE_MIN_CLAIMS = 8

# Story type → timeliness score for roundup
_TIMELINESS = {
    "model_release":               88,
    "product_launch":              85,
    "feature_release":             85,
    "pricing_or_plan_change":      82,
    "infrastructure_or_chip_news": 75,
    "funding_or_acquisition":      72,
    "partnership":                 68,
    "ai_safety":                   70,
    "research_paper":              55,
    "tutorial_or_demo":            60,
    "regulatory":                  65,
    "unknown":                     55,
}

# Story type → compressibility (can it be told in 60–120 seconds?)
_COMPRESSIBILITY = {
    "model_release":               82,
    "product_launch":              85,
    "pricing_or_plan_change":      90,
    "feature_release":             85,
    "funding_or_acquisition":      88,
    "partnership":                 85,
    "infrastructure_or_chip_news": 75,
    "ai_safety":                   70,
    "tutorial_or_demo":            72,
    "research_paper":              55,
    "regulatory":                  68,
    "unknown":                     65,
}


def _safety_score(evidence_safety: dict, fmt: str) -> int:
    status = evidence_safety.get(fmt, {}).get("status", "blocked")
    return 100 if status == "safe" else 0


def _claim_density_score(verified_count: int) -> int:
    if verified_count >= 20:
        return 100
    if verified_count >= 15:
        return 90
    if verified_count >= _DEEP_DIVE_MIN_CLAIMS:
        return int(50 + (verified_count - _DEEP_DIVE_MIN_CLAIMS) / (15 - _DEEP_DIVE_MIN_CLAIMS) * 40)
    return int(verified_count / _DEEP_DIVE_MIN_CLAIMS * 50)


def score_roundup(candidate: dict, evidence_safety: dict,
                  audience_fit: dict, viewer_value: dict) -> dict:
    story_type = candidate.get("story_type", "unknown") or "unknown"

    safety_s       = _safety_score(evidence_safety, "roundup")
    audience_s     = audience_fit.get("audience_fit_score", 70)
    viewer_s       = viewer_value.get("viewer_value_score", 65)
    timeliness_s   = _TIMELINESS.get(story_type, 65)
    compress_s     = _COMPRESSIBILITY.get(story_type, 70)

    score = int(
        safety_s     * 0.30 +
        audience_s   * 0.20 +
        viewer_s     * 0.20 +
        timeliness_s * 0.15 +
        compress_s   * 0.15
    )

    if safety_s == 0:
        fit = "blocked"
        reason = "Evidence safety gate blocked roundup."
    elif score >= 80:
        fit = "strong"
        reason = "Timely, relevant, and clearly explainable in a short segment."
    elif score >= 65:
        fit = "good"
        reason = "Fits roundup format with adequate evidence and audience relevance."
    else:
        fit = "weak"
        reason = "Marginal fit — low timeliness or audience relevance."

    return {
        "score":  score,
        "fit":    fit,
        "reason": reason,
    }


def score_deep_dive(candidate: dict, evidence_safety: dict,
                    audience_fit: dict, viewer_value: dict,
                    novelty: dict) -> dict:
    story_type    = candidate.get("story_type", "unknown") or "unknown"
    n_verified    = candidate.get("verified_claim_count", 0)
    n_primary     = candidate.get("primary_source_count", 0)

    safety_s       = _safety_score(evidence_safety, "deep_dive")
    claim_s        = _claim_density_score(n_verified)
    audience_s     = audience_fit.get("audience_fit_score", 70)
    viewer_s       = viewer_value.get("viewer_value_score", 65)
    novelty_s      = novelty.get("novelty_score", 70)
    primary_s      = 100 if n_primary >= 1 else 50

    score = int(
        safety_s   * 0.25 +
        claim_s    * 0.20 +
        audience_s * 0.20 +
        viewer_s   * 0.15 +
        novelty_s  * 0.10 +
        primary_s  * 0.10
    )

    if safety_s == 0:
        fit = "blocked"
        reason = "Evidence safety gate blocked deep dive."
    elif n_primary < 1:
        fit = "weak"
        reason = "No primary source; deep dive reliability is reduced."
    elif score >= 85:
        fit = "strong"
        reason = f"High evidence density ({n_verified} claims), primary source, strong viewer value."
    elif score >= 75:
        fit = "good"
        reason = f"{n_verified} verified claims and clear viewer question support a full deep dive."
    elif score >= 60:
        fit = "moderate"
        reason = "Sufficient evidence but limited depth or audience appeal for standalone video."
    else:
        fit = "weak"
        reason = "Insufficient evidence density or weak viewer value for deep dive format."

    return {
        "score":  score,
        "fit":    fit,
        "reason": reason,
    }


def score(
    candidate: dict,
    evidence_safety: dict,
    audience_fit: dict,
    viewer_value: dict,
    novelty: dict,
    allowed_formats: list[str] | None = None,
) -> dict:
    allowed = allowed_formats or ["roundup", "deep_dive"]
    payload = {
        "story_id": candidate["story_id"],
        "allowed_formats": list(allowed),
    }
    if "roundup" in allowed:
        payload["roundup"] = score_roundup(candidate, evidence_safety, audience_fit, viewer_value)
    if "deep_dive" in allowed:
        payload["deep_dive"] = score_deep_dive(candidate, evidence_safety, audience_fit, viewer_value, novelty)
    return payload


def score_all(candidates: list[dict], safety_decisions: list[dict],
              audience_fits: list[dict], viewer_values: list[dict],
              novelty_results: list[dict], allowed_formats: list[str] | None = None) -> list[dict]:
    return [
        score(cand, sd, af, vv, nv, allowed_formats=allowed_formats)
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
    from pipelines.layer_5_editorial_intelligence.evidence_safety_gate import gate_all
    from pipelines.layer_5_editorial_intelligence.audience_fit_analyzer import analyze_all
    from pipelines.layer_5_editorial_intelligence.viewer_value_analyzer import analyze_all as vv_all
    from pipelines.layer_5_editorial_intelligence.novelty_checker import check_all

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result     = load(run_id, layer3_dir, layer4_dir)
    candidates = result["editorial_candidates"]

    safety   = gate_all(candidates)
    af       = analyze_all(candidates)
    print("  Running LLM for viewer value...")
    vv       = vv_all(candidates)
    novelty  = check_all(candidates)

    scores = score_all(candidates, safety, af, vv, novelty)
    print(f"\nFormat Fit Scorer — {run_id}")
    for cand, fs in zip(candidates, scores):
        r = fs["roundup"]
        d = fs["deep_dive"]
        print(f"  {cand['story_title'][:48]:48s}  "
              f"roundup={r['score']:3d}({r['fit']:<8})  "
              f"deep_dive={d['score']:3d}({d['fit']})")
