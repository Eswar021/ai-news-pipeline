"""
Layer 7 — Module 8: Visual / B-roll Planner

Generates visual suggestions for each section.

Visual types:
  title_card         — section opener with story name
  source_screenshot  — official announcement source URL
  quote_card         — key claim text displayed on screen
  simple_diagram     — workflow or concept illustration idea
  caution_card       — limitation or uncertainty warning visual
  product_ui_ref     — reference to a product interface or demo

Logic:
  - intro_hook  → title_card (episode title + theme)
  - story sections → source_screenshot from source_pack + quote_card for lead claim
  - lead_story  → also suggest simple_diagram or product_ui_ref
  - final_takeaway → caution_card (what is still unknown)
  - cta         → no visual suggestion

Key function:
    plan(section_plan, layer7_ctx) → visual_plan list

Individual test:
    python visual_broll_planner.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader         import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner import refine
from pipelines.layer_7_content_planning.narrative_arc_planner  import plan as plan_arc
from pipelines.layer_7_content_planning.section_planner        import plan as plan_sections


def _find_source_for_story(story_id: str, sources: list[dict]) -> dict | None:
    if not story_id:
        return None
    suffix = story_id[-6:]
    for src in sources:
        title_lower = src.get("title", "").lower()
        url         = src.get("canonical_url", "")
        # Try to match by claim prefix embedded in source span_ids
        claim_ids_str = " ".join(src.get("claim_ids", []))
        if suffix in claim_ids_str:
            return src
    # Fallback: first source if only one
    return sources[0] if len(sources) == 1 else None


def _build_source_index(sources: list[dict]) -> dict:
    """Map first 6 chars of story suffix → source for quick lookup."""
    idx: dict = {}
    for src in sources:
        for cid in src.get("claim_ids", []):
            # claim_id pattern: claim_{storyid6}_{n}
            parts = cid.split("_")
            if len(parts) >= 2:
                suffix = parts[1]
                if suffix not in idx:
                    idx[suffix] = src
    return idx


def plan(section_plan: list[dict], layer7_ctx: dict) -> list[dict]:
    sources      = layer7_ctx.get("sources", [])
    sections_ctx = layer7_ctx.get("sections", [])
    packet_type  = layer7_ctx["packet_type"]

    # Build a quick lookup: story_id_suffix → source
    source_idx = _build_source_index(sources)

    # Also build a lookup: story_id → L6 section context (has required_claims)
    ctx_by_story = {s.get("story_id", ""): s for s in sections_ctx}

    visual_plan = []
    vis_counter = 1

    for sec in section_plan:
        key     = sec["section_key"]
        sec_id  = sec["section_id"]
        role    = sec["segment_role"]
        story_id = sec.get("story_id")

        if key == "intro_hook":
            visual_plan.append({
                "visual_id":       f"vis_{vis_counter:02d}",
                "section_id":      sec_id,
                "section_key":     key,
                "visual_type":     "title_card",
                "visual_goal":     "Display episode title and theme on screen.",
                "on_screen_text":  "THIS WEEK IN AI",
                "claim_ids":       [],
                "source_ref_url":  None,
                "notes":           "Keep minimal — theme text + channel brand.",
            })
            vis_counter += 1

        elif key.startswith("story_") and story_id:
            suffix = story_id[-6:]
            source = source_idx.get(suffix)

            # Source screenshot for this story
            if source:
                req_ids = sec.get("required_claim_ids", [])[:2]
                visual_plan.append({
                    "visual_id":       f"vis_{vis_counter:02d}",
                    "section_id":      sec_id,
                    "section_key":     key,
                    "visual_type":     "source_screenshot",
                    "visual_goal":     f"Show the official source for: {source.get('title','')[:50]}",
                    "source_ref_url":  source.get("canonical_url", ""),
                    "claim_ids":       req_ids,
                    "notes":           "Show title/headline area. Avoid cluttered page views.",
                })
                vis_counter += 1

            # Quote card for first required claim
            ctx_section = ctx_by_story.get(story_id, {})
            req_claims   = ctx_section.get("required_claims", [])
            if req_claims:
                top_claim = req_claims[0]
                visual_plan.append({
                    "visual_id":       f"vis_{vis_counter:02d}",
                    "section_id":      sec_id,
                    "section_key":     key,
                    "visual_type":     "quote_card",
                    "visual_goal":     "Show the key claim text as an on-screen callout.",
                    "on_screen_text":  top_claim["claim_text"][:80],
                    "claim_ids":       [top_claim["claim_id"]],
                    "source_ref_url":  None,
                    "notes":           "Display only — do not read the full text verbatim.",
                })
                vis_counter += 1

            # Lead story: add a diagram idea
            if role == "lead_story":
                visual_plan.append({
                    "visual_id":       f"vis_{vis_counter:02d}",
                    "section_id":      sec_id,
                    "section_key":     key,
                    "visual_type":     "simple_diagram",
                    "visual_goal":     "Illustrate the workflow or system change described in this story.",
                    "diagram_idea":    "Before/after: old workflow → AI-augmented workflow.",
                    "claim_ids":       [],
                    "source_ref_url":  None,
                    "notes":           "Keep simple — 2-3 boxes maximum.",
                })
                vis_counter += 1

        elif key == "final_takeaway":
            visual_plan.append({
                "visual_id":       f"vis_{vis_counter:02d}",
                "section_id":      sec_id,
                "section_key":     key,
                "visual_type":     "caution_card",
                "visual_goal":     "Visually signal what is still uncertain or early-stage.",
                "on_screen_text":  "WHAT'S STILL UNPROVEN",
                "claim_ids":       [],
                "source_ref_url":  None,
                "notes":           "Use this to transition from summary to limitations acknowledgement.",
            })
            vis_counter += 1

        # cta — no visual suggestion needed

    return visual_plan


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx         = load_packet(layer6_dir)
    strategy    = refine(ctx)
    arc         = plan_arc(ctx, strategy)
    sections    = plan_sections(ctx, arc)
    visual_plan = plan(sections, ctx)

    print(f"Visual suggestions : {len(visual_plan)}")
    print()
    for v in visual_plan:
        url = (v.get("source_ref_url") or "")[:45]
        txt = (v.get("on_screen_text") or v.get("diagram_idea") or "")[:50]
        print(f"  {v['visual_id']} | {v['visual_type']:18s} | sec={v['section_key']:20s} | {txt}")
