"""
L1 Collection — collect raw source records into one flat data file.

Reads:
    output/{run_id}/run_manifest.json         → layer_1 collector config

Writes:
    output/{run_id}/L1/raw_records.json       → kept downstream records only
    output/{run_id}/L1/summary.json           → fetched, kept, filtered counts per group

LLM: no

Module execution order:
    1. load manifest
    2. run each enabled source-group collector
    3. assign record ids
    4. write data file and summary

Usage:
    python -m src.pipeline.L1_collection.runner --run-id run_...
"""

import argparse
import json
import time
from pathlib import Path

from src.config.settings import iso_now, load_manifest, output_dir
from src.pipeline.L1_collection.collectors import (
    company_blogs,
    community_signals,
    research_papers,
    tech_news,
    youtube_transcripts,
)


def run(run_id: str) -> Path:
    manifest = load_manifest(run_id)
    l1_cfg = manifest.get("layer_1")
    if not isinstance(l1_cfg, dict):
        raise KeyError(f"run_manifest.json for {run_id} has no valid 'layer_1' key")

    out_dir = output_dir(run_id) / "L1"
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    records: list[dict] = []
    group_summaries: dict[str, dict] = {}
    enabled_groups = list(l1_cfg["enabled_source_groups"])

    for group_name in enabled_groups:
        cfg = l1_cfg["collectors"][group_name]
        result = _collect_group(group_name, cfg)
        for record in result["records"]:
            record["id"] = f"L1_{len(records) + 1:05d}"
            record["run_id"] = run_id
            records.append(record)
        group_summaries[group_name] = result["summary"]

    raw_payload = {
        "run_id": run_id,
        "generated_at": iso_now(),
        "record_count": len(records),
        "records": records,
    }
    summary = _build_summary(run_id, enabled_groups, group_summaries, len(records), time.time() - started)

    data_path = out_dir / "raw_records.json"
    summary_path = out_dir / "summary.json"
    data_path.write_text(json.dumps(raw_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return data_path


def _collect_group(group_name: str, cfg: dict) -> dict:
    if group_name == "ai_company_blogs":
        return company_blogs.collect(cfg)
    if group_name == "tech_news_apis":
        return tech_news.collect(cfg)
    if group_name == "research_papers":
        return research_papers.collect(cfg)
    if group_name == "youtube_podcast_transcripts":
        return youtube_transcripts.collect(cfg)
    if group_name == "community_signals":
        return community_signals.collect(cfg)
    raise ValueError(f"Unsupported source group: {group_name}")


def _build_summary(
    run_id: str,
    enabled_groups: list[str],
    group_summaries: dict[str, dict],
    total_records: int,
    elapsed_seconds: float,
) -> dict:
    groups_with_records = [
        group_name
        for group_name, summary in group_summaries.items()
        if summary.get("kept_count", 0) > 0
    ]
    return {
        "run_id": run_id,
        "generated_at": iso_now(),
        "status": "partial" if any(summary.get("status") != "ok" for summary in group_summaries.values()) else "ok",
        "enabled_source_groups": enabled_groups,
        "enabled_source_group_count": len(enabled_groups),
        "successful_source_groups": groups_with_records,
        "successful_source_group_count": len(groups_with_records),
        "total_records": total_records,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "groups": group_summaries,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    path = run(args.run_id)
    print(path)
