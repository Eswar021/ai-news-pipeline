from __future__ import annotations

from collections import Counter, defaultdict


BLOCKING_SUPPORT_STATUSES = {"unsupported"}
REVISION_SUPPORT_STATUSES = {"overclaim", "verification_error", "not_verified"}
BLOCKING_SEVERITIES = {"medium", "high"}


def build_verification_decision(
    *,
    script_package: dict,
    sentence_map: list[dict],
    sentence_verifications: list[dict],
    rule_checks: dict,
) -> dict:
    support_summary = _support_summary(sentence_verifications)
    blocking_issues = []
    revision_issues = []

    for check in rule_checks.get("errors", []):
        blocking_issues.append(_rule_issue(check, "blocked"))
    for check in rule_checks.get("warnings", []):
        revision_issues.append(_rule_issue(check, "needs_revision"))

    for verification in sentence_verifications:
        status = verification.get("support_status", "")
        severity = verification.get("severity", "")
        if status in BLOCKING_SUPPORT_STATUSES and severity in BLOCKING_SEVERITIES:
            blocking_issues.append(_support_issue(verification, "blocked"))
        elif status in BLOCKING_SUPPORT_STATUSES or status in REVISION_SUPPORT_STATUSES:
            revision_issues.append(_support_issue(verification, "needs_revision"))

    if blocking_issues:
        status = "blocked"
        reason = f"{len(blocking_issues)} blocking issue(s) found."
    elif revision_issues:
        status = "needs_revision"
        reason = f"{len(revision_issues)} revision issue(s) found."
    else:
        status = "approved"
        reason = "Script passed rule checks and support verification."

    revision_package = _build_revision_package(status, blocking_issues, revision_issues)
    final_publish_package = _build_final_publish_package(status, script_package)
    return {
        "status": status,
        "decision": {
            "status": status,
            "approved": status == "approved",
            "ready_for_layer_9": status == "approved",
            "reason": reason,
            "blocking_issue_count": len(blocking_issues),
            "revision_issue_count": len(revision_issues),
        },
        "support_summary": support_summary,
        "revision_package": revision_package,
        "final_publish_package": final_publish_package,
        "layer9_handoff": {
            "ready_for_layer_9": status == "approved",
            "status": status,
            "package_type": "roundup_verification",
            "selected_format": script_package.get("video", {}).get("selected_format", ""),
            "approved_script_available": status == "approved",
            "revision_required": status != "approved",
        },
    }


def _support_summary(sentence_verifications: list[dict]) -> dict:
    status_counts = Counter(item.get("support_status", "unknown") for item in sentence_verifications)
    severity_counts = Counter(item.get("severity", "unknown") for item in sentence_verifications)
    issue_sections = defaultdict(int)
    for item in sentence_verifications:
        if item.get("support_status") in BLOCKING_SUPPORT_STATUSES | REVISION_SUPPORT_STATUSES:
            issue_sections[item.get("section_id", "")] += 1
    return {
        "sentence_count": len(sentence_verifications),
        "status_counts": dict(status_counts),
        "severity_counts": dict(severity_counts),
        "issue_sections": dict(issue_sections),
    }


def _rule_issue(check: dict, decision_status: str) -> dict:
    return {
        "issue_type": "rule_check",
        "decision_status": decision_status,
        "section_id": "",
        "sentence_id": "",
        "name": check.get("name", ""),
        "detail": check.get("detail", ""),
        "recommended_fix": _fix_for_rule(check),
    }


def _support_issue(verification: dict, decision_status: str) -> dict:
    return {
        "issue_type": "sentence_support",
        "decision_status": decision_status,
        "section_id": verification.get("section_id", ""),
        "sentence_id": verification.get("sentence_id", ""),
        "sentence_text": verification.get("sentence_text", ""),
        "support_status": verification.get("support_status", ""),
        "severity": verification.get("severity", ""),
        "issue": verification.get("issue"),
        "recommended_fix": verification.get("recommended_fix") or "Revise the sentence to match the cited facts.",
    }


def _build_revision_package(status: str, blocking_issues: list[dict], revision_issues: list[dict]) -> dict:
    if status == "approved":
        return {
            "required": False,
            "issues": [],
            "affected_sections": [],
            "rerun_guidance": "",
        }
    issues = blocking_issues + revision_issues
    affected_sections = sorted({issue.get("section_id", "") for issue in issues if issue.get("section_id")})
    return {
        "required": True,
        "issues": issues,
        "affected_sections": affected_sections,
        "rerun_guidance": (
            "Revise the affected L7 sections or prompts, rerun Layer 7, then rerun Layer 8. "
            "Do not carry this package into Layer 9 until status is approved."
        ),
    }


def _build_final_publish_package(status: str, script_package: dict) -> dict:
    if status != "approved":
        return {}
    return {
        "run_id": script_package["run_id"],
        "package_type": "final_publish_package",
        "selected_format": script_package.get("video", {}).get("selected_format", ""),
        "video": script_package.get("video", {}),
        "narration_text": script_package.get("full_script", {}).get("narration_text", ""),
        "youtube_metadata": script_package.get("youtube_metadata", {}),
        "visual_notes": script_package.get("visual_notes", []),
        "source_index": script_package.get("source_index", []),
        "evidence_boundaries": script_package.get("evidence_boundaries", {}),
        "evidence_usage": script_package.get("evidence_usage", {}),
    }


def _fix_for_rule(check: dict) -> str:
    name = check.get("name", "")
    if name == "required_fact_usage":
        return "Rerun or adjust L7 so every required fact appears in narration."
    if name == "cautious_language":
        return "Add explicit attribution or careful qualifier language around cautious facts."
    if name == "duration":
        return "Adjust L7 section length guidance and rerun L7."
    if name == "visual_direction_leak":
        return "Remove editor/visual directions from spoken narration."
    return "Fix the rule-check issue and rerun L8."
