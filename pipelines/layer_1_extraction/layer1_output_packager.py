"""
Module: layer1_output_packager
Layer: 1 — Source Extraction
Purpose: Read raw_documents.jsonl and produce extraction_manifest.json — the handoff
         contract from Layer 1 to Layer 2. Summarises what was collected, broken
         down by source group, and records any failed sources.

Run standalone:
    python layer1_output_packager.py
"""

import sys
import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_1_extraction.raw_document_writer import read_raw_documents
from pipelines.layer_1_extraction.extraction_audit_logger import read_events


def build_extraction_manifest(
    run_id: str,
    layer1_dir: Path = None,
    manifest_path: Path = None,
) -> dict:
    """
    Read raw_documents.jsonl and failed_sources.jsonl, produce extraction_manifest.json.

    Returns the manifest dict.
    """
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    raw_docs_path    = layer1_dir / "raw_documents.jsonl"
    failed_path      = layer1_dir / "failed_sources.jsonl"
    if manifest_path is None:
        manifest_path = layer1_dir / "extraction_manifest.json"

    # ── Read raw documents ─────────────────────────────────────────────────────
    docs = read_raw_documents(raw_docs_path)

    run_manifest_path = RUNS_DIR / run_id / "run_manifest.json"
    run_manifest = {}
    if run_manifest_path.exists():
        with open(run_manifest_path, encoding="utf-8") as f:
            run_manifest = json.load(f)

    # Group by source_group and source_id
    by_group   = defaultdict(list)
    by_source  = defaultdict(list)
    content_stats = defaultdict(lambda: defaultdict(int))

    for doc in docs:
        group     = doc.get("source", {}).get("source_group", "unknown")
        source_id = doc.get("source", {}).get("source_id", "unknown")
        avail     = doc.get("content", {}).get("content_available", "unknown")

        by_group[group].append(doc)
        by_source[source_id].append(doc)
        content_stats[group][avail] += 1

    # ── Read audit log ─────────────────────────────────────────────────────────
    events       = read_events(failed_path)
    failed_sources = [e for e in events if e.get("severity") == "error"]
    warnings      = [e for e in events if e.get("severity") == "warning"]

    # ── Per-group summary ──────────────────────────────────────────────────────
    group_summary = {}
    for group, group_docs in by_group.items():
        group_summary[group] = {
            "doc_count": len(group_docs),
            "sources": list({d["source"]["source_id"] for d in group_docs}),
            "content_availability": dict(content_stats[group]),
        }

    # ── Manifest ───────────────────────────────────────────────────────────────
    manifest = {
        "run_id": run_id,
        "layer": "layer_1",
        "built_at": now_project_iso(),
        "status": "complete" if docs else "empty",
        "totals": {
            "total_raw_documents": len(docs),
            "source_groups_collected": len(by_group),
            "sources_collected": len(by_source),
            "failed_source_events": len(failed_sources),
            "warning_events": len(warnings),
        },
        "by_source_group": group_summary,
        "collection_policy": {
            "run_profile": run_manifest.get("run_profile", {}).get("profile_name"),
            "enabled_source_groups": run_manifest.get("collection_strategy", {}).get("enabled_source_groups", []),
            "query_themes": run_manifest.get("collection_strategy", {}).get("query_themes", []),
            "query_theme_set": run_manifest.get("collection_strategy", {}).get("query_theme_set"),
            "collection_window": run_manifest.get("collection_strategy", {}).get("collection_window", {}),
            "collector_caps": run_manifest.get("collection_strategy", {}).get("collector_caps", {}),
            "source_specific_windows": {
                group: run_manifest.get("collection_strategy", {}).get("source_specific_windows", {}).get(group, {})
                for group in group_summary.keys()
            },
        },
        "failed_sources": [
            {
                "source_id":      e.get("source_id"),
                "event_type":     e.get("event_type"),
                "message":        e.get("message"),
                "retryable":      e.get("retryable", False),
                "occurred_at":    e.get("occurred_at"),
            }
            for e in failed_sources
        ],
        "output_paths": {
            "raw_documents":      str(raw_docs_path),
            "failed_sources":     str(failed_path),
            "extraction_manifest": str(manifest_path),
        },
        "layer_2_handoff": {
            "ready": len(docs) > 0,
            "input_file": str(raw_docs_path),
            "doc_count": len(docs),
        },
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return manifest


if __name__ == "__main__":
    # Use the most recent test run that has a raw_documents.jsonl
    run_id = "test_run_layer1"
    layer1_dir = RUNS_DIR / run_id / "layer_1"

    # Seed some test data if the folder doesn't exist
    raw_docs_path = layer1_dir / "raw_documents.jsonl"
    if not raw_docs_path.exists():
        print(f"No raw_documents.jsonl found at {raw_docs_path}")
        print("Run raw_document_writer.py first to generate test data.")
        import sys; sys.exit(1)

    print(f"Building extraction manifest for run: {run_id}\n")
    manifest = build_extraction_manifest(run_id=run_id, layer1_dir=layer1_dir)

    print(f"Total documents : {manifest['totals']['total_raw_documents']}")
    print(f"Source groups   : {manifest['totals']['source_groups_collected']}")
    print(f"Failed sources  : {manifest['totals']['failed_source_events']}")
    print(f"Layer 2 ready   : {manifest['layer_2_handoff']['ready']}")
    print(f"\nBy group:")
    for group, stats in manifest["by_source_group"].items():
        print(f"  {group}: {stats['doc_count']} docs from {stats['sources']}")

    print(f"\nManifest written to: {manifest['output_paths']['extraction_manifest']}")
