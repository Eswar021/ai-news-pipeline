"""
Layer 5 — Module 12: Layer 5 Validation Gate

Validates the lean Layer 5 outputs before handing off to Layer 6.
"""

import json
from pathlib import Path

_SUPPORTED_FORMATS = {"roundup", "deep_dive", "evergreen", "comparison", "follow_up"}


def validate(run_id: str, layer5_dir: Path) -> dict:
    errors = []
    warnings = []

    brief_path = layer5_dir / "selected_video_brief.json"
    decision_path = layer5_dir / "editorial_decision.json"
    assessments_path = layer5_dir / "story_editorial_assessments.json"

    for required_path, label in (
        (brief_path, "selected_video_brief.json"),
        (decision_path, "editorial_decision.json"),
        (assessments_path, "story_editorial_assessments.json"),
    ):
        if not required_path.exists():
            return {
                "run_id": run_id,
                "passed": False,
                "status": "failed",
                "failure_reason": f"{label} missing",
                "errors": [f"{label} not found in layer_5 output."],
                "warnings": [],
                "ready_for_layer_6": False,
            }

    with open(brief_path) as f:
        brief = json.load(f)
    with open(decision_path) as f:
        decision = json.load(f)

    selected_format = brief.get("selected_format")
    create_video = decision.get("decision") == "create_video"

    if create_video and selected_format not in _SUPPORTED_FORMATS:
        errors.append(
            f"Selected format '{selected_format}' is not in supported formats {_SUPPORTED_FORMATS}."
        )

    evidence = brief.get("evidence_boundaries", {})
    safe_ids = set(evidence.get("safe_claim_ids", []))
    dnu_ids = set(evidence.get("do_not_use_claim_ids", []))
    overlap = safe_ids & dnu_ids
    if overlap:
        errors.append(
            f"{len(overlap)} do_not_use claim(s) found in safe_claim_ids: {list(overlap)[:3]}"
        )

    if create_video and not safe_ids:
        errors.append("decision=create_video but evidence_boundaries.safe_claim_ids is empty.")

    selected_story_ids = list(decision.get("selected_story_ids") or [])
    primary_story_id = decision.get("primary_story_id")
    if create_video and not selected_story_ids and primary_story_id:
        selected_story_ids = [primary_story_id]
    if create_video and not selected_story_ids:
        errors.append("decision=create_video but no selected story IDs were recorded.")

    cautious_ids = evidence.get("cautious_claim_ids", [])
    if cautious_ids:
        warnings.append(
            f"{len(cautious_ids)} cautious claim(s) present; Layer 6 must preserve qualifier guidance."
        )

    gap_ids = evidence.get("evidence_gap_ids", [])
    if gap_ids:
        warnings.append(f"{len(gap_ids)} evidence gap(s) present; Layer 6 should note these.")

    rejected_path = layer5_dir / "rejected_editorial_candidates.jsonl"
    if rejected_path.exists():
        with open(rejected_path) as f:
            rejected = [json.loads(line) for line in f if line.strip()]
        missing_reason = [r for r in rejected if not r.get("rejection_reason")]
        if missing_reason:
            warnings.append(
                f"{len(missing_reason)} rejected candidate(s) have no rejection_reason."
            )

    content = brief.get("content_direction", {})
    promise = content.get("viewer_promise", "") or content.get("episode_theme", "")
    if create_video and len(promise) < 20:
        warnings.append(
            f"viewer_promise is very short ({len(promise)} chars); Layer 6 may need to expand editorial direction."
        )

    passed = len(errors) == 0
    ready_for_layer_6 = passed and create_video

    return {
        "run_id": run_id,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "failure_reason": errors[0] if errors else None,
        "errors": errors,
        "warnings": warnings,
        "ready_for_layer_6": ready_for_layer_6,
        "checks_run": 8,
        "checks_passed": 8 - len(errors),
        "selected_format": selected_format,
        "selected_story_count": len(selected_story_ids),
    }


def write_report(run_id: str, report: dict, layer5_dir: Path) -> Path:
    path = layer5_dir / "layer5_validation_report.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return path
