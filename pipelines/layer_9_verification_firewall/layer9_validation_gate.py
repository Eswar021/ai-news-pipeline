"""
Layer 9 — Module 17: Layer 9 Validation Gate

Validates Layer 9 output before handoff to Layer 10.

Hard failures (block Layer 10):
  1. verification_report.json missing
  2. verified_script.md missing or empty
  3. layer9_manifest.json missing
  4. final_recommendation is 'blocked' (critical issues found)

Soft warnings (pass with warning):
  5. correction_patch has unapplied patches
  6. source_attribution missing sources
  7. metadata_safety has errors

Key functions:
    validate(run_id, layer9_dir) → report dict
    write_report(run_id, report, layer9_dir) → path
"""

import json
from pathlib import Path


def validate(run_id: str, layer9_dir: Path) -> dict:
    errors   = []
    warnings = []

    # ── Check 1: verification_report.json ────────────────────────────────────
    vr_path = layer9_dir / "verification_report.json"
    if not vr_path.exists():
        return {
            "run_id":            run_id,
            "passed":            False,
            "status":            "failed",
            "failure_reason":    "verification_report.json missing",
            "errors":            ["verification_report.json not found."],
            "warnings":          [],
            "ready_for_layer_10": False,
        }

    vr = json.loads(vr_path.read_text())

    # ── Check 2: verified_script.md ───────────────────────────────────────────
    vs_path = layer9_dir / "verified_script.md"
    if not vs_path.exists() or vs_path.stat().st_size < 100:
        errors.append("verified_script.md missing or too small.")

    # ── Check 3: layer9_manifest.json ─────────────────────────────────────────
    if not (layer9_dir / "layer9_manifest.json").exists():
        errors.append("layer9_manifest.json missing.")

    # ── Check 4: final_recommendation == 'blocked' ────────────────────────────
    final_status = vr.get("summary", {}).get("final_status", "")
    if final_status == "blocked":
        errors.append(f"Verification result is 'blocked'. Critical issues must be resolved.")

    # ── Check 5 (soft): unapplied patches ────────────────────────────────────
    patch_path = layer9_dir / "correction_patch.json"
    if patch_path.exists():
        patch = json.loads(patch_path.read_text())
        if patch.get("patch_required") and not patch.get("auto_patch_safe"):
            warnings.append(f"Correction patch requires manual review ({patch.get('patch_count', 0)} patches).")

    # ── Check 6 (soft): source attribution ───────────────────────────────────
    attr_path = layer9_dir / "source_attribution_report.json"
    if attr_path.exists():
        attr = json.loads(attr_path.read_text())
        if attr.get("missing_from_list", 0) > 0:
            warnings.append(f"Source attribution: {attr['missing_from_list']} sources used but not listed.")

    # ── Check 7 (soft): metadata safety errors ───────────────────────────────
    meta_path = layer9_dir / "metadata_safety_report.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("errors"):
            warnings.append(f"Metadata safety errors: {meta['errors'][:1]}")

    passed            = len(errors) == 0
    ready_for_layer_10 = passed and final_status not in ("blocked", "requires_revision")

    return {
        "run_id":             run_id,
        "passed":             passed,
        "status":             "passed" if passed else "failed",
        "failure_reason":     errors[0] if errors else None,
        "errors":             errors,
        "warnings":           warnings,
        "ready_for_layer_10": ready_for_layer_10,
        "final_status":       final_status,
        "risk_level":         vr.get("summary", {}).get("overall_risk_level", ""),
        "risk_score":         vr.get("summary", {}).get("risk_score", 0),
        "critical_issues":    vr.get("summary", {}).get("critical_issue_count", 0),
        "high_issues":        vr.get("summary", {}).get("high_issue_count", 0),
        "medium_issues":      vr.get("summary", {}).get("medium_issue_count", 0),
    }


def write_report(run_id: str, report: dict, layer9_dir: Path) -> Path:
    path = layer9_dir / "layer9_validation_report.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return path
