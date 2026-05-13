"""
Layer 5 — Module 11: Layer 5 Output Writer

Writes the lean Layer 5 output set to data/runs/{run_id}/layer_5/.
Returns the layer5_manifest dict.

Output files:
  editorial_candidates.json
  story_editorial_assessments.json
  editorial_decision.json
  selected_video_brief.json
  rejected_editorial_candidates.jsonl
  layer5_manifest.json
"""

import json
from pathlib import Path

from config.time_utils import now_project_iso


def _write_json(path: Path, data: dict | list):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _write_jsonl(path: Path, records: list[dict]):
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _selected_story_ids(editorial_decision: dict) -> list[str]:
    story_ids = list(editorial_decision.get("selected_story_ids") or [])
    primary_story_id = editorial_decision.get("primary_story_id")
    if not story_ids and primary_story_id:
        story_ids = [primary_story_id]
    return story_ids


def write(
    run_id: str,
    layer5_dir: Path,
    layer3_dir: Path,
    layer4_dir: Path,
    candidates: list[dict],
    story_assessments: list[dict],
    editorial_decision: dict,
    selected_video_brief: dict,
) -> dict:
    layer5_dir.mkdir(parents=True, exist_ok=True)
    now = now_project_iso()

    # ── editorial_candidates.json ──────────────────────────────────────────
    _write_json(
        layer5_dir / "editorial_candidates.json",
        {
            "run_id": run_id,
            "generated_at": now,
            "candidate_count": len(candidates),
            "editorial_candidates": [
                {
                    "editorial_candidate_id": c["editorial_candidate_id"],
                    "story_id": c["story_id"],
                    "story_title": c["story_title"],
                    "story_type": c.get("story_type", ""),
                    "rank": c["rank"],
                    "total_story_score": c["total_story_score"],
                    "ranking_bucket": c["ranking_bucket"],
                    "verified_claim_count": c["verified_claim_count"],
                    "evidence_density_score": c["evidence_density_score"],
                    "primary_source_count": c.get("primary_source_count", 0),
                    "independent_source_count": c.get("independent_source_count", 0),
                    "safe_for_roundup": c["safe_for_roundup"],
                    "safe_for_deep_dive": c["safe_for_deep_dive"],
                    "companies": c.get("companies", []),
                    "topics": c.get("topics", []),
                    "candidate_status": c["candidate_status"],
                }
                for c in candidates
            ],
        },
    )

    # ── story_editorial_assessments.json ───────────────────────────────────
    _write_json(
        layer5_dir / "story_editorial_assessments.json",
        {
            "run_id": run_id,
            "generated_at": now,
            "assessment_count": len(story_assessments),
            "story_editorial_assessments": story_assessments,
        },
    )

    # ── editorial_decision.json ────────────────────────────────────────────
    decision_with_meta = dict(editorial_decision)
    decision_with_meta["run_id"] = run_id
    decision_with_meta["generated_at"] = now
    _write_json(layer5_dir / "editorial_decision.json", decision_with_meta)

    # ── selected_video_brief.json ──────────────────────────────────────────
    brief_with_meta = dict(selected_video_brief)
    brief_with_meta["run_id"] = run_id
    brief_with_meta["generated_at"] = now
    _write_json(layer5_dir / "selected_video_brief.json", brief_with_meta)

    # ── rejected_editorial_candidates.jsonl ────────────────────────────────
    rejected_candidates = editorial_decision.get("rejected_candidates", [])
    _write_jsonl(layer5_dir / "rejected_editorial_candidates.jsonl", rejected_candidates)

    selected_ids = _selected_story_ids(editorial_decision)

    # ── layer5_manifest.json ───────────────────────────────────────────────
    manifest = {
        "run_id": run_id,
        "layer": "layer_5_editorial_intelligence",
        "created_at": now,
        "inputs": {
            "layer3_ranked_stories": str(layer3_dir / "ranked_stories.json"),
            "layer3_entity_map": str(layer3_dir / "story_entity_topic_map.json"),
            "layer4_fact_sheets": str(layer4_dir / "story_fact_sheets.json"),
            "layer4_density_report": str(layer4_dir / "evidence_density_report.json"),
            "layer4_evidence_gaps": str(layer4_dir / "evidence_gaps.json"),
        },
        "outputs": {
            "editorial_candidates": str(layer5_dir / "editorial_candidates.json"),
            "story_editorial_assessments": str(layer5_dir / "story_editorial_assessments.json"),
            "editorial_decision": str(layer5_dir / "editorial_decision.json"),
            "selected_video_brief": str(layer5_dir / "selected_video_brief.json"),
            "rejected_editorial_candidates": str(layer5_dir / "rejected_editorial_candidates.jsonl"),
            "layer5_manifest": str(layer5_dir / "layer5_manifest.json"),
        },
        "counts": {
            "candidate_story_count": len(candidates),
            "evaluated_count": len(story_assessments),
            "selected_video_count": 1 if editorial_decision.get("decision") == "create_video" else 0,
            "selected_story_count": len(selected_ids),
            "rejected_candidate_count": len(rejected_candidates),
        },
        "decision": {
            "create_video": editorial_decision.get("decision") == "create_video",
            "requested_format": editorial_decision.get("requested_format"),
            "selected_format": editorial_decision.get("selected_format"),
            "selected_story_ids": selected_ids,
            "decision_confidence": editorial_decision.get("decision_confidence", 0),
            "decision_reasons": editorial_decision.get("decision_reasons", []),
            "episode_theme": editorial_decision.get("episode_theme"),
        },
        "handoff": {
            "ready_for_layer_6": selected_video_brief.get("handoff", {}).get("ready_for_layer_6", False),
            "next_layer": "layer_6_format_specific_research_packets",
            "selected_video_brief_path": str(layer5_dir / "selected_video_brief.json"),
        },
    }

    _write_json(layer5_dir / "layer5_manifest.json", manifest)
    return manifest
