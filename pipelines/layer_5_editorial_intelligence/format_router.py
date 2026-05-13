"""
Layer 5 — Module 7: Format Router

Makes per-story format recommendations based on format_fit_scores,
evidence safety, and novelty. Only routes to enabled formats
(roundup, deep_dive — as defined in format_config.yaml).

Routing rules:
  deep_dive       if deep_dive_score >= configured threshold AND evidence safe for deep_dive
  roundup_segment if roundup_score >= configured threshold  AND evidence safe for roundup
  monitor_only    if overall evidence blocked
  skip            if novelty_score < 45 (duplicate coverage)

Key function:
    route_all(candidates, format_fit_scores, safety_decisions, novelty_results)
        → list of format_routing dicts

Usage:
    python format_router.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_DEEP_DIVE_MIN_SCORE   = 80
_ROUNDUP_MIN_SCORE     = 65
_NOVELTY_SKIP_THRESHOLD = 45


def route(candidate: dict, format_fit: dict, evidence_safety: dict,
          novelty: dict, allowed_formats: list[str] | None = None,
          routing_rules: dict | None = None) -> dict:
    sid = candidate["story_id"]
    requested_formats = list(allowed_formats or ["roundup", "deep_dive"])
    routing_rules = routing_rules or {}

    novelty_score     = novelty.get("novelty_score", 90)
    overall_safe      = evidence_safety.get("overall_status") == "safe"
    roundup_safe      = evidence_safety.get("roundup", {}).get("status") == "safe"
    deep_dive_safe    = evidence_safety.get("deep_dive", {}).get("status") == "safe"
    roundup_score     = format_fit.get("roundup", {}).get("score", 0)
    deep_dive_score   = format_fit.get("deep_dive", {}).get("score", 0)
    deep_dive_threshold = int(routing_rules.get("deep_dive_threshold", _DEEP_DIVE_MIN_SCORE))
    roundup_threshold = int(routing_rules.get("roundup_threshold", _ROUNDUP_MIN_SCORE))

    # ── Skip for low novelty ──────────────────────────────────────────────────
    if novelty_score < _NOVELTY_SKIP_THRESHOLD:
        return {
            "story_id":           sid,
            "recommended_format": "skip",
            "secondary_format":   None,
            "routing_confidence": 0.90,
            "routing_reasons":    [f"Novelty score {novelty_score} — already covered."],
            "allowed_formats":    [],
            "profile_allowed_formats": requested_formats,
            "blocked_formats": [{
                "format": "all",
                "reason": "Already covered recently; novelty too low.",
            }],
        }

    # ── Block if overall unsafe ───────────────────────────────────────────────
    if not overall_safe:
        return {
            "story_id":           sid,
            "recommended_format": "monitor_only",
            "secondary_format":   None,
            "routing_confidence": 0.95,
            "routing_reasons":    ["All formats blocked by evidence safety gate."],
            "allowed_formats":    [],
            "profile_allowed_formats": requested_formats,
            "blocked_formats": [{
                "format": "all",
                "reason": "Insufficient evidence for any format.",
            }],
        }

    eligible_formats = []
    blocked_formats  = []
    routing_reasons  = []

    # ── Deep dive eligibility ─────────────────────────────────────────────────
    if "deep_dive" in requested_formats and deep_dive_safe and deep_dive_score >= deep_dive_threshold:
        eligible_formats.append("deep_dive")
        routing_reasons.append(
            f"Deep dive score {deep_dive_score} — strong evidence and viewer value."
        )
    elif "deep_dive" in requested_formats:
        reason = (
            f"Deep dive score {deep_dive_score} below threshold {deep_dive_threshold}."
            if deep_dive_safe else "Evidence safety blocked deep dive."
        )
        blocked_formats.append({"format": "deep_dive", "reason": reason})

    # ── Roundup eligibility ───────────────────────────────────────────────────
    if "roundup" in requested_formats and roundup_safe and roundup_score >= roundup_threshold:
        eligible_formats.append("roundup_segment")
        routing_reasons.append(
            f"Roundup score {roundup_score} — timely and audience-relevant."
        )
    elif "roundup" in requested_formats:
        reason = (
            f"Roundup score {roundup_score} below threshold {roundup_threshold}."
            if roundup_safe else "Evidence safety blocked roundup."
        )
        blocked_formats.append({"format": "roundup_segment", "reason": reason})

    # ── Pick recommended format ───────────────────────────────────────────────
    if not eligible_formats:
        recommended_format = "monitor_only"
        secondary_format   = None
        confidence         = 0.80
    elif "deep_dive" in eligible_formats and "roundup_segment" in eligible_formats:
        # Both eligible: recommend higher-scoring one; other is secondary
        if deep_dive_score >= roundup_score:
            recommended_format = "deep_dive"
            secondary_format   = "roundup_segment"
        else:
            recommended_format = "roundup_segment"
            secondary_format   = "deep_dive"
        confidence = round(max(deep_dive_score, roundup_score) / 100, 2)
    elif "deep_dive" in eligible_formats:
        recommended_format = "deep_dive"
        secondary_format   = None
        confidence         = round(deep_dive_score / 100, 2)
    else:
        recommended_format = "roundup_segment"
        secondary_format   = None
        confidence         = round(roundup_score / 100, 2)

    return {
        "story_id":           sid,
        "recommended_format": recommended_format,
        "secondary_format":   secondary_format,
        "routing_confidence": confidence,
        "routing_reasons":    routing_reasons,
        "allowed_formats":    eligible_formats,
        "profile_allowed_formats": requested_formats,
        "blocked_formats":    blocked_formats,
    }


def route_all(candidates: list[dict], format_fit_scores: list[dict],
              safety_decisions: list[dict], novelty_results: list[dict],
              allowed_formats: list[str] | None = None,
              routing_rules: dict | None = None) -> list[dict]:
    return [
        route(cand, ffs, sd, nv, allowed_formats=allowed_formats, routing_rules=routing_rules)
        for cand, ffs, sd, nv
        in zip(candidates, format_fit_scores, safety_decisions, novelty_results)
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
    from pipelines.layer_5_editorial_intelligence.format_fit_scorer      import score_all

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result     = load(run_id, layer3_dir, layer4_dir)
    candidates = result["editorial_candidates"]

    safety  = gate_all(candidates)
    af      = af_all(candidates)
    print("  Running LLM for viewer value...")
    vv      = vv_all(candidates)
    novelty = check_all(candidates)
    ffs     = score_all(candidates, safety, af, vv, novelty)
    routing = route_all(candidates, ffs, safety, novelty)

    print(f"\nFormat Router — {run_id}")
    for cand, r in zip(candidates, routing):
        sec = f" / {r['secondary_format']}" if r["secondary_format"] else ""
        print(f"  {cand['story_title'][:50]:50s}  → {r['recommended_format']}{sec}  "
              f"conf={r['routing_confidence']:.2f}")
