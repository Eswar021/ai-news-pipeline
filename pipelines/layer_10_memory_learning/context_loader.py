"""
Layer 10 — Module 1: Context Loader

Loads all input files from Layers 3–9 needed for memory updates.

Returns a flat ctx dict:
  run_id, base_dir
  final_publish_package, verification_report, verified_youtube_metadata
  source_attribution_report
  claim_usage_report, youtube_metadata
  video_plan, title_thumbnail_plan, script_writer_brief
  selected_video_brief
  verified_claims (list), rejected_claims (list)
  evidence_gaps (list), contradictions (list)
  story_entity_topic_map (list)
"""

import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def load(
    layer9_dir: Path,
    layer8_dir: Path,
    layer7_dir: Path,
    layer5_dir: Path,
    layer4_dir: Path,
    layer3_dir: Path,
) -> dict:
    run_id = _load_json(layer9_dir / "layer9_manifest.json")["run_id"]

    # Layer 9
    final_publish_package      = _load_json(layer9_dir / "final_publish_package.json")
    verification_report        = _load_json(layer9_dir / "verification_report.json")
    verified_youtube_metadata  = _load_json(layer9_dir / "verified_youtube_metadata.json")
    source_attribution_report  = _load_json(layer9_dir / "source_attribution_report.json")

    # Layer 8
    claim_usage_report  = _load_json(layer8_dir / "claim_usage_report.json")
    youtube_metadata    = _load_json(layer8_dir / "youtube_metadata.json")

    # Layer 7
    video_plan           = _load_json(layer7_dir / "video_plan.json")
    title_thumbnail_plan = _load_json(layer7_dir / "title_thumbnail_plan.json")
    script_writer_brief  = _load_json(layer7_dir / "script_writer_brief.json")

    # Layer 5
    selected_video_brief = _load_json(layer5_dir / "selected_video_brief.json")

    # Layer 4
    verified_claims  = _load_jsonl(layer4_dir / "verified_claims.jsonl")
    rejected_claims  = _load_jsonl(layer4_dir / "rejected_claims.jsonl")
    evidence_gaps    = _load_json(layer4_dir / "evidence_gaps.json").get("evidence_gaps", [])
    contradictions   = _load_json(layer4_dir / "contradictions.json").get("contradictions", [])

    # Layer 3
    story_entity_topic_map = _load_json(layer3_dir / "story_entity_topic_map.json").get(
        "story_entity_topic_map", []
    )

    # Build claim lookup map for quick access by claim_id
    claim_map = {c["claim_id"]: c for c in verified_claims}

    return {
        "run_id":                    run_id,
        "layer9_dir":                layer9_dir,
        "layer8_dir":                layer8_dir,
        "layer7_dir":                layer7_dir,
        "layer5_dir":                layer5_dir,
        "layer4_dir":                layer4_dir,
        "layer3_dir":                layer3_dir,
        "final_publish_package":     final_publish_package,
        "verification_report":       verification_report,
        "verified_youtube_metadata": verified_youtube_metadata,
        "source_attribution_report": source_attribution_report,
        "claim_usage_report":        claim_usage_report,
        "youtube_metadata":          youtube_metadata,
        "video_plan":                video_plan,
        "title_thumbnail_plan":      title_thumbnail_plan,
        "script_writer_brief":       script_writer_brief,
        "selected_video_brief":      selected_video_brief,
        "verified_claims":           verified_claims,
        "rejected_claims":           rejected_claims,
        "evidence_gaps":             evidence_gaps,
        "contradictions":            contradictions,
        "story_entity_topic_map":    story_entity_topic_map,
        "claim_map":                 claim_map,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(
        base / "layer_9", base / "layer_8", base / "layer_7",
        base / "layer_5", base / "layer_4", base / "layer_3",
    )
    print(f"run_id               : {ctx['run_id']}")
    print(f"verified_claims      : {len(ctx['verified_claims'])}")
    print(f"rejected_claims      : {len(ctx['rejected_claims'])}")
    print(f"evidence_gaps        : {len(ctx['evidence_gaps'])}")
    print(f"contradictions       : {len(ctx['contradictions'])}")
    print(f"story_entity_map     : {len(ctx['story_entity_topic_map'])}")
    print(f"used_claim_ids       : {len(ctx['claim_usage_report']['used_claim_ids'])}")
    print(f"L9 approval          : {ctx['final_publish_package']['approval']['status']}")
    print(f"ready_for_layer_10   : {ctx['final_publish_package']['memory_handoff']['ready_for_layer_10']}")
