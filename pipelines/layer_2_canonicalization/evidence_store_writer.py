"""
Layer 2 — Module 9: Evidence Store Writer

Writes all Layer 2 output files:
  canonical_documents.jsonl
  source_spans.jsonl
  provenance_map.jsonl
  content_quality_report.json
  source_trust_report.json
  rejected_documents.jsonl
  layer2_manifest.json

Usage:
    Called by run_layer_2.py — not meant to be run directly.
    Has a __main__ block that shows what would be written for a dry run.
"""

import sys
import json
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def _write_jsonl(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write(
    run_id: str,
    layer2_dir: Path,
    canonical_documents: list[dict],
    source_spans: list[dict],
    provenance_records: list[dict],
    rejected_documents: list[dict],
) -> dict:
    """
    Write all Layer 2 output files and return the layer2_manifest dict.

    Args:
        run_id:               The run ID
        layer2_dir:           data/runs/{run_id}/layer_2/
        canonical_documents:  List of CanonicalDocument dicts
        source_spans:         List of SourceSpan dicts
        provenance_records:   List of ProvenanceRecord dicts
        rejected_documents:   List of rejection records

    Returns:
        layer2_manifest dict (also written to disk).
    """
    layer2_dir.mkdir(parents=True, exist_ok=True)

    # ── Write JSONL files ──────────────────────────────────────────────────────
    _write_jsonl(layer2_dir / "canonical_documents.jsonl", canonical_documents)
    _write_jsonl(layer2_dir / "source_spans.jsonl",        source_spans)
    _write_jsonl(layer2_dir / "provenance_map.jsonl",      provenance_records)
    _write_jsonl(layer2_dir / "rejected_documents.jsonl",  rejected_documents)

    # ── Content quality report ─────────────────────────────────────────────────
    completeness_counts = Counter(
        d.get("content_completeness", "unknown") for d in canonical_documents
    )
    quality_warnings = []
    partial_count = completeness_counts.get("partial", 0)
    title_only    = completeness_counts.get("title_only", 0)
    if partial_count > 0:
        quality_warnings.append({
            "warning_type": "partial_content",
            "count": partial_count,
            "message": f"{partial_count} docs are partial snippets (news API truncation).",
        })
    if title_only > 0:
        quality_warnings.append({
            "warning_type": "title_only",
            "count": title_only,
            "message": f"{title_only} docs have title only (community signals).",
        })

    missing_dates = sum(
        1 for d in canonical_documents
        if not d.get("published_at")
    )
    if missing_dates > 0:
        quality_warnings.append({
            "warning_type": "missing_publish_date",
            "count": missing_dates,
        })

    quality_report = {
        "run_id":                   run_id,
        "documents_received":       len(canonical_documents) + len(rejected_documents),
        "documents_canonicalized":  len(canonical_documents),
        "documents_rejected":       len(rejected_documents),
        "source_spans_created":     len(source_spans),
        "quality_summary":          dict(completeness_counts),
        "warnings":                 quality_warnings,
        "generated_at":             datetime.now(timezone.utc).isoformat(),
    }
    _write_json(layer2_dir / "content_quality_report.json", quality_report)

    # ── Source trust report ────────────────────────────────────────────────────
    tier_counts: dict[str, int] = {}
    for d in canonical_documents:
        tier = d.get("trust_tier", 4)
        role = d.get("source_role", "unknown")
        key  = f"tier_{str(tier).replace('.', '_')}_{role}"
        tier_counts[key] = tier_counts.get(key, 0) + 1

    trust_report = {
        "run_id":       run_id,
        "trust_summary": tier_counts,
        "source_role_rules": {
            "community_can_support_factual_claims": False,
            "official_sources_can_support_core_claims": True,
            "research_sources_can_support_technical_claims": True,
            "partial_snippets_can_support_claims": False,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(layer2_dir / "source_trust_report.json", trust_report)

    # ── Layer 2 manifest (handoff to Layer 3) ─────────────────────────────────
    runs_dir = layer2_dir.parent.parent

    manifest = {
        "run_id":  run_id,
        "layer":   "layer_2_canonicalization_evidence_store",
        "created_at": datetime.now(timezone.utc).isoformat(),

        "inputs": {
            "raw_documents": str(layer2_dir.parent / "layer_1" / "raw_documents.jsonl"),
            "layer1_manifest": str(layer2_dir.parent / "layer_1" / "extraction_manifest.json"),
        },

        "outputs": {
            "canonical_documents": str(layer2_dir / "canonical_documents.jsonl"),
            "source_spans":        str(layer2_dir / "source_spans.jsonl"),
            "provenance_map":      str(layer2_dir / "provenance_map.jsonl"),
            "content_quality_report": str(layer2_dir / "content_quality_report.json"),
            "source_trust_report": str(layer2_dir / "source_trust_report.json"),
            "rejected_documents":  str(layer2_dir / "rejected_documents.jsonl"),
            "clean_text_dir":      str(layer2_dir / "clean_text"),
        },

        "counts": {
            "raw_documents_received":       len(canonical_documents) + len(rejected_documents),
            "canonical_documents_created":  len(canonical_documents),
            "source_spans_created":         len(source_spans),
            "rejected_documents":           len(rejected_documents),
        },

        "quality_summary": dict(completeness_counts),

        "handoff": {
            "ready_for_layer_3": len(canonical_documents) > 0,
            "ready_for_layer_4": any(
                d.get("usable_for_claim_extraction") for d in canonical_documents
            ),
            "next_layer": "layer_3_story_processing",
        },
    }
    _write_json(layer2_dir / "layer2_manifest.json", manifest)

    return manifest


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("evidence_store_writer.py — called by run_layer_2.py orchestrator")
    print("Run 'python run_layer_2.py' to produce all Layer 2 output files.")
