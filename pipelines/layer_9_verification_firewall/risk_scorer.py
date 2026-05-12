"""
Layer 9 — Module 13: Risk Scorer + Severity Classifier

Aggregates all verification issues from all modules and assigns:
  - overall_risk_level: low | medium | high | critical
  - final_recommendation: approved | approved_with_warnings | requires_revision | blocked

Approval gate rules (inline):
  approved              : 0 critical, 0 high, 0 medium
  approved_with_warnings: 0 critical, 0 high, ≤5 medium
  requires_revision     : 0 critical, ≥1 high (or >5 medium)
  blocked               : ≥1 critical

Returns:
    dict with risk_score, final_recommendation, issue_list, priority_fixes
"""

_SEVERITY_WEIGHTS = {"critical": 100, "high": 10, "medium": 3, "warning": 1, "info": 0}


def _collect_issues(
    coverage_result,
    traceability_result,
    support_results,
    overclaim_result,
    cautious_result,
    leakage_result,
    contradiction_result,
    repetition_result,
    metadata_result,
    attribution_result,
) -> list:
    issues = []

    # Coverage — uncovered factual sentences
    for r in coverage_result.get("uncovered_list", []):
        issues.append({
            "source":   "sentence_coverage",
            "severity": r.get("severity", "high"),
            "message":  f"Uncovered sentence: {r.get('sentence_text', '')[:60]}",
            "sentence_id": r.get("sentence_id", ""),
        })
    for r in coverage_result.get("rejected_list", []):
        issues.append({
            "source":   "sentence_coverage",
            "severity": "critical",
            "message":  f"Rejected claim in sentence: {r.get('sentence_id', '')}",
            "sentence_id": r.get("sentence_id", ""),
        })

    # Traceability
    for r in traceability_result.get("missing_list", []):
        issues.append({
            "source":   "claim_traceability",
            "severity": "critical",
            "message":  f"Claim {r['claim_id']} missing from verified claims.",
        })
    for r in traceability_result.get("broken_list", []):
        issues.append({
            "source":   "claim_traceability",
            "severity": "medium",
            "message":  f"Claim {r['claim_id']} has broken source spans.",
        })

    # LLM support verification
    for r in support_results:
        if r.get("support_status") in ("overclaim", "unsupported", "verification_error"):
            issues.append({
                "source":      "sentence_support",
                "severity":    r.get("severity", "medium"),
                "message":     f"{r['support_status']}: {r.get('sentence_text', '')[:60]}",
                "sentence_id": r.get("sentence_id", ""),
                "issue":       r.get("issue", ""),
                "fix":         r.get("recommended_fix", ""),
            })

    # Overclaims (pattern-based)
    for oc in overclaim_result.get("overclaims", []):
        issues.append({
            "source":      "overclaim_detector",
            "severity":    oc.get("severity", "medium"),
            "message":     f"{oc['overclaim_type']}: '{oc.get('matched_text', '')}' in {oc.get('section_key', '')}",
            "sentence_id": oc.get("sentence_id", ""),
        })

    # Cautious language
    for iss in cautious_result.get("issues", []):
        issues.append({
            "source":      "cautious_language",
            "severity":    iss.get("severity", "high"),
            "message":     f"Cautious claim overstated: {iss.get('sentence_text', '')[:60]}",
            "sentence_id": iss.get("sentence_id", ""),
        })

    # Rejected claim leakage
    for leak in leakage_result.get("leaks", []):
        issues.append({
            "source":   "rejected_claim_leakage",
            "severity": "critical",
            "message":  f"Leak: {leak.get('leak_type', '')} — '{leak.get('matched_text', '')[:40]}'",
        })

    # Contradiction handler (informational only — never block)
    # Don't add to issues list since is_informational = True

    # Repetition safety
    for issue in repetition_result.get("issues", []):
        issues.append({
            "source": "repetition_safety",
            "severity": issue.get("severity", "medium"),
            "message": issue.get("message", "Repetition safety issue."),
        })
    for warning in repetition_result.get("warnings", []):
        issues.append({
            "source": "repetition_safety",
            "severity": "warning",
            "message": warning,
        })

    # Metadata safety
    for e in metadata_result.get("errors", []):
        issues.append({
            "source":   "metadata_safety",
            "severity": "high",
            "message":  e,
        })
    for w in metadata_result.get("warnings", []):
        issues.append({
            "source":   "metadata_safety",
            "severity": "medium",
            "message":  w,
        })

    # Source attribution
    for e in attribution_result.get("errors", []):
        issues.append({
            "source":   "source_attribution",
            "severity": "high",
            "message":  e,
        })
    for w in attribution_result.get("warnings", []):
        issues.append({
            "source":   "source_attribution",
            "severity": "medium",
            "message":  w,
        })

    return issues


