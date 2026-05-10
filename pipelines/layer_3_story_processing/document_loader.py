"""
Layer 3 — Module 1: Document Loader

Loads canonical documents and source spans from Layer 2.
Builds a doc_id → span_ids index.
Validates required fields and marks invalid documents.

Usage:
    python document_loader.py --run-id run_2026_05_10_48h_auto
    python document_loader.py   # auto-discovers latest run
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_REQUIRED_DOC_FIELDS = {
    "canonical_document_id", "raw_document_id", "run_id",
    "source_group", "trust_tier", "source_role", "title",
}


def load(run_id: str, layer2_dir: Path = None) -> dict:
    """
    Load and validate Layer 2 canonical documents and source spans.

    Returns:
        {
            "valid_docs":    [doc_dict, ...],
            "invalid_docs":  [(doc_dict, reason_str), ...],
            "all_spans":     [span_dict, ...],
            "doc_span_index": {canonical_document_id: [span_id, ...], ...},
            "counts": {...},
        }
    """
    if layer2_dir is None:
        layer2_dir = RUNS_DIR / run_id / "layer_2"

    # ── Load canonical documents ───────────────────────────────────────────────
    canon_path = layer2_dir / "canonical_documents.jsonl"
    raw_docs = [json.loads(l) for l in canon_path.read_text().splitlines() if l.strip()]

    valid_docs   = []
    invalid_docs = []

    for doc in raw_docs:
        missing = _REQUIRED_DOC_FIELDS - set(doc.keys())
        if missing:
            invalid_docs.append((doc, f"missing_fields:{','.join(sorted(missing))}"))
            continue
        if not doc.get("canonical_document_id") or not doc.get("title"):
            invalid_docs.append((doc, "empty_required_field"))
            continue
        valid_docs.append(doc)

    # ── Load source spans ──────────────────────────────────────────────────────
    spans_path = layer2_dir / "source_spans.jsonl"
    all_spans = [json.loads(l) for l in spans_path.read_text().splitlines() if l.strip()]

    # ── Build doc → span index ─────────────────────────────────────────────────
    valid_ids = {d["canonical_document_id"] for d in valid_docs}
    doc_span_index: dict[str, list[str]] = {doc_id: [] for doc_id in valid_ids}

    orphan_spans = 0
    for span in all_spans:
        doc_id = span.get("canonical_document_id", "")
        if doc_id in doc_span_index:
            doc_span_index[doc_id].append(span["span_id"])
        else:
            orphan_spans += 1

    return {
        "valid_docs":     valid_docs,
        "invalid_docs":   invalid_docs,
        "all_spans":      all_spans,
        "doc_span_index": doc_span_index,
        "counts": {
            "raw_docs_loaded":     len(raw_docs),
            "valid_docs":          len(valid_docs),
            "invalid_docs":        len(invalid_docs),
            "spans_loaded":        len(all_spans),
            "orphan_spans":        orphan_spans,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    if args.run_id:
        run_id = args.run_id
    else:
        run_dirs = sorted(RUNS_DIR.glob("*/run_manifest.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = run_dirs[0].parent.name
        print(f"Auto-discovered run: {run_id}")

    result = load(run_id)
    print(f"\nDocument Loader — {run_id}")
    for k, v in result["counts"].items():
        print(f"  {k:30}: {v}")
    print(f"\n  Sample valid doc: {result['valid_docs'][0]['title'][:60]}")
    sample_id = result["valid_docs"][0]["canonical_document_id"]
    spans = result["doc_span_index"].get(sample_id, [])
    print(f"  Spans for that doc: {len(spans)}")
