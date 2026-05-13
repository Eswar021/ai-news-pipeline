"""
Layer 9 validation gate with tri-state output semantics.
"""

from __future__ import annotations

import json
from pathlib import Path


_APPROVED_STATUSES = {"approved", "approved_with_warnings"}
_REVISION_STATUSES = {"revisable", "blocked"}


def validate(run_id: str, layer9_dir: Path) -> dict:
    errors = []
    warnings = []

    vr_path = layer9_dir / "verification_report.json"
    if not vr_path.exists():
        return {
            "run_id": run_id,
            "passed": False,
            "status": "failed",
            "failure_reason": "verification_report.json missing",
            "errors": ["verification_report.json not found."],
            "warnings": [],
            "ready_for_layer_10": False,
        }

    report = json.loads(vr_path.read_text(encoding="utf-8"))
    final_status = report.get("summary", {}).get("final_status", "")

    if not (layer9_dir / "layer9_manifest.json").exists():
        errors.append("layer9_manifest.json missing.")

    revision_package_path = layer9_dir / "revision_package.json"
    if not revision_package_path.exists():
        errors.append("revision_package.json missing.")

    if not (layer9_dir / "verified_youtube_metadata.json").exists():
        errors.append("verified_youtube_metadata.json missing.")

    if not (layer9_dir / "final_publish_package.json").exists():
        errors.append("final_publish_package.json missing.")

    verified_script_path = layer9_dir / "verified_script.md"
    if final_status in _APPROVED_STATUSES:
        if not verified_script_path.exists() or verified_script_path.stat().st_size < 100:
            errors.append("verified_script.md missing or too small for approved output.")

    if final_status in _REVISION_STATUSES:
        if report.get("decision", {}).get("ready_for_layer_10"):
            errors.append("Revision-required outcome incorrectly marked ready_for_layer_10.")
        warnings.append(
            f"Layer 9 requires revision ({final_status}). See revision_package.json before rerunning layers 8,9."
        )

    metadata_detail = report.get("check_details", {}).get("metadata_safety", {})
    if metadata_detail.get("errors"):
        warnings.append(f"Metadata safety errors: {metadata_detail['errors'][:1]}")

    attribution_detail = report.get("check_details", {}).get("source_attribution", {})
    if attribution_detail.get("missing_from_list", 0) > 0:
        warnings.append(
            f"Source attribution: {attribution_detail['missing_from_list']} sources used but not listed."
        )

    if errors:
        status = "failed"
        passed = False
    elif final_status in _APPROVED_STATUSES:
        status = "passed"
        passed = True
    elif final_status in _REVISION_STATUSES:
        status = "revisable"
        passed = False
    else:
        status = "failed"
        passed = False
        errors.append(f"Unknown Layer 9 final_status: {final_status!r}")

    return {
        "run_id": run_id,
        "passed": passed,
        "status": status,
        "failure_reason": errors[0] if errors else None,
        "errors": errors,
        "warnings": warnings,
        "ready_for_layer_10": final_status in _APPROVED_STATUSES and not errors,
        "final_status": final_status,
        "risk_level": report.get("summary", {}).get("overall_risk_level", ""),
        "risk_score": report.get("summary", {}).get("risk_score", 0),
        "critical_issues": report.get("summary", {}).get("critical_issue_count", 0),
        "high_issues": report.get("summary", {}).get("high_issue_count", 0),
        "medium_issues": report.get("summary", {}).get("medium_issue_count", 0),
    }


def write_report(run_id: str, report: dict, layer9_dir: Path) -> Path:
    path = layer9_dir / "layer9_validation_report.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return path
