"""
Layer 5 — Module 12: Layer 5 Validation Gate

Validates Layer 5 output before handing off to Layer 6.

Hard failures (block Layer 6):
  1. selected_video_brief.json missing
  2. selected format not in enabled formats
  3. do_not_use claims present in safe_claim_ids
  4. decision=create_video but no safe_claim_ids

Soft warnings (pass with warning):
  5. cautious_claim_ids present (Layer 6 must preserve qualifiers)
  6. evidence_gap_ids present
  7. rejected_candidates missing rejection reasons
  8. viewer_promise too short (< 20 chars)

Key functions:
    validate(run_id, layer5_dir) → report dict
    write_report(run_id, report, layer5_dir) → path
"""

import json
from pathlib import Path

_SUPPORTED_FORMATS = {"roundup", "deep_dive", "evergreen", "comparison", "follow_up"}


def validate(run_id: str, layer5_dir: Path) -> dict:
    errors   = []
    warnings = []

    # ── Check 1: selected_video_brief.json exists (hard fail) ────────────────
    brief_path = layer5_dir / "selected_video_brief.json"
    if not brief_path.exists():
        return {
            "run_id":           run_id,
            "passed":           False,
            "status":           "failed",
            "failure_reason":   "selected_video_brief.json missing",
            "errors":           ["selected_video_brief.json not found in layer_5 output."],
            "warnings":         [],
            "ready_for_layer_6": False,
        }

    with open(brief_path) as f:
        brief = json.load(f)

    with open(layer5_dir / "layer5_manifest.json") as f:
        manifest = json.load(f)

    # ── Check 2: selected format is enabled (hard fail) ──────────────────────
    selected_format = brief.get("selected_format", "")
    decision   = manifest.get("decision", {})
    create_vid = decision.get("create_video", False)
    if create_vid and selected_format not in _SUPPORTED_FORMATS:
        errors.append(
            f"Selected format '{selected_format}' is not in supported formats {_SUPPORTED_FORMATS}."
        )

    # ── Check 3: no do_not_use claims in safe_claim_ids (hard fail) ──────────
    evidence = brief.get("evidence_boundaries", {})
    safe_ids  = set(evidence.get("safe_claim_ids", []))
    dnu_ids   = set(evidence.get("do_not_use_claim_ids", []))
    overlap   = safe_ids & dnu_ids
    if overlap:
        errors.append(
            f"{len(overlap)} do_not_use claim(s) found in safe_claim_ids: {list(overlap)[:3]}"
        )

    # ── Check 4: create_video requires safe_claim_ids ─────────────────────────
    if create_vid and not safe_ids:
        errors.append("decision=create_video but evidence_boundaries.safe_claim_ids is empty.")

    # ── Check 5: cautious claims warning ─────────────────────────────────────
    cautious_ids = evidence.get("cautious_claim_ids", [])
    if cautious_ids:
        warnings.append(
            f"{len(cautious_ids)} cautious claim(s) present; "
            "Layer 6 must preserve qualifier guidance."
        )

    # ── Check 6: evidence gaps ───────────────────────────────────────────────
    gap_ids = evidence.get("evidence_gap_ids", [])
    if gap_ids:
        warnings.append(
            f"{len(gap_ids)} evidence gap(s) present; Layer 6 should note these."
        )

    # ── Check 7: rejected candidates have reasons ─────────────────────────────
    rejected_path = layer5_dir / "rejected_editorial_candidates.jsonl"
    if rejected_path.exists():
        with open(rejected_path) as f:
            rejected = [json.loads(l) for l in f if l.strip()]
        missing_reason = [r for r in rejected if not r.get("rejection_reason")]
        if missing_reason:
            warnings.append(
                f"{len(missing_reason)} rejected candidate(s) have no rejection_reason."
            )

    # ── Check 8: viewer_promise not too short ─────────────────────────────────
    content = brief.get("content_direction", {})
    promise = content.get("viewer_promise", "") or content.get("episode_theme", "")
    if len(promise) < 20:
        warnings.append(
            f"viewer_promise is very short ({len(promise)} chars); "
            "Layer 6 may need to expand editorial direction."
        )

    passed          = len(errors) == 0
    ready_for_layer_6 = passed and create_vid

    return {
        "run_id":             run_id,
        "passed":             passed,
        "status":             "passed" if passed else "failed",
        "failure_reason":     errors[0] if errors else None,
        "errors":             errors,
        "warnings":           warnings,
        "ready_for_layer_6":  ready_for_layer_6,
        "checks_run":         8,
        "checks_passed":      8 - len(errors),
        "selected_format":    selected_format,
        "selected_story_count": len(decision.get("selected_story_ids", [])),
    }


def write_report(run_id: str, report: dict, layer5_dir: Path) -> Path:
    path = layer5_dir / "layer5_validation_report.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return path
