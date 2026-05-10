"""
Layer 2 — Module 8: Provenance Builder

Builds the traceability chain:
  raw_document_id → canonical_document_id → span_ids

Also writes clean text to layer_2/clean_text/{doc_id}.txt
and records SHA256 hashes for audit trail.

Usage:
    python provenance_builder.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import hashlib
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_clean_text(clean_text: str, canonical_document_id: str,
                     layer2_dir: Path) -> Path:
    """Write clean text to layer_2/clean_text/{doc_id}.txt. Returns path."""
    clean_dir = layer2_dir / "clean_text"
    clean_dir.mkdir(parents=True, exist_ok=True)
    out_path = clean_dir / f"{canonical_document_id}.txt"
    out_path.write_text(clean_text, encoding="utf-8")
    return out_path


def build(raw_doc: dict, canonical_document_id: str,
          clean_text: str, span_ids: list[str],
          canonical_url: str, layer2_dir: Path,
          transformations: list[str] = None) -> dict:
    """
    Build a provenance record for one document.

    Writes clean text file, computes hashes, assembles traceability chain.

    Args:
        raw_doc:               The original Layer 1 raw document dict
        canonical_document_id: From canonical_url_resolver
        clean_text:            From content_cleaner
        span_ids:              List of span_ids from source_span_chunker
        canonical_url:         From canonical_url_resolver
        layer2_dir:            data/runs/{run_id}/layer_2/
        transformations:       List of applied transformations

    Returns:
        ProvenanceRecord dict.
    """
    raw_document_id = raw_doc.get("raw_document_id", "")
    collected_at    = raw_doc.get("collection", {}).get("collected_at", "")
    original_url    = raw_doc.get("item", {}).get("url", "")

    # Write clean text file
    clean_text_path = write_clean_text(clean_text, canonical_document_id, layer2_dir)
    clean_text_hash = _sha256(clean_text)

    # Raw payload path (Layer 1 stored raw JSON batches, not per-doc files)
    # Point to the raw_document_id for audit — actual payload in Layer 1 payloads/
    raw_payload_ref = f"layer_1/raw_payloads/ (raw_document_id={raw_document_id})"

    if transformations is None:
        transformations = ["text_extracted", "boilerplate_removed",
                           "metadata_normalized", "source_span_chunked"]

    return {
        "provenance_id":        f"prov_{canonical_document_id}",
        "raw_document_id":      raw_document_id,
        "canonical_document_id": canonical_document_id,
        "span_ids":             span_ids,
        "source_trace": {
            "source_id":       raw_doc.get("source", {}).get("source_id", ""),
            "source_group":    raw_doc.get("source", {}).get("source_group", ""),
            "original_url":    original_url,
            "canonical_url":   canonical_url,
            "collected_at":    collected_at,
            "canonicalized_at": datetime.now(timezone.utc).isoformat(),
        },
        "storage_trace": {
            "raw_payload_ref":  raw_payload_ref,
            "clean_text_path":  str(clean_text_path),
        },
        "hashes": {
            "clean_text_sha256": clean_text_hash,
        },
        "transformations": transformations,
    }


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    from pipelines.layer_2_canonicalization.content_cleaner import clean as clean_fn

    if args.run_id:
        run_id = args.run_id
    else:
        run_dirs = sorted(RUNS_DIR.glob("*/run_manifest.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = run_dirs[0].parent.name
        print(f"Auto-discovered run: {run_id}")

    raw_path  = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    layer2_dir.mkdir(parents=True, exist_ok=True)

    docs = [json.loads(l) for l in raw_path.read_text().splitlines() if l.strip()]
    doc  = docs[0]

    title      = doc["item"].get("title", "")
    raw        = doc["content"].get("raw_text", "")
    sg         = doc["source"]["source_group"]
    cleaned    = clean_fn(raw, sg, title)["clean_text"]
    canon_url  = doc["item"].get("url", "")
    canon_id   = "doc_20260510_openai_news_test001"
    span_ids   = ["span_doc_test001_0000", "span_doc_test001_0001"]

    record = build(doc, canon_id, cleaned, span_ids, canon_url, layer2_dir)

    print(f"\nProvenance Builder — {run_id}")
    print(f"  provenance_id    : {record['provenance_id']}")
    print(f"  raw_document_id  : {record['raw_document_id']}")
    print(f"  span_ids         : {record['span_ids']}")
    print(f"  clean_text_path  : {record['storage_trace']['clean_text_path']}")
    print(f"  clean_text_sha256: {record['hashes']['clean_text_sha256'][:16]}...")
    print(f"  transformations  : {record['transformations']}")

    # Verify the file was written
    fpath = Path(record["storage_trace"]["clean_text_path"])
    print(f"\n  Clean text file exists: {fpath.exists()}")
    print(f"  First 100 chars: {fpath.read_text()[:100]}")
