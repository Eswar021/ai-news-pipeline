"""
Layer 9 — Module 14: Correction Patch Generator

Generates a structured correction patch from risk_scorer issues.

For each fixable issue (severity medium or higher, with a sentence_id):
  - original_text:    the current sentence from the script
  - replacement_text: recommended fix (from LLM if available, else generic)
  - reason:           why the change is needed
  - severity:         issue severity
  - auto_patch_safe:  True for medium issues, False for high/critical

Patch is auto-applicable only for medium-severity LLM-suggested fixes.
High/critical require human review.

Returns:
    dict with patch_required, auto_patch_safe, patches list
"""


def generate(risk_result: dict, ctx: dict) -> dict:
    sentence_map = ctx["sentence_map"]
    issues       = risk_result.get("all_issues", [])

    patches = []
    patch_id = 1

    for issue in issues:
        sev = issue.get("severity", "info")
        if sev not in ("critical", "high", "medium"):
            continue

        sid = issue.get("sentence_id", "")
        if not sid:
            continue  # no sentence target, can't auto-patch

        sent = sentence_map.get(sid, {})
        original_text = sent.get("sentence_text", "")
        if not original_text:
            continue

        replacement = issue.get("fix") or issue.get("recommended_fix") or ""

        # Severity determines if auto-patch is safe
        auto_safe = sev == "medium" and bool(replacement)

        patch = {
            "patch_id":        f"patch_{patch_id:03d}",
            "target_type":     "sentence",
            "sentence_id":     sid,
            "section_key":     sent.get("section_key", ""),
            "issue_type":      issue.get("source", ""),
            "original_text":   original_text,
            "replacement_text": replacement or "(manual revision required)",
            "reason":          issue.get("message", ""),
            "severity":        sev,
            "auto_patch_safe": auto_safe,
        }
        patches.append(patch)
        patch_id += 1

    patch_required = len(patches) > 0
    # auto_patch_safe at patch level: only if ALL patches are safe
    all_safe = all(p["auto_patch_safe"] for p in patches) if patches else False

    return {
        "patch_required":   patch_required,
        "auto_patch_safe":  all_safe,
        "patch_count":      len(patches),
        "patches":          patches,
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
    from pipelines.layer_9_verification_firewall.metadata_safety_checker import check as check_metadata
    from pipelines.layer_9_verification_firewall.source_attribution_checker import check as check_attribution
    from pipelines.layer_9_verification_firewall.risk_scorer import score

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
    metadata      = check_metadata(ctx)
    attribution   = check_attribution(ctx)
    risk          = score(coverage, traceability, support, overclaims,
                         cautious, leakage, contradiction, metadata, attribution)

    result = generate(risk, ctx)
    print(f"Patch required   : {result['patch_required']}")
    print(f"Auto patch safe  : {result['auto_patch_safe']}")
    print(f"Patch count      : {result['patch_count']}")
    for p in result["patches"]:
        print(f"\n  [{p['patch_id']}] [{p['severity']}] [{p['section_key']}]")
        print(f"  Original    : {p['original_text'][:70]}")
        print(f"  Replacement : {p['replacement_text'][:70]}")
        print(f"  Reason      : {p['reason'][:70]}")
