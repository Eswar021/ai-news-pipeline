"""
Layer 2 — Module 10: Layer 2 Validation Gate

Validates Layer 2 output before passing to Layer 3.

Checks:
  1. canonical_documents.jsonl exists and is non-empty
  2. source_spans.jsonl exists and is non-empty
  3. Every canonical document has canonical_document_id and raw_document_id
  4. Every canonical document has trust_tier
  5. Every source span has text and canonical_document_id
  6. Every source span references a valid canonical_document_id
  7. provenance_map.jsonl exists
  8. At least one document is usable_for_claim_extraction

Layer 2 passes with warnings if partial content is common (expected for news APIs).
Layer 2 fails hard if no documents were canonicalized.

Usage:
    python layer2_validation_gate.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from config.time_utils import now_project_iso

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def validate(run_id: str, layer2_dir: Path = None) -> dict:
    """
    Validate Layer 2 output files.

    Returns:
        {
            "passed": bool,
            "status": str,
            "checks": [{"check": str, "passed": bool, "detail": str}],
            "warnings": [str],
            "failure_reason": str | None,
            "ready_for_layer_3": bool,
            "ready_for_layer_4": bool,
        }
    """
    if layer2_dir is None:
        layer2_dir = RUNS_DIR / run_id / "layer_2"

    checks  = []
    warnings = []

    def _check(name, ok, detail=""):
        checks.append({"check": name, "passed": ok, "detail": detail})
        return ok

    # Check 1: canonical_documents.jsonl exists and non-empty
    canon_path = layer2_dir / "canonical_documents.jsonl"
    canon_docs = []
    if canon_path.exists():
        canon_docs = [json.loads(l) for l in canon_path.read_text().splitlines() if l.strip()]
    _check("canonical_documents_exists", bool(canon_docs),
           f"{len(canon_docs)} canonical documents")

    # Check 2: source_spans.jsonl exists and non-empty
    spans_path = layer2_dir / "source_spans.jsonl"
    spans = []
    if spans_path.exists():
        spans = [json.loads(l) for l in spans_path.read_text().splitlines() if l.strip()]
    _check("source_spans_exists", bool(spans),
           f"{len(spans)} source spans")

    # Check 3: required fields on all canonical docs
    missing_fields = [
        d.get("canonical_document_id", "?")
        for d in canon_docs
        if not d.get("canonical_document_id") or not d.get("raw_document_id")
    ]
    _check("canonical_docs_have_required_fields",
           len(missing_fields) == 0,
           f"{len(missing_fields)} docs missing canonical_document_id or raw_document_id")

    # Check 4: trust_tier present on all docs
    missing_tier = [d for d in canon_docs if "trust_tier" not in d]
    _check("all_docs_have_trust_tier", len(missing_tier) == 0,
           f"{len(missing_tier)} docs missing trust_tier")

    # Check 5: spans have text and back-reference
    bad_spans = [s for s in spans if not s.get("text") or not s.get("canonical_document_id")]
    _check("all_spans_have_text_and_doc_ref", len(bad_spans) == 0,
           f"{len(bad_spans)} spans missing text or canonical_document_id")

    # Check 6: span doc IDs reference valid canonical docs
    valid_doc_ids = {d["canonical_document_id"] for d in canon_docs if d.get("canonical_document_id")}
    orphan_spans = [s for s in spans if s.get("canonical_document_id") not in valid_doc_ids]
    _check("no_orphan_spans", len(orphan_spans) == 0,
           f"{len(orphan_spans)} spans reference unknown canonical_document_id")

    # Check 7: provenance_map.jsonl exists
    prov_path = layer2_dir / "provenance_map.jsonl"
    _check("provenance_map_exists", prov_path.exists(), str(prov_path))

    # Check 8: at least one doc usable for claim extraction
    usable = [d for d in canon_docs if d.get("usable_for_claim_extraction")]
    has_usable = len(usable) > 0
    _check("has_claim_extractable_docs", has_usable,
           f"{len(usable)} docs usable for claim extraction")
    if not has_usable:
        warnings.append("no_docs_usable_for_claim_extraction — Layer 4 will have no input")

    # Warnings for expected partial content
    partial = sum(1 for d in canon_docs if d.get("content_completeness") == "partial")
    title_only = sum(1 for d in canon_docs if d.get("content_completeness") == "title_only")
    if partial > 0:
        warnings.append(f"{partial} partial docs (news API snippets — expected)")
    if title_only > 0:
        warnings.append(f"{title_only} title_only docs (community signals — expected)")

    # ── Determine pass/fail ───────────────────────────────────────────────────
    hard_failures = [c for c in checks if not c["passed"]]
    # Only the first two checks (files exist) are hard failures
    critical_failures = [c for c in checks[:2] if not c["passed"]]

    passed = len(critical_failures) == 0
    status = "passed" if (passed and not hard_failures) else (
        "passed_with_warnings" if passed else "failed"
    )
    failure_reason = critical_failures[0]["detail"] if critical_failures else None

    return {
        "passed":           passed,
        "status":           status,
        "checks":           checks,
        "warnings":         warnings,
        "failure_reason":   failure_reason,
        "ready_for_layer_3": passed and len(canon_docs) > 0,
        "ready_for_layer_4": passed and len(usable) > 0,
        "counts": {
            "canonical_documents": len(canon_docs),
            "source_spans":        len(spans),
        },
    }


def write_report(run_id: str, report: dict, layer2_dir: Path = None) -> Path:
    """Write validation report JSON."""
    if layer2_dir is None:
        layer2_dir = RUNS_DIR / run_id / "layer_2"

    import json
    path = layer2_dir / "layer2_validation_report.json"
    report["run_id"]    = run_id
    report["checked_at"] = now_project_iso()
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


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

    report = validate(run_id)
    print(f"\nLayer 2 Validation — {run_id}")
    print(f"  Status     : {report['status']}")
    print(f"  Passed     : {report['passed']}")
    print(f"  Layer 3 ok : {report['ready_for_layer_3']}")
    print(f"  Layer 4 ok : {report['ready_for_layer_4']}")
    print(f"  Counts     : {report['counts']}")
    print(f"\nChecks:")
    for c in report["checks"]:
        mark = "✓" if c["passed"] else "✗"
        print(f"  {mark} {c['check']}: {c['detail']}")
    if report["warnings"]:
        print(f"\nWarnings:")
        for w in report["warnings"]:
            print(f"  ! {w}")
    if report["failure_reason"]:
        print(f"\nFailure: {report['failure_reason']}")
