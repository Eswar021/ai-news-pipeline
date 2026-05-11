"""
Layer 7 — Module 14: Layer 7 Output Writer

Writes all 13 Layer 7 output files and returns the layer7_manifest dict.

Output files:
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

Key function:
    write(run_id, layer7_dir, layer6_dir, layer7_ctx, viewer_strategy,
          hook_plan, narrative_plan, section_plan, claim_placement_plan,
          transition_plan, pacing_plan, visual_plan, title_thumbnail_plan,
          cta_plan, boundary_review, script_writer_brief) → manifest dict
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def write(
    run_id:               str,
    layer7_dir:           Path,
    layer6_dir:           Path,
    layer7_ctx:           dict,
    viewer_strategy:      dict,
    hook_plan:            dict,
    narrative_plan:       dict,
    section_plan:         list,
    claim_placement_plan: list,
    transition_plan:      list,
    pacing_plan:          dict,
    visual_plan:          list,
    title_thumbnail_plan: dict,
    cta_plan:             dict,
    boundary_review:      dict,
    script_writer_brief:  dict,
) -> dict:
    layer7_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    packet_type     = layer7_ctx["packet_type"]
    total_dur       = pacing_plan["target_duration_seconds"]
    section_count   = len(section_plan)
    title_count     = len(title_thumbnail_plan.get("recommended_title_angles", []))
    visual_count    = len(visual_plan)

    # ── video_plan.json ──────────────────────────────────────────────────────
    video_plan = {
        "video_plan_id":    f"video_plan_{now[:10].replace('-','')}_{run_id[-6:]}",
        "run_id":           run_id,
        "generated_at":     now,
        "selected_format":  packet_type,
        "selected_video_id": layer7_ctx.get("selected_video_id", ""),
        "target_duration_seconds": total_dur,
        "target_duration_minutes": round(total_dur / 60, 1),
        "viewer_strategy":  viewer_strategy,
        "hook_strategy": {
            "selected_hook_direction": hook_plan.get("recommended_hook", {}).get("hook_direction", ""),
            "hook_type":               hook_plan.get("recommended_hook", {}).get("hook_type", ""),
            "hook_claim_ids":          hook_plan.get("recommended_hook", {}).get("supported_by_claim_ids", []),
            "hook_risk_level":         hook_plan.get("recommended_hook", {}).get("risk_level", "low"),
        },
        "narrative_strategy": {
            "narrative_arc": narrative_plan.get("narrative_arc", ""),
            "core_tension":  narrative_plan.get("core_tension", ""),
        },
        "sections":           section_plan,
        "evidence_boundaries": {
            "safe_claim_ids":      sorted(layer7_ctx.get("safe_claim_ids", set())),
            "cautious_claim_ids":  sorted(layer7_ctx.get("cautious_claim_ids", set())),
            "do_not_use_claim_ids": sorted(layer7_ctx.get("do_not_use_claim_ids", set())),
        },
        "handoff": {
            "ready_for_layer_8": boundary_review.get("passed", False),
            "next_layer":        "layer_8_script_generation",
        },
    }
    _write_json(layer7_dir / "video_plan.json", video_plan)

    # ── hook_plan.json ───────────────────────────────────────────────────────
    hook_out = dict(hook_plan)
    hook_out["run_id"]       = run_id
    hook_out["generated_at"] = now
    _write_json(layer7_dir / "hook_plan.json", hook_out)

    # ── narrative_plan.json ──────────────────────────────────────────────────
    narr_out = dict(narrative_plan)
    narr_out["run_id"]       = run_id
    narr_out["generated_at"] = now
    _write_json(layer7_dir / "narrative_plan.json", narr_out)

    # ── section_plan.json ────────────────────────────────────────────────────
    _write_json(layer7_dir / "section_plan.json", {
        "run_id":       run_id,
        "generated_at": now,
        "section_count": section_count,
        "sections":     section_plan,
    })

    # ── claim_placement_plan.json ────────────────────────────────────────────
    _write_json(layer7_dir / "claim_placement_plan.json", {
        "run_id":              run_id,
        "generated_at":        now,
        "total_placements":    len(claim_placement_plan),
        "claim_placement_plan": claim_placement_plan,
    })

    # ── transition_plan.json ─────────────────────────────────────────────────
    _write_json(layer7_dir / "transition_plan.json", {
        "run_id":          run_id,
        "generated_at":    now,
        "transition_count": len(transition_plan),
        "transition_plan": transition_plan,
    })

    # ── pacing_retention_plan.json ───────────────────────────────────────────
    pacing_out = dict(pacing_plan)
    pacing_out["run_id"]       = run_id
    pacing_out["generated_at"] = now
    _write_json(layer7_dir / "pacing_retention_plan.json", pacing_out)

    # ── visual_plan.json ─────────────────────────────────────────────────────
    _write_json(layer7_dir / "visual_plan.json", {
        "run_id":       run_id,
        "generated_at": now,
        "visual_count": visual_count,
        "visual_plan":  visual_plan,
    })

    # ── title_thumbnail_plan.json ────────────────────────────────────────────
    tt_out = dict(title_thumbnail_plan)
    tt_out["run_id"]       = run_id
    tt_out["generated_at"] = now
    _write_json(layer7_dir / "title_thumbnail_plan.json", tt_out)

    # ── cta_plan.json ────────────────────────────────────────────────────────
    cta_out = dict(cta_plan)
    cta_out["run_id"]       = run_id
    cta_out["generated_at"] = now
    _write_json(layer7_dir / "cta_plan.json", cta_out)

    # ── evidence_boundary_review.json ────────────────────────────────────────
    br_out = dict(boundary_review)
    br_out["run_id"]       = run_id
    br_out["generated_at"] = now
    _write_json(layer7_dir / "evidence_boundary_review.json", br_out)

    # ── script_writer_brief.json ─────────────────────────────────────────────
    _write_json(layer7_dir / "script_writer_brief.json", script_writer_brief)

    # ── layer7_manifest.json ─────────────────────────────────────────────────
    manifest = {
        "run_id":      run_id,
        "layer":       "layer_7_content_planning",
        "created_at":  now,
        "inputs": {
            "research_packet":         str(layer6_dir / "research_packet.json"),
            "packet_context_for_layer7": str(layer6_dir / "packet_context_for_layer7.json"),
            "source_pack":             str(layer6_dir / "source_pack.json"),
            "claim_section_map":       str(layer6_dir / "claim_section_map.json"),
            "evidence_boundary_report": str(layer6_dir / "evidence_boundary_report.json"),
            "packet_quality_report":   str(layer6_dir / "packet_quality_report.json"),
            "layer6_manifest":         str(layer6_dir / "layer6_manifest.json"),
        },
        "outputs": {
            "video_plan":              str(layer7_dir / "video_plan.json"),
            "hook_plan":               str(layer7_dir / "hook_plan.json"),
            "narrative_plan":          str(layer7_dir / "narrative_plan.json"),
            "section_plan":            str(layer7_dir / "section_plan.json"),
            "claim_placement_plan":    str(layer7_dir / "claim_placement_plan.json"),
            "transition_plan":         str(layer7_dir / "transition_plan.json"),
            "pacing_retention_plan":   str(layer7_dir / "pacing_retention_plan.json"),
            "visual_plan":             str(layer7_dir / "visual_plan.json"),
            "title_thumbnail_plan":    str(layer7_dir / "title_thumbnail_plan.json"),
            "cta_plan":                str(layer7_dir / "cta_plan.json"),
            "evidence_boundary_review": str(layer7_dir / "evidence_boundary_review.json"),
            "script_writer_brief":     str(layer7_dir / "script_writer_brief.json"),
            "layer7_manifest":         str(layer7_dir / "layer7_manifest.json"),
        },
        "planning_summary": {
            "selected_format":         packet_type,
            "section_count":           section_count,
            "target_duration_seconds": total_dur,
            "target_duration_minutes": round(total_dur / 60, 1),
            "title_option_count":      title_count,
            "visual_suggestion_count": visual_count,
            "boundary_review_status":  boundary_review.get("status", "unknown"),
        },
        "handoff": {
            "ready_for_layer_8": boundary_review.get("passed", False),
            "next_layer":        "layer_8_script_generation",
            "script_writer_brief_path": str(layer7_dir / "script_writer_brief.json"),
            "video_plan_path":         str(layer7_dir / "video_plan.json"),
        },
    }
    _write_json(layer7_dir / "layer7_manifest.json", manifest)
    return manifest
