"""
Layer 2 Orchestrator — Canonicalization + Evidence Store

Reads Layer 1 output, runs all 10 processing modules in sequence for each
document, and writes the complete Layer 2 evidence store.

Per-document pipeline:
  1. raw_document_reader      → validate schema
  2. content_cleaner          → clean text
  3. metadata_normalizer      → normalize dates, content_type
  4. canonical_url_resolver   → strip tracking params, generate doc ID
  5. content_quality_classifier → quality score, completeness, usability
  6. trust_tier_tagger        → trust tier + source role
  7. source_span_chunker      → split into citeable spans
  8. provenance_builder       → write clean text file, build traceability
  [collect all]
  9. evidence_store_writer    → write all JSONL files + reports
  10. layer2_validation_gate  → validate output before Layer 3

Output:
    data/runs/{run_id}/layer_2/
      canonical_documents.jsonl
      source_spans.jsonl
      provenance_map.jsonl
      content_quality_report.json
      source_trust_report.json
      rejected_documents.jsonl
      layer2_manifest.json
      layer2_validation_report.json
      clean_text/

Usage:
    python run_layer_2.py --run-id run_2026_05_10_48h_auto
    python run_layer_2.py                            # auto-discovers latest run
"""

import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_2_canonicalization.raw_document_reader     import read_and_validate
from pipelines.layer_2_canonicalization.content_cleaner         import clean as clean_text
from pipelines.layer_2_canonicalization.metadata_normalizer     import normalize as normalize_meta
from pipelines.layer_2_canonicalization.canonical_url_resolver  import resolve as resolve_url
from pipelines.layer_2_canonicalization.content_quality_classifier import classify as classify_quality
from pipelines.layer_2_canonicalization.trust_tier_tagger       import tag as tag_trust
from pipelines.layer_2_canonicalization.source_span_chunker     import chunk as chunk_spans
from pipelines.layer_2_canonicalization.provenance_builder      import build as build_provenance
from pipelines.layer_2_canonicalization.evidence_store_writer   import write as write_store
from pipelines.layer_2_canonicalization.layer2_validation_gate  import validate, write_report


def _process_document(raw_doc: dict, layer2_dir: Path) -> tuple[dict | None, list[dict], dict | None, dict | None]:
    """
    Run one raw document through the full Layer 2 pipeline.

    Returns (canonical_doc, source_spans, provenance_record, rejection_record)
    where rejection_record is set if the document was rejected.
    """
    source = raw_doc.get("source", {})
    item   = raw_doc.get("content", {})

    source_group   = source.get("source_group", "")
    source_id      = source.get("source_id", "")
    raw_text       = item.get("raw_text") or ""
    content_avail  = item.get("content_available") or ""
    title          = raw_doc.get("item", {}).get("title") or ""

    # Step 2: clean text
    clean_result   = clean_text(raw_text, source_group, title)
    cleaned        = clean_result["clean_text"]

    # Step 3: normalize metadata
    meta           = normalize_meta(raw_doc)

    # Step 4: resolve canonical URL + document ID
    url_result     = resolve_url(raw_doc, iso_date=meta["published_at"])
    canon_url      = url_result["canonical_url"]
    canon_doc_id   = url_result["canonical_document_id"]

    # Step 5: content quality
    quality        = classify_quality(cleaned, source_group, content_avail, title)

    # Step 6: trust tier
    trust          = tag_trust(raw_doc, quality["content_completeness"])

    # Step 7: chunk into source spans
    spans          = chunk_spans(
        canonical_document_id=canon_doc_id,
        clean_text=cleaned,
        source_group=source_group,
        source_id=source_id,
        canonical_url=canon_url,
        trust_tier=trust["trust_tier"],
        source_role=trust["source_role"],
        content_completeness=quality["content_completeness"],
        title=title,
        item=raw_doc.get("item", {}),
    )

    # Step 8: build provenance
    span_ids       = [s["span_id"] for s in spans]
    transformations = ["text_extracted"]
    if clean_result["boilerplate_removed"]:
        transformations.append("boilerplate_removed")
    if clean_result["was_truncated"]:
        transformations.append("truncation_marker_removed")
    transformations += ["metadata_normalized", "source_span_chunked"]

    prov_record    = build_provenance(
        raw_doc=raw_doc,
        canonical_document_id=canon_doc_id,
        clean_text=cleaned,
        span_ids=span_ids,
        canonical_url=canon_url,
        layer2_dir=layer2_dir,
        transformations=transformations,
    )

    # Assemble canonical document
    canon_doc = {
        "canonical_document_id": canon_doc_id,
        "raw_document_id":       raw_doc.get("raw_document_id"),
        "run_id":                raw_doc.get("run_id"),

        # Source
        "source_id":             source_id,
        "source_name":           source.get("source_name", ""),
        "source_group":          source_group,
        "source_type":           source.get("source_type", ""),

        # Trust
        "trust_tier":            trust["trust_tier"],
        "source_role":           trust["source_role"],
        "can_support_factual_claims":   trust["can_support_factual_claims"],
        "can_support_technical_claims": trust["can_support_technical_claims"],
        "can_support_trend_signal":     trust["can_support_trend_signal"],
        "can_support_quote":            trust["can_support_quote"],

        # Identity
        "title":                 meta["title"],
        "canonical_url":         canon_url,
        "original_url":          url_result["original_url"],
        "published_at":          meta["published_at"],
        "date_confidence":       meta["date_confidence"],
        "author":                meta["author"],
        "publisher":             meta["publisher"],
        "language":              meta["language"],
        "content_type":          meta["content_type"],

        # Content quality
        "content_completeness":           quality["content_completeness"],
        "content_quality_score":          quality["quality_score"],
        "word_count":                     quality["word_count"],
        "usable_for_story_clustering":    quality["usable_for_story_clustering"],
        "usable_for_claim_extraction":    quality["usable_for_claim_extraction"],
        "usable_for_trend_signal":        quality["usable_for_trend_signal"],

        # Provenance pointer
        "clean_text_path":       prov_record["storage_trace"]["clean_text_path"],
        "span_count":            len(spans),

        # Warnings
        "warnings": meta["metadata_warnings"] + quality["quality_warnings"],
    }

    return canon_doc, spans, prov_record, None


