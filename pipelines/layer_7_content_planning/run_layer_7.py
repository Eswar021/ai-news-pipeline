"""
Layer 7 Orchestrator — Content Planning

Reads Layer 6 output and builds a full video plan + script_writer_brief.

Processing pipeline:
  1.  packet_loader            → load + validate Layer 6 packet
  2.  viewer_promise_refiner   → refine viewer promise into planning statement
  3.  narrative_arc_planner    → build narrative arc + story flow
  4.  section_planner          → build section-by-section plan
  5.  claim_placement_planner  → map claims to placement types
  6.  transition_planner       → plan transitions between sections
  7.  pacing_retention_planner → time budgets + retention beats
  8.  visual_broll_planner     → visual suggestions per section
  9.  hook_planner             → LLM: 3 hook directions + blocked angles
  10. title_thumbnail_planner  → LLM: 6-8 titles + 5 thumbnail texts
  11. cta_planner              → CTA + engagement plan
  12. evidence_boundary_review → scan all plans for DNU violations
  13. script_writer_brief_builder → assemble final brief for Layer 8
  14. layer7_writer            → write all 13 output files
  15. layer7_validation_gate   → validate output, write report

Output:
    data/runs/{run_id}/layer_7/
      video_plan.json
      hook_plan.json
      narrative_plan.json
      section_plan.json
      claim_placement_plan.json
      transition_plan.json
      pacing_retention_plan.json
      visual_plan.json
      title_thumbnail_plan.json
      cta_plan.json
      evidence_boundary_review.json
      script_writer_brief.json
      layer7_manifest.json
      layer7_validation_report.json

Usage:
    python run_layer_7.py --run-id run_2026_05_10_48h_auto
    python run_layer_7.py   # auto-discovers latest run with Layer 6 output
"""

import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_7_content_planning.packet_loader              import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner     import refine
from pipelines.layer_7_content_planning.narrative_arc_planner      import plan as plan_arc
from pipelines.layer_7_content_planning.section_planner            import plan as plan_sections
from pipelines.layer_7_content_planning.claim_placement_planner    import plan as plan_placement
from pipelines.layer_7_content_planning.transition_planner         import plan as plan_transitions
from pipelines.layer_7_content_planning.pacing_retention_planner   import plan as plan_pacing
from pipelines.layer_7_content_planning.visual_broll_planner       import plan as plan_visuals
from pipelines.layer_7_content_planning.hook_planner               import plan as plan_hook
from pipelines.layer_7_content_planning.title_thumbnail_planner    import plan as plan_titles
from pipelines.layer_7_content_planning.cta_planner                import plan as plan_cta
from pipelines.layer_7_content_planning.evidence_boundary_review   import review
from pipelines.layer_7_content_planning.script_writer_brief_builder import build as build_brief
from pipelines.layer_7_content_planning.layer7_writer              import write
from pipelines.layer_7_content_planning.layer7_validation_gate     import validate, write_report


