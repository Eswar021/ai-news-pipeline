"""
Build the durable revision package for Layer 9 outcomes.
"""

from __future__ import annotations

from collections import Counter


def build(
    *,
    risk_result: dict,
    patch_result: dict,
    structure_result: dict,
    support_results: list[dict],
    coverage_result: dict,
    editorial_analysis_result: dict,
) -> dict:
    final_status = risk_result.get("final_recommendation", "approved")
    issue_counts = Counter(issue.get("source", "unknown") for issue in risk_result.get("all_issues", []))
    per_sentence_items = []

    patch_by_sentence = {
        patch.get("sentence_id", ""): patch
        for patch in patch_result.get("patches", [])
        if patch.get("sentence_id")
    }

    for sentence in support_results:
        sentence_id = sentence.get("sentence_id", "")
        if sentence.get("support_status") not in ("overclaim", "unsupported", "verification_error"):
            continue
        patch = patch_by_sentence.get(sentence_id, {})
        per_sentence_items.append({
            "sentence_id": sentence_id,
            "section_key": sentence.get("section_key", ""),
            "issue_class": "sentence_support",
            "severity": sentence.get("severity", "medium"),
            "sentence_text": sentence.get("sentence_text", ""),
            "issue": sentence.get("issue"),
            "recommended_fix": sentence.get("recommended_fix"),
            "auto_patch_safe": patch.get("auto_patch_safe", False),
        })

    for sentence in coverage_result.get("uncovered_list", []):
        per_sentence_items.append({
            "sentence_id": sentence.get("sentence_id", ""),
            "section_key": sentence.get("section_key", ""),
            "issue_class": "sentence_coverage",
            "severity": sentence.get("severity", "high"),
            "sentence_text": sentence.get("sentence_text", ""),
            "issue": sentence.get("reason", ""),
            "recommended_fix": None,
            "auto_patch_safe": False,
        })

    for issue in editorial_analysis_result.get("issues", []):
        per_sentence_items.append({
            "sentence_id": issue.get("sentence_id", ""),
            "section_key": issue.get("section_key", ""),
            "issue_class": "editorial_analysis",
            "severity": issue.get("severity", "high"),
            "sentence_text": issue.get("sentence_text", ""),
            "issue": issue.get("message", ""),
            "recommended_fix": None,
            "auto_patch_safe": False,
        })

    safe_auto_patches = [patch for patch in patch_result.get("patches", []) if patch.get("auto_patch_safe")]
    manual_review_items = [patch for patch in patch_result.get("patches", []) if not patch.get("auto_patch_safe")]

    return {
        "final_status": final_status,
        "revision_required": final_status in {"revisable", "blocked"},
        "issue_summary_by_class": dict(issue_counts),
        "issue_counts": {
            "critical": risk_result.get("critical_count", 0),
            "high": risk_result.get("high_count", 0),
            "medium": risk_result.get("medium_count", 0),
            "warning": risk_result.get("warning_count", 0),
            "total": risk_result.get("total_issues", 0),
        },
        "per_sentence_revision_items": per_sentence_items,
        "safe_auto_patch_items": safe_auto_patches,
        "manual_review_items": manual_review_items,
        "rerun_guidance": {
            "recommended_rerun_layers": [8, 9],
            "recommended_rerun_command": "python pipeline.py --run-id <run_id> --layers 8,9",
            "notes": [
                "Fix narration generation issues first, then rerun Layer 8 and Layer 9 on the same run.",
                "Revision-needed outcomes should not proceed to Layer 10.",
            ],
        },
        "structure_summary": {
            "status": structure_result.get("status", "unknown"),
            "warnings": structure_result.get("warnings", []),
        },
    }