def run_layer_2(run_id: str, layer1_dir: Path = None) -> dict:
    """
    Execute the full Layer 2 canonicalization pipeline.

    Returns the layer2_manifest dict.
    """
    started_at = datetime.now(timezone.utc)

    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    layer2_dir = RUNS_DIR / run_id / "layer_2"

    print(f"[Layer 2] Run       : {run_id}")
    print(f"[Layer 2] Input     : {layer1_dir}")
    print(f"[Layer 2] Output    : {layer2_dir}\n")

    # Step 1: Read and validate Layer 1 output
    print("[Layer 2] Step 1 — Reading and validating Layer 1 output...")
    valid_docs, rejected_from_reader = read_and_validate(run_id, layer1_dir)
    print(f"  Valid: {len(valid_docs)}  |  Rejected: {len(rejected_from_reader)}")

    # Steps 2–8: Process each document
    print("[Layer 2] Steps 2–8 — Processing documents...")
    canonical_documents = []
    all_source_spans    = []
    provenance_records  = []
    rejected_documents  = [
        {"raw_document_id": d.get("raw_document_id", "?"),
         "rejection_reason": r["rejection_reason"],
         "source": "schema_validation"}
        for d, r in rejected_from_reader
    ]

    for doc, validation_result in valid_docs:
        try:
            canon_doc, spans, prov, rejection = _process_document(doc, layer2_dir)
            if rejection:
                rejected_documents.append(rejection)
            else:
                canonical_documents.append(canon_doc)
                all_source_spans.extend(spans)
                provenance_records.append(prov)
        except Exception as e:
            rejected_documents.append({
                "raw_document_id": doc.get("raw_document_id", "?"),
                "rejection_reason": f"processing_error: {e}",
                "source": "layer2_pipeline",
            })

    print(f"  Canonical docs : {len(canonical_documents)}")
    print(f"  Source spans   : {len(all_source_spans)}")
    print(f"  Rejected       : {len(rejected_documents)}")

    # Step 9: Write evidence store
    print("[Layer 2] Step 9 — Writing evidence store...")
    manifest = write_store(
        run_id=run_id,
        layer2_dir=layer2_dir,
        canonical_documents=canonical_documents,
        source_spans=all_source_spans,
        provenance_records=provenance_records,
        rejected_documents=rejected_documents,
    )

    # Step 10: Validate
    print("[Layer 2] Step 10 — Validating output...")
    report = validate(run_id, layer2_dir)
    write_report(run_id, report, layer2_dir)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*55}")
    print(f"Layer 2 {'PASSED' if report['passed'] else 'FAILED'} ({report['status']})")
    print(f"  Canonical docs : {len(canonical_documents)}")
    print(f"  Source spans   : {len(all_source_spans)}")
    print(f"  Rejected       : {len(rejected_documents)}")
    print(f"  Ready Layer 3  : {report['ready_for_layer_3']}")
    print(f"  Ready Layer 4  : {report['ready_for_layer_4']}")
    print(f"  Elapsed        : {elapsed:.1f}s")
    print(f"  Output         : {layer2_dir}")
    if report["warnings"]:
        for w in report["warnings"]:
            print(f"  ! {w}")
    if not report["passed"]:
        print(f"  Failure: {report['failure_reason']}")
    print(f"{'='*55}\n")

    return manifest


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 2 — Canonicalization + Evidence Store")
    parser.add_argument("--run-id",  required=False, help="Run ID from Layer 0/1")
    args = parser.parse_args()

    if args.run_id:
        run_id = args.run_id
    else:
        run_dirs = sorted(RUNS_DIR.glob("*/run_manifest.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        if not run_dirs:
            print("No runs found. Run run_layer_0.py + run_layer_1.py first.")
            sys.exit(1)
        run_id = run_dirs[0].parent.name
        print(f"Auto-discovered run: {run_id}")

    result = run_layer_2(run_id)
    print(f"Layer 3 input: {result['outputs']['canonical_documents']}")
    print(f"Canonical docs: {result['counts']['canonical_documents_created']}")
    print(f"Source spans:  {result['counts']['source_spans_created']}")
