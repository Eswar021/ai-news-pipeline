"""
Module: layer1_validation_gate
Layer: 1 — Source Extraction
Purpose: Check that Layer 1's output meets the minimum bar before handing off to Layer 2.
         Doesn't block on API failures — it checks whether what we DID collect is
         good enough to produce a video. If not, it raises with a clear failure reason.

Checks:
    1. raw_documents.jsonl exists and is non-empty
    2. At least one tier-1 or tier-2 source contributed documents
    3. Every document has required fields (raw_document_id, source, item, content, collection)
    4. Primary evidence sources have at least some content (not just titles)
    5. extraction_manifest.json exists

Run standalone:
    python layer1_validation_gate.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from config.time_utils import now_project_iso

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_1_extraction.raw_document_writer import read_raw_documents


_REQUIRED_DOC_FIELDS = ["raw_document_id", "run_id", "source", "item", "content", "collection"]
_PRIMARY_TIERS       = {1, 1.5, 2}


def validate(run_id: str, layer1_dir: Path = None) -> dict:
    """
    Validate Layer 1 output and return a report dict.

    Returns:
        {
          "passed": bool,
          "checks": [{name, passed, detail}],
          "failure_reason": str or None,
          "stats": {...}
        }
    """
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    raw_docs_path = layer1_dir / "raw_documents.jsonl"
    manifest_path = layer1_dir / "extraction_manifest.json"

    checks = []

    # ── Check 1: raw_documents.jsonl exists ───────────────────────────────────
    exists = raw_docs_path.exists()
    checks.append({"name": "raw_documents_exists", "passed": exists,
                   "detail": str(raw_docs_path) if exists else "File not found"})
    if not exists:
        return _report(checks, "raw_documents.jsonl not found — no extraction ran", {})

    # ── Check 2: Has documents ────────────────────────────────────────────────
    docs = read_raw_documents(raw_docs_path)
    has_docs = len(docs) > 0
    checks.append({"name": "has_documents", "passed": has_docs,
                   "detail": f"{len(docs)} documents"})
    if not has_docs:
        return _report(checks, "raw_documents.jsonl is empty — all collectors failed", {})

    # ── Check 3: Required fields on all docs ──────────────────────────────────
    bad_docs = []
    for doc in docs:
        missing = [f for f in _REQUIRED_DOC_FIELDS if f not in doc]
        if missing:
            bad_docs.append({"id": doc.get("raw_document_id", "?"), "missing": missing})
    fields_ok = len(bad_docs) == 0
    checks.append({"name": "required_fields", "passed": fields_ok,
                   "detail": f"{len(bad_docs)} docs missing fields" if bad_docs else "All fields present",
                   "bad_docs": bad_docs[:5]})

    # ── Check 4: At least one primary-tier source ─────────────────────────────
    primary_docs = [
        d for d in docs
        if d.get("source", {}).get("trust_tier_hint") in _PRIMARY_TIERS
    ]
    has_primary = len(primary_docs) > 0
    checks.append({"name": "has_primary_evidence", "passed": has_primary,
                   "detail": f"{len(primary_docs)} docs from tier 1/1.5/2 sources"})

    # ── Check 5: Primary docs have actual content (not just titles) ───────────
    primary_with_content = [
        d for d in primary_docs
        if len(d.get("content", {}).get("raw_text", "")) > 50
    ]
    content_ratio = len(primary_with_content) / len(primary_docs) if primary_docs else 0
    has_content = content_ratio >= 0.3  # at least 30% have real content
    checks.append({"name": "primary_content_quality", "passed": has_content,
                   "detail": f"{len(primary_with_content)}/{len(primary_docs)} primary docs have content ({content_ratio:.0%})"})

    # ── Check 6: extraction_manifest exists ───────────────────────────────────
    manifest_exists = manifest_path.exists()
    checks.append({"name": "extraction_manifest_exists", "passed": manifest_exists,
                   "detail": str(manifest_path) if manifest_exists else "Run layer1_output_packager first"})

    # ── Determine overall pass/fail ───────────────────────────────────────────
    hard_failures = [c for c in checks if not c["passed"] and c["name"] in
                     ("raw_documents_exists", "has_documents", "has_primary_evidence")]
    failure_reason = hard_failures[0]["name"] if hard_failures else None

    stats = {
        "total_docs": len(docs),
        "primary_docs": len(primary_docs),
        "primary_with_content": len(primary_with_content),
        "content_ratio": round(content_ratio, 3),
        "source_groups": list({d.get("source", {}).get("source_group") for d in docs}),
    }

    return _report(checks, failure_reason, stats)


def _report(checks: list, failure_reason, stats: dict) -> dict:
    all_passed = all(c["passed"] for c in checks)
    return {
        "passed": all_passed and failure_reason is None,
        "checks": checks,
        "failure_reason": failure_reason,
        "stats": stats,
        "validated_at": now_project_iso(),
    }


def write_report(run_id: str, report: dict, layer1_dir: Path = None) -> Path:
    """Write the validation report to layer1_validation_report.json."""
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"
    report_path = layer1_dir / "layer1_validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report_path


if __name__ == "__main__":
    run_id = "test_run_layer1"
    layer1_dir = RUNS_DIR / run_id / "layer_1"

    if not (layer1_dir / "raw_documents.jsonl").exists():
        print(f"No raw_documents.jsonl at {layer1_dir}")
        print("Run raw_document_writer.py first.")
        import sys; sys.exit(1)

    print(f"Validating Layer 1 output for run: {run_id}\n")
    report = validate(run_id=run_id, layer1_dir=layer1_dir)
    report_path = write_report(run_id=run_id, report=report, layer1_dir=layer1_dir)

    status = "PASSED" if report["passed"] else "FAILED"
    print(f"Validation: {status}\n")

    for check in report["checks"]:
        icon = "✓" if check["passed"] else "✗"
        print(f"  {icon} {check['name']}: {check['detail']}")

    if report["failure_reason"]:
        print(f"\nFailure reason: {report['failure_reason']}")

    print(f"\nStats: {json.dumps(report['stats'], indent=2)}")
    print(f"\nReport written to: {report_path}")
