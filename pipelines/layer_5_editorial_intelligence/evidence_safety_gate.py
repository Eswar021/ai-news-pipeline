"""
Layer 5 — Module 2: Evidence Safety Gate

Determines per-story, per-format evidence safety using Layer 4 density data.
Only evaluates formats that are enabled (roundup, deep_dive).

Safety rules:
  roundup  — safe if: safe_for_roundup=True AND verified_claim_count >= 2
  deep_dive — safe if: safe_for_deep_dive=True AND primary_source_count >= 1
                       AND verified_claim_count >= 8 AND high_sev_contradictions == 0

Overall status:
  safe    — at least one format is safe
  blocked — no format is safe

Key function:
    gate_all(candidates) → list of evidence_safety dicts

Usage:
    python evidence_safety_gate.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_ROUNDUP_MIN_CLAIMS  = 2
_DEEP_DIVE_MIN_CLAIMS = 8


def gate(candidate: dict) -> dict:
    """
    Evaluate evidence safety for a single editorial candidate.
    Returns a flat evidence_safety record.
    """
    sid = candidate["story_id"]
    n_verified     = candidate["verified_claim_count"]
    n_primary      = candidate["primary_source_count"]
    high_sev_contra = candidate["high_sev_contradictions"]
    blocking_gaps   = candidate["blocking_gaps"]

    # ── Roundup ───────────────────────────────────────────────────────────────
    if candidate["safe_for_roundup"] and n_verified >= _ROUNDUP_MIN_CLAIMS:
        roundup_status = "safe"
        roundup_reason = f"{n_verified} verified claims; roundup threshold met."
    elif n_verified < _ROUNDUP_MIN_CLAIMS:
        roundup_status = "blocked"
        roundup_reason = f"Only {n_verified} verified claims; need {_ROUNDUP_MIN_CLAIMS}."
    else:
        roundup_status = "blocked"
        roundup_reason = "Layer 4 evidence density gate blocked roundup."

    # ── Deep Dive ─────────────────────────────────────────────────────────────
    if (candidate["safe_for_deep_dive"]
            and n_primary >= 1
            and n_verified >= _DEEP_DIVE_MIN_CLAIMS
            and high_sev_contra == 0):
        deep_dive_status = "safe"
        deep_dive_reason = (f"{n_verified} verified claims, "
                            f"{n_primary} primary source(s); deep dive threshold met.")
    elif n_verified < _DEEP_DIVE_MIN_CLAIMS:
        deep_dive_status = "blocked"
        deep_dive_reason = f"Only {n_verified} verified claims; need {_DEEP_DIVE_MIN_CLAIMS}."
    elif n_primary < 1:
        deep_dive_status = "blocked"
        deep_dive_reason = "No primary source; deep dive requires at least one."
    elif high_sev_contra > 0:
        deep_dive_status = "blocked"
        deep_dive_reason = f"{high_sev_contra} high-severity contradiction(s) unresolved."
    else:
        deep_dive_status = "blocked"
        deep_dive_reason = "Layer 4 evidence density gate blocked deep dive."

    # ── Blocking gaps ─────────────────────────────────────────────────────────
    blocking_roundup_gaps  = [g for g in blocking_gaps if g.get("blocks_roundup")]
    blocking_deepdive_gaps = [g for g in blocking_gaps if g.get("blocks_deep_dive")]
    if blocking_roundup_gaps and roundup_status == "safe":
        roundup_status = "blocked"
        roundup_reason = f"Blocking evidence gap: {blocking_roundup_gaps[0]['gap_type']}."
    if blocking_deepdive_gaps and deep_dive_status == "safe":
        deep_dive_status = "blocked"
        deep_dive_reason = f"Blocking evidence gap: {blocking_deepdive_gaps[0]['gap_type']}."

    # ── Overall ───────────────────────────────────────────────────────────────
    any_safe = roundup_status == "safe" or deep_dive_status == "safe"
    overall_status = "safe" if any_safe else "blocked"
    overall_reason = "" if any_safe else "No format passed the evidence safety gate."

    return {
        "story_id":         sid,
        "overall_status":   overall_status,
        "overall_reason":   overall_reason,
        "roundup": {
            "status": roundup_status,
            "reason": roundup_reason,
        },
        "deep_dive": {
            "status": deep_dive_status,
            "reason": deep_dive_reason,
        },
        "evergreen":   {"status": "not_applicable", "reason": "Format disabled."},
        "comparison":  {"status": "not_applicable", "reason": "Format disabled."},
        "follow_up":   {"status": "not_applicable", "reason": "Format disabled."},
    }


def gate_all(candidates: list[dict]) -> list[dict]:
    return [gate(c) for c in candidates]


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
    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result = load(run_id, layer3_dir, layer4_dir)
    candidates = result["editorial_candidates"]

    safety_decisions = gate_all(candidates)
    n_safe    = sum(1 for s in safety_decisions if s["overall_status"] == "safe")
    n_blocked = sum(1 for s in safety_decisions if s["overall_status"] == "blocked")
    print(f"\nEvidence Safety Gate — {run_id}")
    print(f"  Safe   : {n_safe}")
    print(f"  Blocked: {n_blocked}")
    for cand, sd in zip(candidates, safety_decisions):
        rnd = sd["roundup"]["status"]
        dd  = sd["deep_dive"]["status"]
        print(f"  {cand['story_title'][:50]:50s}  roundup={rnd:<8} deep_dive={dd}")
