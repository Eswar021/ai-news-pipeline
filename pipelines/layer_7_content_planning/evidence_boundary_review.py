"""
Layer 7 — Module 12: Evidence Boundary Review

Scans the entire video plan for evidence boundary violations before script writing.

Checks:
  1. Section plan: no DNU claim IDs in required/optional lists
  2. Hook plan: no DNU claim IDs in supported_by_claim_ids
  3. Title plan: flag medium/high accuracy_risk titles as warnings
  4. Cautious claims: all must be in cautious_interpretation placement type

Status:
  passed        — no hard violations
  passed_with_warnings — soft issues only
  failed        — hard violations found (DNU in active plan)

Key function:
    review(section_plan, claim_placement_plan, hook_plan,
           title_thumbnail_plan, layer7_ctx) → boundary_review dict

Individual test:
    python evidence_boundary_review.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader          import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner  import refine
from pipelines.layer_7_content_planning.narrative_arc_planner   import plan as plan_arc
from pipelines.layer_7_content_planning.section_planner         import plan as plan_sections
from pipelines.layer_7_content_planning.claim_placement_planner import plan as plan_placement


def review(
    section_plan:          list[dict],
    claim_placement_plan:  list[dict],
    hook_plan:             dict,
    title_thumbnail_plan:  dict,
    layer7_ctx:            dict,
) -> dict:
    dnu_ids      = layer7_ctx.get("do_not_use_claim_ids", set())
    cautious_ids = layer7_ctx.get("cautious_claim_ids", set())

    errors   = []
    warnings = []

    # ── Check 1: Section plan — required claim_ids must not be DNU ────────────
    safe_claim_ids_used     = set()
    cautious_claim_ids_used = set()
    dnu_claim_ids_found     = set()

    for p in claim_placement_plan:
        cid   = p["claim_id"]
        ptype = p["placement_type"]

        if ptype == "do_not_use":
            dnu_claim_ids_found.add(cid)
            if p["priority"] == "required":
                errors.append(
                    f"DNU claim {cid} is marked required in section {p['section_key']}."
                )
        elif ptype == "cautious_interpretation":
            cautious_claim_ids_used.add(cid)
            if "language_note" not in p and cid in cautious_ids:
                warnings.append(
                    f"Cautious claim {cid} in {p['section_key']} has no language_note guidance."
                )
        else:
            safe_claim_ids_used.add(cid)

    # ── Check 2: Hook plan — no DNU in supported_by_claim_ids ────────────────
    rec_hook     = hook_plan.get("recommended_hook", {})
    hook_claim_ids = rec_hook.get("supported_by_claim_ids", [])
    dnu_in_hook  = [cid for cid in hook_claim_ids if cid in dnu_ids]
    if dnu_in_hook:
        errors.append(
            f"DNU claim(s) {dnu_in_hook} appear in recommended hook claim IDs."
        )

    for alt in hook_plan.get("alternative_hooks", []):
        alt_claims = alt.get("supported_by_claim_ids", [])
        dnu_alt    = [c for c in alt_claims if c in dnu_ids]
        if dnu_alt:
            warnings.append(
                f"DNU claim(s) {dnu_alt} in alternative hook. Script must not use this angle."
            )

    # ── Check 3: Title plan — flag medium/high risk titles ───────────────────
    for t in title_thumbnail_plan.get("recommended_title_angles", []):
        risk = t.get("accuracy_risk", "low")
        if risk == "high":
            errors.append(
                f"Title '{t['title'][:60]}' has high accuracy_risk and must be removed or revised."
            )
        elif risk == "medium":
            warnings.append({
                "type":                     "medium_risk_title",
                "title":                    t["title"],
                "required_script_handling": "Script must clarify uncertainty for this angle.",
            })

    # ── Check 4: Cautious claims must have guidance if used in required slots ─
    for p in claim_placement_plan:
        if p["placement_type"] == "cautious_interpretation" and p["priority"] == "required":
            if "language_note" not in p:
                warnings.append(
                    f"Required cautious claim {p['claim_id']} in {p['section_key']} "
                    f"is missing language_note."
                )

    passed = len(errors) == 0
    status = (
        "passed"               if passed and not warnings
        else "passed_with_warnings" if passed
        else "failed"
    )

    return {
        "status":                    status,
        "passed":                    passed,
        "safe_claim_ids_used":       sorted(safe_claim_ids_used),
        "cautious_claim_ids_used":   sorted(cautious_claim_ids_used),
        "do_not_use_claim_ids_found": sorted(dnu_claim_ids_found),
        "errors":                    errors,
        "warnings":                  warnings,
    }


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx        = load_packet(layer6_dir)
    strategy   = refine(ctx)
    arc        = plan_arc(ctx, strategy)
    sections   = plan_sections(ctx, arc)
    placements = plan_placement(sections, ctx)

    # Minimal hook/title stubs for test
    hook_stub  = {"recommended_hook": {"hook_type": "roundup_speed_hook",
                                        "supported_by_claim_ids": []},
                  "alternative_hooks": [], "blocked_hook_angles": []}
    tt_stub    = {"recommended_title_angles": [
                      {"title": "This Week in AI", "accuracy_risk": "low",
                       "angle_type": "weekly_roundup", "supported_by_claim_ids": []}
                  ], "blocked_title_angles": []}

    br = review(sections, placements, hook_stub, tt_stub, ctx)

    print(f"Status  : {br['status']}")
    print(f"Passed  : {br['passed']}")
    print(f"Safe IDs used     : {len(br['safe_claim_ids_used'])}")
    print(f"Cautious IDs used : {len(br['cautious_claim_ids_used'])}")
    print(f"DNU IDs found     : {len(br['do_not_use_claim_ids_found'])}")
    print(f"Errors  : {br['errors']}")
    print(f"Warnings: {len(br['warnings'])}")
