"""
Layer 6 — Module 9: Layer 6 Output Writer

Writes all 7 Layer 6 output files and returns the layer6_manifest dict.

Output files:
  research_packet.json
  source_pack.json
  claim_section_map.json
  evidence_boundary_report.json
  packet_quality_report.json
  packet_context_for_layer7.json
  layer6_manifest.json

Key function:
    write(run_id, layer6_dir, layer5_dir, layer4_dir, layer3_dir, layer2_dir,
          packet, source_pack, claim_section_map, boundary_report,
          quality_report, packet_context, brief_ctx) → manifest dict
"""

import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path


def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def write(
    run_id:            str,
    layer6_dir:        Path,
    layer5_dir:        Path,
    layer4_dir:        Path,
    layer3_dir:        Path,
    layer2_dir:        Path,
    packet:            dict,
    source_pack:       dict,
    claim_section_map: list,
    boundary_report:   dict,
    quality_report:    dict,
    packet_context:    dict,
    brief_ctx:         dict,
) -> dict:
    layer6_dir.mkdir(parents=True, exist_ok=True)
    now = now_project_iso()

    # ── research_packet.json ─────────────────────────────────────────────────
    research_packet = {
        "research_packet_id":  f"packet_{now[:10].replace('-','')}_{run_id[-6:]}",
        "run_id":              run_id,
        "generated_at":        now,
        "packet_type":         packet.get("packet_type"),
        "selected_format":     packet.get("selected_format"),
        "selected_video_id":   brief_ctx.get("selected_video_id"),
        "selected_story_ids":  brief_ctx.get("selected_story_ids", []),
        "primary_story_id":    brief_ctx.get("primary_story_id"),
        "packet_identity": {
            "packet_type":         packet.get("packet_type"),
            "selected_format":     packet.get("selected_format"),
            "selected_story_ids":  brief_ctx.get("selected_story_ids", []),
            "primary_story_id":    brief_ctx.get("primary_story_id"),
        },
        "editorial_direction": brief_ctx.get("content_direction", {}),
        "evidence_boundaries": {
            "safe_claim_ids":       list(brief_ctx.get("safe_claim_ids", set())),
            "cautious_claim_ids":   list(brief_ctx.get("cautious_claim_ids", set())),
            "do_not_use_claim_ids": list(brief_ctx.get("do_not_use_claim_ids", set())),
        },
        "packet_content": packet,
        "source_support": {
            "source_pack_path":      str(layer6_dir / "source_pack.json"),
            "claim_section_map_path": str(layer6_dir / "claim_section_map.json"),
        },
        "handoff": {
            "next_layer":        "layer_7_content_planning",
            "ready_for_layer_7": quality_report.get("ready_for_layer_7", False),
        },
    }
    _write_json(layer6_dir / "research_packet.json", research_packet)

    # ── source_pack.json ─────────────────────────────────────────────────────
    _write_json(layer6_dir / "source_pack.json", source_pack)

    # ── claim_section_map.json ───────────────────────────────────────────────
    _write_json(layer6_dir / "claim_section_map.json", {
        "run_id":            run_id,
        "generated_at":      now,
        "packet_id":         research_packet["research_packet_id"],
        "packet_type":       packet.get("packet_type"),
        "claim_section_map": claim_section_map,
    })

    # ── evidence_boundary_report.json ────────────────────────────────────────
    boundary_with_meta = dict(boundary_report)
    boundary_with_meta["run_id"]       = run_id
    boundary_with_meta["generated_at"] = now
    boundary_with_meta["packet_id"]    = research_packet["research_packet_id"]
    _write_json(layer6_dir / "evidence_boundary_report.json", boundary_with_meta)

    # ── packet_quality_report.json ───────────────────────────────────────────
    quality_with_meta = dict(quality_report)
    quality_with_meta["run_id"]       = run_id
    quality_with_meta["generated_at"] = now
    quality_with_meta["packet_id"]    = research_packet["research_packet_id"]
    _write_json(layer6_dir / "packet_quality_report.json", quality_with_meta)

    # ── packet_context_for_layer7.json ───────────────────────────────────────
    context_with_meta = dict(packet_context)
    context_with_meta["run_id"]       = run_id
    context_with_meta["generated_at"] = now
    _write_json(layer6_dir / "packet_context_for_layer7.json", context_with_meta)

    # ── layer6_manifest.json ─────────────────────────────────────────────────
    selected_ids = brief_ctx.get("selected_story_ids", [])
    manifest = {
        "run_id":      run_id,
        "layer":       "layer_6_format_specific_research_packets",
        "created_at":  now,
        "inputs": {
            "selected_video_brief": str(layer5_dir / "selected_video_brief.json"),
            "layer5_manifest":      str(layer5_dir / "layer5_manifest.json"),
            "story_fact_sheets":    str(layer4_dir / "story_fact_sheets.json"),
            "verified_claims":      str(layer4_dir / "verified_claims.jsonl"),
            "claim_evidence_map":   str(layer4_dir / "claim_evidence_map.jsonl"),
            "story_timeline":       str(layer3_dir / "story_timeline.json"),
            "source_spans":         str(layer2_dir / "source_spans.jsonl"),
            "canonical_documents":  str(layer2_dir / "canonical_documents.jsonl"),
        },
        "outputs": {
            "research_packet":          str(layer6_dir / "research_packet.json"),
            "source_pack":              str(layer6_dir / "source_pack.json"),
            "claim_section_map":        str(layer6_dir / "claim_section_map.json"),
            "evidence_boundary_report": str(layer6_dir / "evidence_boundary_report.json"),
            "packet_quality_report":    str(layer6_dir / "packet_quality_report.json"),
            "packet_context_for_layer7": str(layer6_dir / "packet_context_for_layer7.json"),
            "layer6_manifest":          str(layer6_dir / "layer6_manifest.json"),
        },
        "packet": {
            "selected_format":       packet.get("selected_format"),
            "packet_type":           packet.get("packet_type"),
            "selected_story_ids":    selected_ids,
            "primary_story_id":      brief_ctx.get("primary_story_id"),
            "packet_quality_score":  quality_report.get("packet_quality_score"),
            "research_packet_id":    research_packet["research_packet_id"],
        },
        "counts": {
            "selected_story_count": len(selected_ids),
            "safe_claim_count":     len(brief_ctx.get("safe_claim_ids", set())),
            "cautious_claim_count": len(brief_ctx.get("cautious_claim_ids", set())),
            "dnu_claim_count":      len(brief_ctx.get("do_not_use_claim_ids", set())),
            "source_count":         source_pack.get("source_count", 0),
        },
        "handoff": {
            "ready_for_layer_7":           quality_report.get("ready_for_layer_7", False),
            "next_layer":                  "layer_7_content_planning",
            "packet_context_path":         str(layer6_dir / "packet_context_for_layer7.json"),
            "research_packet_path":        str(layer6_dir / "research_packet.json"),
        },
    }
    _write_json(layer6_dir / "layer6_manifest.json", manifest)
    return manifest
