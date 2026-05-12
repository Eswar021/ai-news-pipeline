"""
Layer 7 — Module 13: Script Writer Brief Builder

Assembles all Layer 7 planning outputs into one clean brief for Layer 8.

Layer 8 reads ONLY this file — it should contain everything the script writer needs:
  - video identity (format, duration, audience, tone)
  - viewer strategy (question, promise, payoff)
  - hook instruction (type, direction, allowed claims)
  - section-by-section plan (goal, duration, required/optional claims, instructions)
  - evidence rules (safe, cautious, DNU claim IDs, blocked phrases)
  - visual notes per section
  - title/thumbnail recommendations
  - CTA instructions

Key function:
    build(run_id, layer7_ctx, viewer_strategy, hook_plan,
          section_plan, claim_placement_plan, pacing_plan,
          visual_plan, title_thumbnail_plan, cta_plan,
          boundary_review, research_packet_id) → brief dict

Individual test:
    python script_writer_brief_builder.py
"""

import sys
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader          import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner  import refine
from pipelines.layer_7_content_planning.narrative_arc_planner   import plan as plan_arc
from pipelines.layer_7_content_planning.section_planner         import plan as plan_sections
from pipelines.layer_7_content_planning.claim_placement_planner import plan as plan_placement
from pipelines.layer_7_content_planning.pacing_retention_planner import plan as plan_pacing
from pipelines.layer_7_content_planning.visual_broll_planner    import plan as plan_visuals
from pipelines.layer_7_content_planning.cta_planner             import plan as plan_cta
from pipelines.layer_7_content_planning.evidence_boundary_review import review


_BLOCKED_PHRASES = [
    "will replace developers",
    "will replace humans",
    "guaranteed to dominate",
    "proves the end of",
    "officially dead",
    "AI takes over",
    "jobs are gone",
]


def _sections_for_brief(
    section_plan:         list[dict],
    claim_placement_plan: list[dict],
    visual_plan:          list[dict],
) -> list[dict]:
    # Index placements by section_id
    placements_by_sec: dict = {}
    for p in claim_placement_plan:
        placements_by_sec.setdefault(p["section_id"], []).append(p)

    # Index visuals by section_id
    visuals_by_sec: dict = {}
    for v in visual_plan:
        visuals_by_sec.setdefault(v["section_id"], []).append(v)

    brief_sections = []
    for sec in section_plan:
        sec_id = sec["section_id"]
        ps     = placements_by_sec.get(sec_id, [])

        required_ids = [p["claim_id"] for p in ps
                        if p["placement_type"] == "required_core_fact" and p["priority"] == "required"]
        cautious_ids = [p["claim_id"] for p in ps
                        if p["placement_type"] == "cautious_interpretation"]
        optional_ids = [p["claim_id"] for p in ps
                        if p["priority"] == "optional" and p["placement_type"] == "optional_supporting"]

        vis_notes = [
            {"visual_type": v["visual_type"], "visual_goal": v["visual_goal"],
             "on_screen_text": v.get("on_screen_text"), "source_ref_url": v.get("source_ref_url")}
            for v in visuals_by_sec.get(sec_id, [])
        ]

        brief_sections.append({
            "section_id":              sec_id,
            "section_key":             sec["section_key"],
            "section_goal":            sec["section_goal"],
            "target_duration_seconds": sec["target_duration_seconds"],
            "story_id":                sec.get("story_id"),
            "segment_role":            sec.get("segment_role"),
            "required_claim_ids":      required_ids,
            "optional_claim_ids":      optional_ids,
            "cautious_claim_ids":      cautious_ids,
            "writer_instructions":     sec.get("writer_instructions", []),
            "visual_notes":            vis_notes,
        })

    return brief_sections