def run_layer_7(run_id: str) -> dict:
    started_at = datetime.now(timezone.utc)

    layer6_dir = RUNS_DIR / run_id / "layer_6"
    layer7_dir = RUNS_DIR / run_id / "layer_7"

    print(f"[Layer 7] Run    : {run_id}")
    print(f"[Layer 7] Input  : {layer6_dir}")
    print(f"[Layer 7] Output : {layer7_dir}\n")

    # ── Step 1: Load packet ──────────────────────────────────────────────────
    print("[Layer 7] Step 1 — Loading Layer 6 packet...")
    ctx = load_packet(layer6_dir)
    print(f"  Format: {ctx['selected_format']}  Stories: {len(ctx['selected_story_ids'])}  "
          f"Safe claims: {len(ctx['safe_claim_ids'])}  DNU: {len(ctx['do_not_use_claim_ids'])}")

    # ── Step 2: Viewer promise ───────────────────────────────────────────────
    print("[Layer 7] Step 2 — Refining viewer promise...")
    viewer_strategy = refine(ctx)
    print(f"  Question: {viewer_strategy['central_viewer_question'][:70]}")

    # ── Step 3: Narrative arc ────────────────────────────────────────────────
    print("[Layer 7] Step 3 — Planning narrative arc...")
    narrative_plan = plan_arc(ctx, viewer_strategy)
    print(f"  Arc: {narrative_plan['narrative_arc'][:70]}")
    print(f"  Stages: {narrative_plan['total_stages']}")

    # ── Step 4: Section plan ─────────────────────────────────────────────────
    print("[Layer 7] Step 4 — Building section plan...")
    section_plan = plan_sections(ctx, narrative_plan)
    total_dur    = sum(s["target_duration_seconds"] for s in section_plan)
    print(f"  Sections: {len(section_plan)}  Total: {total_dur}s ({total_dur/60:.1f} min)")

    # ── Step 5: Claim placement ──────────────────────────────────────────────
    print("[Layer 7] Step 5 — Planning claim placement...")
    claim_placement_plan = plan_placement(section_plan, ctx)
    req_count  = sum(1 for p in claim_placement_plan if p["priority"] == "required")
    opt_count  = sum(1 for p in claim_placement_plan if p["priority"] == "optional")
    print(f"  Total placements: {len(claim_placement_plan)}  Required: {req_count}  Optional: {opt_count}")

    # ── Step 6: Transitions ──────────────────────────────────────────────────
    print("[Layer 7] Step 6 — Planning transitions...")
    transition_plan = plan_transitions(section_plan, ctx)
    print(f"  Transitions: {len(transition_plan)}")

    # ── Step 7: Pacing + retention ───────────────────────────────────────────
    print("[Layer 7] Step 7 — Planning pacing + retention...")
    pacing_plan = plan_pacing(section_plan, ctx)
    print(f"  Duration: {pacing_plan['target_duration_seconds']}s  "
          f"Beats: {len(pacing_plan['retention_beats'])}")

    # ── Step 8: Visuals ──────────────────────────────────────────────────────
    print("[Layer 7] Step 8 — Planning visuals...")
    visual_plan = plan_visuals(section_plan, ctx)
    print(f"  Visual suggestions: {len(visual_plan)}")

    # ── Step 9: Hook planner (LLM) ───────────────────────────────────────────
    print("[Layer 7] Step 9 — Planning hook (LLM)...")
    hook_plan = plan_hook(ctx, section_plan)
    rec_hook  = hook_plan.get("recommended_hook", {})
    print(f"  Hook type: {rec_hook.get('hook_type')}  "
          f"Risk: {rec_hook.get('risk_level')}  "
          f"Alts: {len(hook_plan.get('alternative_hooks', []))}")

    # ── Step 10: Titles + thumbnails (LLM) ───────────────────────────────────
    print("[Layer 7] Step 10 — Planning titles + thumbnails (LLM)...")
    title_thumbnail_plan = plan_titles(ctx, hook_plan)
    print(f"  Titles: {title_thumbnail_plan['title_count']}  "
          f"Thumbnails: {title_thumbnail_plan['thumbnail_text_count']}")

    # ── Step 11: CTA plan ────────────────────────────────────────────────────
    print("[Layer 7] Step 11 — Planning CTA...")
    cta_plan = plan_cta(ctx, viewer_strategy)
    print(f"  Style: {cta_plan['cta_style']}")

    # ── Step 12: Evidence boundary review ────────────────────────────────────
    print("[Layer 7] Step 12 — Evidence boundary review...")
    boundary_review = review(
        section_plan, claim_placement_plan, hook_plan, title_thumbnail_plan, ctx
    )
    print(f"  Status: {boundary_review['status']}  "
          f"Errors: {len(boundary_review['errors'])}  "
          f"Warnings: {len(boundary_review['warnings'])}")

    # ── Step 13: Script writer brief ─────────────────────────────────────────
    print("[Layer 7] Step 13 — Building script writer brief...")
    script_writer_brief = build_brief(
        run_id=run_id, layer7_ctx=ctx, viewer_strategy=viewer_strategy,
        hook_plan=hook_plan, section_plan=section_plan,
        claim_placement_plan=claim_placement_plan, pacing_plan=pacing_plan,
        visual_plan=visual_plan, title_thumbnail_plan=title_thumbnail_plan,
        cta_plan=cta_plan, boundary_review=boundary_review,
        research_packet_id=ctx["research_packet_id"],
    )
    print(f"  Brief ID: {script_writer_brief['brief_id']}")
    print(f"  Ready for Layer 8: {script_writer_brief['handoff']['ready_for_layer_8']}")

    # ── Step 14: Write output files ───────────────────────────────────────────
    print("[Layer 7] Step 14 — Writing output files...")
    manifest = write(
        run_id=run_id, layer7_dir=layer7_dir, layer6_dir=layer6_dir,
        layer7_ctx=ctx, viewer_strategy=viewer_strategy,
        hook_plan=hook_plan, narrative_plan=narrative_plan,
        section_plan=section_plan, claim_placement_plan=claim_placement_plan,
        transition_plan=transition_plan, pacing_plan=pacing_plan,
        visual_plan=visual_plan, title_thumbnail_plan=title_thumbnail_plan,
        cta_plan=cta_plan, boundary_review=boundary_review,
        script_writer_brief=script_writer_brief,
    )
    print(f"  Output: {layer7_dir}")

    # ── Step 15: Validate ────────────────────────────────────────────────────
    print("[Layer 7] Step 15 — Validating output...")
    val_report = validate(run_id, layer7_dir)
    write_report(run_id, val_report, layer7_dir)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*58}")
    print(f"Layer 7 {'PASSED' if val_report['passed'] else 'FAILED'} ({val_report['status']})")
    print(f"  Format         : {manifest['planning_summary']['selected_format']}")
    print(f"  Sections       : {manifest['planning_summary']['section_count']}")
    print(f"  Duration       : {manifest['planning_summary']['target_duration_seconds']}s "
          f"({manifest['planning_summary']['target_duration_minutes']} min)")
    print(f"  Title options  : {manifest['planning_summary']['title_option_count']}")
    print(f"  Visuals        : {manifest['planning_summary']['visual_suggestion_count']}")
    print(f"  Ready Layer 8  : {val_report['ready_for_layer_8']}")
    print(f"  Elapsed        : {elapsed:.1f}s")
    if val_report["warnings"]:
        for w in val_report["warnings"]:
            msg = w["message"] if isinstance(w, dict) else str(w)
            print(f"  ! {msg}")
    if not val_report["passed"]:
        print(f"  Failure: {val_report['failure_reason']}")
    print(f"{'='*58}\n")

    return manifest


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 7 — Content Planning")
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/layer_6/layer6_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            run_id = rp.parents[1].name
            break
        print(f"Auto-discovered run: {run_id}")

    result = run_layer_7(run_id)
    print(f"Script writer brief: {result['handoff']['script_writer_brief_path']}")
    print(f"Video plan         : {result['handoff']['video_plan_path']}")
    print(f"Format             : {result['planning_summary']['selected_format']}")
    print(f"Ready for Layer 8  : {result['handoff']['ready_for_layer_8']}")
