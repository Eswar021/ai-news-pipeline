"""
Layer 5 — Module 11: Layer 5 Output Writer

Writes all Layer 5 output files to data/runs/{run_id}/layer_5/.
Returns the layer5_manifest dict.

Output files:
  editorial_candidates.json
  evidence_safety_decisions.json
  audience_fit_report.json
  viewer_value_report.json
  novelty_report.json
  format_fit_scores.json
  format_routing_decisions.json
  video_opportunity_scores.json
  selected_video_brief.json
  rejected_editorial_candidates.jsonl
  layer5_manifest.json

Key function:
    write(run_id, layer5_dir, layer3_dir, layer4_dir, ...) → manifest dict
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _write_json(path: Path, data: dict | list):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _write_jsonl(path: Path, records: list[dict]):
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def write(
    run_id:                str,
    layer5_dir:            Path,
    layer3_dir:            Path,
    layer4_dir:            Path,
    candidates:            list[dict],
    safety_decisions:      list[dict],
    audience_fits:         list[dict],
    viewer_values:         list[dict],
    novelty_results:       list[dict],
    format_fit_scores:     list[dict],
    routing_decisions:     list[dict],
    opportunity_scores:    list[dict],
    editorial_decision:    dict,
    selected_video_brief:  dict,
) -> dict:
    layer5_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    # ── editorial_candidates.json ─────────────────────────────────────────────
    _write_json(layer5_dir / "editorial_candidates.json", {
        "run_id":               run_id,
        "generated_at":         now,
        "candidate_count":      len(candidates),
        "editorial_candidates": [
            {
                "editorial_candidate_id": c["editorial_candidate_id"],
                "story_id":               c["story_id"],
                "story_title":            c["story_title"],
                "story_type":             c.get("story_type", ""),
                "rank":                   c["rank"],
                "total_story_score":      c["total_story_score"],
                "ranking_bucket":         c["ranking_bucket"],
                "verified_claim_count":   c["verified_claim_count"],
                "evidence_density_score": c["evidence_density_score"],
                "safe_for_roundup":       c["safe_for_roundup"],
                "safe_for_deep_dive":     c["safe_for_deep_dive"],
                "companies":              c.get("companies", []),
                "topics":                 c.get("topics", []),
                "candidate_status":       c["candidate_status"],
            }
            for c in candidates
        ],
    })

    # ── evidence_safety_decisions.json ────────────────────────────────────────
    _write_json(layer5_dir / "evidence_safety_decisions.json", {
        "run_id":        run_id,
        "generated_at":  now,
        "decisions":     safety_decisions,
    })

    # ── audience_fit_report.json ──────────────────────────────────────────────
    _write_json(layer5_dir / "audience_fit_report.json", {
        "run_id":        run_id,
        "generated_at":  now,
        "audience_fit":  audience_fits,
    })

    # ── viewer_value_report.json ──────────────────────────────────────────────
    _write_json(layer5_dir / "viewer_value_report.json", {
        "run_id":        run_id,
        "generated_at":  now,
        "viewer_value":  viewer_values,
    })

    # ── novelty_report.json ───────────────────────────────────────────────────
    _write_json(layer5_dir / "novelty_report.json", {
        "run_id":        run_id,
        "generated_at":  now,
        "novelty":       novelty_results,
    })

    # ── format_fit_scores.json ────────────────────────────────────────────────
    _write_json(layer5_dir / "format_fit_scores.json", {
        "run_id":            run_id,
        "generated_at":      now,
        "format_fit_scores": format_fit_scores,
    })

    # ── format_routing_decisions.json ─────────────────────────────────────────
    _write_json(layer5_dir / "format_routing_decisions.json", {
        "run_id":                   run_id,
        "generated_at":             now,
        "format_routing_decisions": routing_decisions,
    })

    # ── video_opportunity_scores.json ─────────────────────────────────────────
    _write_json(layer5_dir / "video_opportunity_scores.json", {
        "run_id":                  run_id,
        "generated_at":            now,
        "video_opportunity_scores": opportunity_scores,
    })

    # ── selected_video_brief.json ─────────────────────────────────────────────
    brief_with_meta = dict(selected_video_brief)
    brief_with_meta["run_id"]       = run_id
    brief_with_meta["generated_at"] = now
    _write_json(layer5_dir / "selected_video_brief.json", brief_with_meta)

    # ── rejected_editorial_candidates.jsonl ───────────────────────────────────
    _write_jsonl(
        layer5_dir / "rejected_editorial_candidates.jsonl",
        editorial_decision.get("rejected_candidates", [])
    )

    # ── Compute summary counts ────────────────────────────────────────────────
    selected_ids = (
        editorial_decision.get("selected_story_ids") or
        ([editorial_decision.get("primary_story_id")] if editorial_decision.get("primary_story_id") else [])
    )
    selected_count = len(selected_ids)
    rejected_count = len(editorial_decision.get("rejected_candidates", []))

    # ── layer5_manifest.json ──────────────────────────────────────────────────
    manifest = {
        "run_id":        run_id,
        "layer":         "layer_5_editorial_intelligence",
        "created_at":    now,
        "inputs": {
            "layer3_ranked_stories":  str(layer3_dir / "ranked_stories.json"),
            "layer3_entity_map":      str(layer3_dir / "story_entity_topic_map.json"),
            "layer4_fact_sheets":     str(layer4_dir / "story_fact_sheets.json"),
            "layer4_density_report":  str(layer4_dir / "evidence_density_report.json"),
            "layer4_evidence_gaps":   str(layer4_dir / "evidence_gaps.json"),
        },
        "outputs": {
            "editorial_candidates":         str(layer5_dir / "editorial_candidates.json"),
            "evidence_safety_decisions":     str(layer5_dir / "evidence_safety_decisions.json"),
            "audience_fit_report":           str(layer5_dir / "audience_fit_report.json"),
            "viewer_value_report":           str(layer5_dir / "viewer_value_report.json"),
            "novelty_report":                str(layer5_dir / "novelty_report.json"),
            "format_fit_scores":             str(layer5_dir / "format_fit_scores.json"),
            "format_routing_decisions":      str(layer5_dir / "format_routing_decisions.json"),
            "video_opportunity_scores":      str(layer5_dir / "video_opportunity_scores.json"),
            "selected_video_brief":          str(layer5_dir / "selected_video_brief.json"),
            "rejected_editorial_candidates": str(layer5_dir / "rejected_editorial_candidates.jsonl"),
            "layer5_manifest":               str(layer5_dir / "layer5_manifest.json"),
        },
        "counts": {
            "candidate_story_count":   len(candidates),
            "evaluated_count":         len(candidates),
            "selected_video_count":    1 if editorial_decision.get("decision") == "create_video" else 0,
            "selected_story_count":    selected_count,
            "rejected_candidate_count": rejected_count,
        },
        "decision": {
            "create_video":            editorial_decision.get("decision") == "create_video",
            "selected_format":         editorial_decision.get("selected_format"),
            "selected_story_ids":      selected_ids,
            "decision_confidence":     editorial_decision.get("decision_confidence", 0),
            "episode_theme":           editorial_decision.get("episode_theme"),
        },
        "handoff": {
            "ready_for_layer_6": selected_video_brief.get("handoff", {}).get("ready_for_layer_6", False),
            "next_layer":        "layer_6_format_specific_research_packets",
            "selected_video_brief_path": str(layer5_dir / "selected_video_brief.json"),
        },
    }

    _write_json(layer5_dir / "layer5_manifest.json", manifest)
    return manifest
