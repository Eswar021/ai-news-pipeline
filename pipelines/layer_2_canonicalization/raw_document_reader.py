"""
Layer 2 — Module 1: Raw Document Reader + Schema Validator

Reads raw_documents.jsonl from Layer 1, validates that each record has the
minimum required fields to be processed. Returns validated docs and rejects.

Required fields (hard, doc is rejected without them):
  raw_document_id, run_id, source.source_id, source.source_group, item.title

Soft warnings (doc is flagged but still processed):
  item.url missing, item.published_at missing, content.raw_text empty

Usage:
    python raw_document_reader.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Generator

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


REQUIRED_FIELDS = [
    ("raw_document_id",),
    ("run_id",),
    ("source", "source_id"),
    ("source", "source_group"),
    ("item", "title"),
]

SOFT_FIELDS = [
    ("item", "url"),
    ("item", "published_at"),
]


def _get_nested(doc: dict, *keys):
    """Walk nested keys, return value or None."""
    cur = doc
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def validate_doc(doc: dict) -> dict:
    """
    Validate a single raw document record.

    Returns:
        {
            "status": "valid" | "valid_with_warnings" | "rejected",
            "warnings": [...],
            "rejection_reason": str | None,
            "processable": bool,
        }
    """
    warnings = []
    rejection_reason = None

    for key_path in REQUIRED_FIELDS:
        val = _get_nested(doc, *key_path)
        if not val:
            rejection_reason = f"missing_required_field: {'.'.join(key_path)}"
            return {
                "status": "rejected",
                "warnings": [],
                "rejection_reason": rejection_reason,
                "processable": False,
            }

    for key_path in SOFT_FIELDS:
        val = _get_nested(doc, *key_path)
        if not val:
            warnings.append(f"missing_soft_field: {'.'.join(key_path)}")

    raw_text = _get_nested(doc, "content", "raw_text") or ""
    content_available = _get_nested(doc, "content", "content_available") or ""
    if not raw_text and content_available not in ("title_only",):
        warnings.append("empty_raw_text_unexpected")

    source_group = _get_nested(doc, "source", "source_group") or ""
    if not source_group:
        warnings.append("unknown_source_group")

    status = "valid_with_warnings" if warnings else "valid"
    return {
        "status": status,
        "warnings": warnings,
        "rejection_reason": None,
        "processable": True,
    }


def read_and_validate(run_id: str, layer1_dir: Path = None):
    """
    Read raw_documents.jsonl and validate every record.

    Returns:
        valid_docs   — list of (doc, validation_result) for processable docs
        rejected_docs — list of (doc, validation_result) for rejected docs
    """
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    raw_path = layer1_dir / "raw_documents.jsonl"
    if not raw_path.exists():
        raise FileNotFoundError(f"raw_documents.jsonl not found at {raw_path}")

    valid_docs = []
    rejected_docs = []

    with open(raw_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError as e:
                rejected_docs.append(({}, {
                    "status": "rejected",
                    "warnings": [],
                    "rejection_reason": f"json_parse_error_line_{lineno}: {e}",
                    "processable": False,
                }))
                continue

            result = validate_doc(doc)
            if result["processable"]:
                valid_docs.append((doc, result))
            else:
                rejected_docs.append((doc, result))

    return valid_docs, rejected_docs


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
        if not run_dirs:
            print("No runs found.")
            sys.exit(1)
        run_id = run_dirs[0].parent.name
        print(f"Auto-discovered run: {run_id}")

    valid, rejected = read_and_validate(run_id)

    print(f"\nRaw Document Reader — {run_id}")
    print(f"  Valid       : {len(valid)}")
    print(f"  Rejected    : {len(rejected)}")

    print("\nSample valid doc validation:")
    doc, res = valid[0]
    print(f"  ID     : {doc.get('raw_document_id')}")
    print(f"  Group  : {doc.get('source', {}).get('source_group')}")
    print(f"  Status : {res['status']}")
    print(f"  Warnings: {res['warnings']}")

    if rejected:
        print("\nRejected docs:")
        for d, r in rejected:
            print(f"  {d.get('raw_document_id', '?')} — {r['rejection_reason']}")