def build(
    run_id:               str,
    layer7_ctx:           dict,
    viewer_strategy:      dict,
    hook_plan:            dict,
    section_plan:         list[dict],
    claim_placement_plan: list[dict],
    pacing_plan:          dict,
    visual_plan:          list[dict],
    title_thumbnail_plan: dict,
    cta_plan:             dict,
    boundary_review:      dict,
    research_packet_id:   str,
) -> dict:
    now          = now_project_iso()
    packet_type  = layer7_ctx["packet_type"]
    total_dur    = pacing_plan["target_duration_seconds"]
    target_min   = round(total_dur / 60, 1)

    safe_ids = sorted(layer7_ctx.get("safe_claim_ids", set()))
    caut_ids = sorted(layer7_ctx.get("cautious_claim_ids", set()))
    dnu_ids  = sorted(layer7_ctx.get("do_not_use_claim_ids", set()))

    rec_hook = hook_plan.get("recommended_hook", {})
    sections_for_brief = _sections_for_brief(section_plan, claim_placement_plan, visual_plan)

    # Top title recommendation
    titles = title_thumbnail_plan.get("recommended_title_angles", [])
    low_risk_titles = [t for t in titles if t.get("accuracy_risk") == "low"]
    top_title = (low_risk_titles or titles or [{}])[0]

    brief_id = f"script_brief_{now[:10].replace('-', '')}_{run_id[-6:]}"

    return {
        "brief_id":               brief_id,
        "run_id":                 run_id,
        "research_packet_id":     research_packet_id,
        "generated_at":           now,

        "video_identity": {
            "selected_format":        packet_type,
            "target_duration_seconds": total_dur,
            "target_duration_minutes": target_min,
            "selected_video_id":      layer7_ctx.get("selected_video_id", ""),
            "selected_story_ids":     layer7_ctx.get("selected_story_ids", []),
            "primary_story_id":       layer7_ctx.get("primary_story_id"),
        },

        "viewer_strategy": {
            "target_audience":        viewer_strategy.get("target_audience", "technical_but_accessible"),
            "tone":                   viewer_strategy.get("tone", "fast, clear, analytical, evidence-first"),
            "central_viewer_question": viewer_strategy.get("central_viewer_question", ""),
            "refined_viewer_promise": viewer_strategy.get("refined_viewer_promise", ""),
            "viewer_payoff":          viewer_strategy.get("viewer_payoff", []),
        },

        "hook_instruction": {
            "hook_type":              rec_hook.get("hook_type", ""),
            "direction":              rec_hook.get("hook_direction", ""),
            "allowed_claim_ids":      rec_hook.get("supported_by_claim_ids", []),
            "risk_level":             rec_hook.get("risk_level", "low"),
            "why_it_works":           rec_hook.get("why_it_works", ""),
            "blocked_hook_angles":    hook_plan.get("blocked_hook_angles", []),
        },

        "sections":                   sections_for_brief,

        "evidence_rules": {
            "safe_claim_ids":         safe_ids,
            "cautious_claim_ids":     caut_ids,
            "do_not_use_claim_ids":   dnu_ids,
            "blocked_phrases":        _BLOCKED_PHRASES,
            "cautious_language_rule": (
                "For any cautious_claim_id, use qualifying language: "
                "may, could, suggests, appears to. Do not assert certainty."
            ),
        },

        "retention_beats":            pacing_plan.get("retention_beats", []),
        "pacing_avoid":               pacing_plan.get("pacing_avoid", []),

        "title_recommendation": {
            "top_title":              top_title.get("title", ""),
            "angle_type":             top_title.get("angle_type", ""),
            "all_title_options":      titles,
            "thumbnail_text_options": title_thumbnail_plan.get("thumbnail_text_options", []),
            "blocked_title_angles":   title_thumbnail_plan.get("blocked_title_angles", []),
        },

        "cta_instructions": {
            "comment_prompt":         cta_plan.get("comment_prompt", ""),
            "subscribe_cta_timing":   cta_plan.get("subscribe_cta_timing", "near_end"),
            "placement_note":         cta_plan.get("placement_note", ""),
        },

        "evidence_boundary_review_status": boundary_review.get("status", "unknown"),
        "boundary_review_warnings":        boundary_review.get("warnings", []),

        "handoff": {
            "ready_for_layer_8": boundary_review.get("passed", False),
            "next_layer":        "layer_8_script_generation",
        },
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
    pacing     = plan_pacing(sections, ctx)
    visuals    = plan_visuals(sections, ctx)
    cta        = plan_cta(ctx, strategy)

    # Stub hook + titles for individual test (no LLM call here)
    hook_stub = {"recommended_hook": {
                     "hook_type": "roundup_speed_hook",
                     "hook_direction": "Open with the pace of this week's AI releases — multiple layers shipping at once.",
                     "supported_by_claim_ids": [],
                     "risk_level": "low",
                     "why_it_works": "Creates curiosity about which update matters most."
                 }, "alternative_hooks": [], "blocked_hook_angles": []}
    tt_stub   = {"recommended_title_angles": [
                     {"title": "This Week in AI: Coding Agents, Voice Models, and Trust Governance",
                      "angle_type": "weekly_roundup", "accuracy_risk": "low",
                      "click_potential": "medium_high", "supported_by_claim_ids": []}
                 ], "thumbnail_text_options": [
                     {"text": "THIS WEEK IN AI", "risk": "low"}
                 ], "blocked_title_angles": []}

    br    = review(sections, placements, hook_stub, tt_stub, ctx)
    brief = build(
        run_id=run_id, layer7_ctx=ctx, viewer_strategy=strategy,
        hook_plan=hook_stub, section_plan=sections,
        claim_placement_plan=placements, pacing_plan=pacing,
        visual_plan=visuals, title_thumbnail_plan=tt_stub,
        cta_plan=cta, boundary_review=br,
        research_packet_id=ctx["research_packet_id"],
    )

    print(f"Brief ID          : {brief['brief_id']}")
    print(f"Format            : {brief['video_identity']['selected_format']}")
    print(f"Duration          : {brief['video_identity']['target_duration_seconds']}s "
          f"({brief['video_identity']['target_duration_minutes']} min)")
    print(f"Sections          : {len(brief['sections'])}")
    print(f"Safe claim IDs    : {len(brief['evidence_rules']['safe_claim_ids'])}")
    print(f"Cautious claim IDs: {len(brief['evidence_rules']['cautious_claim_ids'])}")
    print(f"DNU claim IDs     : {len(brief['evidence_rules']['do_not_use_claim_ids'])}")
    print(f"Hook type         : {brief['hook_instruction']['hook_type']}")
    print(f"Top title         : {brief['title_recommendation']['top_title']}")
    print(f"Ready for L8      : {brief['handoff']['ready_for_layer_8']}")
    print(f"Boundary review   : {brief['evidence_boundary_review_status']}")
    print()
    print("Section summary:")
    for s in brief["sections"]:
        print(f"  {s['section_id']} | {s['section_key']:20s} | {s['target_duration_seconds']:3d}s | "
              f"required={len(s['required_claim_ids'])} | visuals={len(s['visual_notes'])}")
