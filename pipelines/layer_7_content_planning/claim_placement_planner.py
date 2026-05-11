"""
Layer 7 — Module 5: Claim Placement Planner

Maps every claim to a section with a placement_type.
Cross-references section_plan required/optional/cautious lists.

Placement types:
  required_core_fact      — required claim in this section (script must use it)
  optional_supporting     — optional claim that adds depth (script may use it)
  cautious_interpretation — cautious claim; script must use qualifying language
  do_not_use              — DNU claim; listed for reference only, blocked from script

Key function:
    plan(section_plan, layer7_ctx) → claim_placement_plan list

Individual test:
    python claim_placement_planner.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader         import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner import refine
from pipelines.layer_7_content_planning.narrative_arc_planner  import plan as plan_arc
from pipelines.layer_7_content_planning.section_planner        import plan as plan_sections


def plan(section_plan: list[dict], layer7_ctx: dict) -> list[dict]:
    dnu_ids      = layer7_ctx.get("do_not_use_claim_ids", set())
    cautious_ids = layer7_ctx.get("cautious_claim_ids", set())
    result       = []

    for sec in section_plan:
        section_id  = sec["section_id"]
        section_key = sec["section_key"]

        for cid in sec.get("required_claim_ids", []):
            if cid in dnu_ids:
                ptype = "do_not_use"
                language_note = "BLOCKED — do not use in script."
            elif cid in cautious_ids:
                ptype = "cautious_interpretation"
                language_note = "Use may/could/suggests. Do not assert certainty."
            else:
                ptype = "required_core_fact"
                language_note = None

            entry = {
                "claim_id":       cid,
                "section_id":     section_id,
                "section_key":    section_key,
                "placement_type": ptype,
                "priority":       "required",
            }
            if language_note:
                entry["language_note"] = language_note
            result.append(entry)

        for cid in sec.get("cautious_claim_ids", []):
            entry = {
                "claim_id":       cid,
                "section_id":     section_id,
                "section_key":    section_key,
                "placement_type": "cautious_interpretation",
                "priority":       "required",
                "language_note":  "Use may/could/suggests. Do not assert certainty.",
            }
            result.append(entry)

        for cid in sec.get("optional_claim_ids", []):
            if cid in dnu_ids:
                continue  # skip DNU claims entirely from optional list
            ptype = (
                "cautious_interpretation"
                if cid in cautious_ids
                else "optional_supporting"
            )
            entry = {
                "claim_id":       cid,
                "section_id":     section_id,
                "section_key":    section_key,
                "placement_type": ptype,
                "priority":       "optional",
            }
            if ptype == "cautious_interpretation":
                entry["language_note"] = "Use may/could/suggests."
            result.append(entry)

    return result


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx      = load_packet(layer6_dir)
    strategy = refine(ctx)
    arc      = plan_arc(ctx, strategy)
    sections = plan_sections(ctx, arc)
    placements = plan(sections, ctx)

    required  = [p for p in placements if p["priority"] == "required"]
    optional_ = [p for p in placements if p["priority"] == "optional"]
    cautious  = [p for p in placements if p["placement_type"] == "cautious_interpretation"]
    dnu       = [p for p in placements if p["placement_type"] == "do_not_use"]

    print(f"Total placements : {len(placements)}")
    print(f"  Required       : {len(required)}")
    print(f"  Optional       : {len(optional_)}")
    print(f"  Cautious       : {len(cautious)}")
    print(f"  DNU (blocked)  : {len(dnu)}")
    print()
    print("Sample required placements:")
    for p in required[:6]:
        print(f"  {p['claim_id'][:20]:22s} → {p['section_key']:20s} [{p['placement_type']}]")