def score(
    coverage_result,
    traceability_result,
    support_results,
    overclaim_result,
    cautious_result,
    leakage_result,
    contradiction_result,
    repetition_result,
    metadata_result,
    attribution_result,
) -> dict:

    all_issues = _collect_issues(
        coverage_result, traceability_result, support_results,
        overclaim_result, cautious_result, leakage_result,
        contradiction_result, repetition_result, metadata_result, attribution_result,
    )

    critical = [i for i in all_issues if i["severity"] == "critical"]
    high     = [i for i in all_issues if i["severity"] == "high"]
    medium   = [i for i in all_issues if i["severity"] == "medium"]
    warning  = [i for i in all_issues if i["severity"] in ("warning", "info")]

    risk_score = (
        len(critical) * _SEVERITY_WEIGHTS["critical"] +
        len(high)     * _SEVERITY_WEIGHTS["high"] +
        len(medium)   * _SEVERITY_WEIGHTS["medium"] +
        len(warning)  * _SEVERITY_WEIGHTS["warning"]
    )

    # Approval gate
    if critical:
        recommendation    = "blocked"
        overall_risk      = "critical"
    elif high:
        recommendation    = "requires_revision"
        overall_risk      = "high"
    elif len(medium) > 5:
        recommendation    = "requires_revision"
        overall_risk      = "high"
    elif medium:
        recommendation    = "approved_with_warnings"
        overall_risk      = "medium"
    elif warning:
        recommendation    = "approved_with_warnings"
        overall_risk      = "low"
    else:
        recommendation    = "approved"
        overall_risk      = "low"

    # Priority fixes
    priority_fixes = []
    for i in (critical + high + medium)[:10]:
        fix_entry = {
            "source":   i["source"],
            "severity": i["severity"],
            "message":  i["message"],
        }
        if i.get("fix"):
            fix_entry["recommended_fix"] = i["fix"]
        if i.get("sentence_id"):
            fix_entry["sentence_id"] = i["sentence_id"]
        priority_fixes.append(fix_entry)

    return {
        "overall_risk_level":    overall_risk,
        "risk_score":            risk_score,
        "critical_count":        len(critical),
        "high_count":            len(high),
        "medium_count":          len(medium),
        "warning_count":         len(warning),
        "total_issues":          len(all_issues),
        "final_recommendation":  recommendation,
        "all_issues":            all_issues,
        "priority_fixes":        priority_fixes,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_9_verification_firewall.context_loader import load
    from pipelines.layer_9_verification_firewall.sentence_classification_validator import classify
    from pipelines.layer_9_verification_firewall.sentence_claim_coverage_checker import check as check_coverage
    from pipelines.layer_9_verification_firewall.claim_source_traceability_checker import check as check_traceability
    from pipelines.layer_9_verification_firewall.sentence_support_verifier import verify as verify_support
    from pipelines.layer_9_verification_firewall.overclaim_detector import detect as detect_overclaims
    from pipelines.layer_9_verification_firewall.cautious_language_verifier import verify as verify_cautious
    from pipelines.layer_9_verification_firewall.rejected_claim_leakage_detector import detect as detect_leakage
    from pipelines.layer_9_verification_firewall.contradiction_evidence_gap_handler import handle as handle_contradictions
    from pipelines.layer_9_verification_firewall.repetition_safety_checker import check as check_repetition
    from pipelines.layer_9_verification_firewall.metadata_safety_checker import check as check_metadata
    from pipelines.layer_9_verification_firewall.source_attribution_checker import check as check_attribution

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")
    classified    = classify(ctx)
    coverage      = check_coverage(classified, ctx)
    traceability  = check_traceability(coverage, ctx)
    support       = verify_support(classified, ctx)
    overclaims    = detect_overclaims(classified, ctx)
    cautious      = verify_cautious(classified, ctx)
    leakage       = detect_leakage(coverage, support, ctx)
    contradiction = handle_contradictions(ctx)
    repetition    = check_repetition(ctx)
    metadata      = check_metadata(ctx)
    attribution   = check_attribution(ctx)

    result = score(
        coverage, traceability, support, overclaims,
        cautious, leakage, contradiction, repetition, metadata, attribution
    )

    print(f"Risk level       : {result['overall_risk_level']}")
    print(f"Risk score       : {result['risk_score']}")
    print(f"Critical         : {result['critical_count']}")
    print(f"High             : {result['high_count']}")
    print(f"Medium           : {result['medium_count']}")
    print(f"Warnings         : {result['warning_count']}")
    print(f"Recommendation   : {result['final_recommendation']}")
    print(f"\nPriority fixes ({len(result['priority_fixes'])}):")
    for fix in result["priority_fixes"]:
        print(f"  [{fix['severity']}] [{fix['source']}] {fix['message'][:70]}")
