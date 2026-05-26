"""
L3 Story Map — cluster prepared records into ranked story objects.

Reads:
    output/{run_id}/run_manifest.json
    output/{run_id}/L2/prepared_records.json

Writes:
    output/{run_id}/L3/stories.json
    output/{run_id}/L3/summary.json
    output/{run_id}/L3/llm_calls.jsonl        → when LLM story labels are enabled

LLM: yes when layer_3.use_llm_story_labels is true
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.llm.client import OpenAIJSONClient
from src.llm.prompt_loader import load_prompt_bundle
from src.pipeline.L3_story_map.clusterer import cluster_records
from src.pipeline.L3_story_map.ranker import rank_stories
from src.pipeline.L3_story_map.story_label import attach_story_labels


IST = timezone(timedelta(hours=5, minutes=30))


def run(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    layer3_cfg = manifest.get("layer_3")
    if not isinstance(layer3_cfg, dict):
        raise KeyError("run_manifest.json is missing layer_3 config. Re-run layer 0.")
    _validate_layer3_config(layer3_cfg)

    run_id = manifest["run_id"]
    print(f"[L3] Run: {run_id}")
    prepared = _load_l2_records(run_id)
    print(f"[L3] Input records: {prepared['record_count']}")

    out_dir = OUTPUT_DIR / run_id / "L3"
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_calls_path = out_dir / "llm_calls.jsonl"

    records = prepared["records"]
    clusters, cluster_stats = cluster_records(records, layer3_cfg)

    llm_story_label_count = 0
    if layer3_cfg.get("use_llm_story_labels", False):
        if llm_calls_path.exists():
            llm_calls_path.unlink()
        prompt_bundle = load_prompt_bundle("story_label", layer3_cfg["story_label_prompt_version"])
        llm_client = OpenAIJSONClient(model=layer3_cfg["story_label_model"])
        clusters = attach_story_labels(
            clusters,
            layer3_cfg=layer3_cfg,
            llm_client=llm_client,
            system_prompt=prompt_bundle["system"],
            log_path=llm_calls_path,
        )
        llm_story_label_count = len(clusters)
        print(f"[L3] Story labels: {llm_story_label_count}")

    ranked_stories = rank_stories(clusters)

    payload = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "story_count": len(ranked_stories),
        "stories": ranked_stories,
    }
    summary = _build_summary(
        run_id,
        prepared["record_count"],
        ranked_stories,
        cluster_stats,
        llm_story_label_count=llm_story_label_count,
        story_label_worker_count=(
            int(layer3_cfg["story_label_worker_count"])
            if layer3_cfg.get("use_llm_story_labels", False)
            else 0
        ),
    )

    data_path = out_dir / "stories.json"
    summary_path = out_dir / "summary.json"
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"[L3] Stories: {len(ranked_stories)}  "
        f"Single-record: {sum(1 for story in ranked_stories if story['record_count'] == 1)}  "
        f"Multi-record: {sum(1 for story in ranked_stories if story['record_count'] > 1)}"
    )
    print(f"[L3] Wrote: {data_path}")
    return data_path


def _build_summary(
    run_id: str,
    input_count: int,
    stories: list[dict],
    cluster_stats: dict[str, int],
    *,
    llm_story_label_count: int,
    story_label_worker_count: int,
) -> dict:
    bucket_counts: dict[str, int] = {}
    source_group_mix: dict[str, int] = {}
    for story in stories:
        bucket = story["priority_bucket"]
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        for group in story["source_groups"]:
            source_group_mix[group] = source_group_mix.get(group, 0) + 1

    return {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "status": "ok",
        "input_record_count": input_count,
        "story_count": len(stories),
        "llm_story_label_count": llm_story_label_count,
        "story_label_worker_count": story_label_worker_count,
        "single_record_story_count": sum(1 for story in stories if story["record_count"] == 1),
        "multi_record_story_count": sum(1 for story in stories if story["record_count"] > 1),
        "exact_match_merge_count": cluster_stats["exact_match_edges"],
        "semantic_merge_count": cluster_stats["semantic_edges"],
        "dropped_singleton_count": cluster_stats["dropped_singletons"],
        "priority_bucket_counts": bucket_counts,
        "source_group_mix": source_group_mix,
        "top_story_quality_flags": _top_story_quality_flags(stories[:12]),
        "top_stories": [
            {
                "rank": story["rank"],
                "title": story["story_title"],
                "score": story["rank_score"],
                "record_count": story["record_count"],
                "quality_flags": _story_quality_flags(story),
            }
            for story in stories[:10]
        ],
    }


def _validate_layer3_config(layer3_cfg: dict) -> None:
    required = [
        "embedding_model",
        "use_llm_story_labels",
    ]
    if layer3_cfg.get("use_llm_story_labels"):
        required.extend(
            [
                "story_label_model",
                "story_label_prompt_version",
                "story_label_worker_count",
            ]
        )
    missing = [key for key in required if key not in layer3_cfg]
    if missing:
        raise KeyError(
            "run_manifest.json has stale or incomplete layer_3 config. "
            f"Missing: {', '.join(missing)}. Re-run layer 0."
        )


def _top_story_quality_flags(stories: list[dict]) -> dict:
    flags = {
        "low_editorial_value_count": 0,
        "tutorial_count": 0,
        "weak_content_count": 0,
        "event_update_count": 0,
    }
    for story in stories:
        story_flags = _story_quality_flags(story)
        for key in flags:
            if story_flags.get(key.removesuffix("_count"), False):
                flags[key] += 1
    return flags


def _story_quality_flags(story: dict) -> dict:
    identity = story.get("story_identity") or {}
    return {
        "low_editorial_value": identity.get("editorial_value") == "low",
        "tutorial": bool(identity.get("is_tutorial") or story.get("story_type_hint") == "tutorial_or_demo"),
        "weak_content": any(_record_has_weak_content(record) for record in story.get("records", [])),
        "event_update": bool(identity.get("is_event_update") or story.get("story_type_hint") == "event_update"),
    }


def _record_has_weak_content(record: dict) -> bool:
    content = str(record.get("content", ""))
    if record.get("content_status") != "full":
        return True
    if record.get("content_integrity_status") in {"wrong_article", "title_mismatch", "too_short"}:
        return True
    return record.get("source_group") in {"ai_company_blogs", "tech_news_apis"} and len(content) < 700


def _load_l2_records(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L2" / "prepared_records.json"
    if not path.exists():
        raise FileNotFoundError(
            f"L2 prepared_records.json not found for {run_id}. Run layers 1 and 2 first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_manifest(run_ref: str) -> dict:
    if run_ref == "current":
        path = CURRENT_MANIFEST_PATH
    else:
        path = OUTPUT_DIR / run_ref / "run_manifest.json"
    if not path.exists():
        raise FileNotFoundError(
            f"run_manifest.json not found for {run_ref}. Run L0 first."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if run_ref == "current":
        run_id = manifest.get("run_id")
        if not run_id:
            raise KeyError("output/current_manifest.json is missing run_id")
        run_manifest_path = OUTPUT_DIR / run_id / "run_manifest.json"
        if not run_manifest_path.exists():
            raise FileNotFoundError(f"Run manifest not found: {run_manifest_path}")
        manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    return manifest


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    path = run(args.run_id)
    print(path)
