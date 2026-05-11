"""
Layer 7 — Module 15: Layer 7 Validation Gate

Validates Layer 7 output before handing off to Layer 8.

Hard failures (block Layer 8):
  1. script_writer_brief.json missing
  2. video_plan.json missing
  3. section count < 2
  4. DNU claim IDs appear in required section claims
  5. boundary_review failed (status == "failed")
  6. ready_for_layer_8 is False in boundary review

Soft warnings (pass with warning):
  7. title count < 4
  8. no visual suggestions
  9. hook type missing

Key functions:
    validate(run_id, layer7_dir) → report dict
    write_report(run_id, report, layer7_dir) → path
"""

import json
from pathlib import Path

_MIN_SECTION_COUNT = 2
_MIN_TITLE_COUNT   = 4


def validate(run_id: str, layer7_dir: Path) -> dict:
    errors   = []
    warnings = []

    # ── Check 1 & 2: Required files exist ────────────────────────────────────
    brief_path = layer7_dir / "script_writer_brief.json"
    plan_path  = layer7_dir / "video_plan.json"

    if not brief_path.exists():
        return {
            "run_id":             run_id,
            "passed":             False,
            "status":             "failed",
            "failure_reason":     "script_writer_brief.json missing",
            "errors":             ["script_writer_brief.json not found in layer_7 output."],
            "warnings":           [],
            "ready_for_layer_8":  False,
        }

    if not plan_path.exists():
        errors.append("video_plan.json missing from layer_7 output.")

    with open(brief_path) as f:
        brief = json.load(f)
    with open(layer7_dir / "section_plan.json") as f:
        section_data = json.load(f)
    with open(layer7_dir / "evidence_boundary_review.json") as f:
        br = json.load(f)
    with open(layer7_dir / "title_thumbnail_plan.json") as f:
        tt = json.load(f)
    with open(layer7_dir / "visual_plan.json") as f:
        vis = json.load(f)
    with open(layer7_dir / "hook_plan.json") as f:
        hook = json.load(f)

    # ── Check 3: Section count ────────────────────────────────────────────────
    sections = section_data.get("sections", [])
    if len(sections) < _MIN_SECTION_COUNT:
        errors.append(f"Section count {len(sections)} is below minimum {_MIN_SECTION_COUNT}.")

    # ── Check 4: DNU in required claims ──────────────────────────────────────
    dnu_found = br.get("do_not_use_claim_ids_found", [])
    if dnu_found:
        errors.append(
            f"{len(dnu_found)} do-not-use claim(s) found in plan: {dnu_found[:3]}"
        )

    # ── Check 5 & 6: Boundary review status ──────────────────────────────────
    if br.get("status") == "failed":
        errors.append("Evidence boundary review failed. Layer 8 blocked.")
    if not br.get("passed", False):
        errors.append("boundary_review.passed is False — Layer 8 blocked.")

    # ── Check 7 (soft): Title count ───────────────────────────────────────────
    title_count = len(tt.get("recommended_title_angles", []))
    if title_count < _MIN_TITLE_COUNT:
        warnings.append(
            f"Only {title_count} title option(s); fewer than {_MIN_TITLE_COUNT} limits publishing flexibility."
        )

    # ── Check 8 (soft): Visual suggestions ───────────────────────────────────
    visual_count = vis.get("visual_count", 0)
    if visual_count == 0:
        warnings.append("No visual suggestions produced. Layer 8 will have no visual guidance.")

    # ── Check 9 (soft): Hook type ─────────────────────────────────────────────
    rec_hook = hook.get("recommended_hook", {})
    if not rec_hook.get("hook_type"):
        warnings.append("Hook plan missing hook_type. Layer 8 will have minimal hook guidance.")

    passed           = len(errors) == 0
    ready_for_layer_8 = passed

    return {
        "run_id":              run_id,
        "passed":              passed,
        "status":              "passed" if passed else "failed",
        "failure_reason":      errors[0] if errors else None,
        "errors":              errors,
        "warnings":            warnings,
        "ready_for_layer_8":   ready_for_layer_8,
        "checks_run":          9,
        "checks_passed":       9 - len(errors),
        "section_count":       len(sections),
        "title_option_count":  title_count,
        "visual_count":        visual_count,
        "boundary_status":     br.get("status", "unknown"),
    }


def write_report(run_id: str, report: dict, layer7_dir: Path) -> Path:
    path = layer7_dir / "layer7_validation_report.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return path
