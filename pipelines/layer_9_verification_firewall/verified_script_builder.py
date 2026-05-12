"""
Layer 9 — Module 15: Verified Script Builder

Builds verified_script.md from Layer 8's script.md.

Modes (determined by final_recommendation):
  approved                → copy script as-is (verified_script.md = script.md)
  approved_with_warnings  → apply safe auto-patches if patch.auto_patch_safe=True
  requires_revision       → do not create verified script; return not_created
  blocked                 → do not create verified script; return not_created

Auto-patch applies sentence-level replacements by exact text match in script.

Returns:
    dict with status, verified_script_text, patches_applied, remaining_warnings
"""


_INSTRUCTION_STARTS = (
    "remove ", "add ", "rewrite ", "delete ", "insert ", "provide ",
    "change ", "replace the", "consider ", "revise ",
)


def _is_instruction_text(text: str) -> bool:
    lower = text.lower().strip()
    return any(lower.startswith(s) for s in _INSTRUCTION_STARTS)


def _apply_patches(script_text: str, patches: list) -> tuple[str, list]:
    """Apply patches by replacing original_text with replacement_text in script."""
    applied = []
    for p in patches:
        if not p.get("auto_patch_safe"):
            continue
        orig = p.get("original_text", "").strip()
        repl = p.get("replacement_text", "").strip()
        if not orig or not repl or repl == "(manual revision required)":
            continue
        if _is_instruction_text(repl):
            continue  # skip LLM-generated instructions, not actual replacement text
        if orig in script_text:
            script_text = script_text.replace(orig, repl, 1)
            applied.append(p["patch_id"])
    return script_text, applied


def build(
    risk_result: dict,
    patch_result: dict,
    ctx: dict,
    layer8_dir,
) -> dict:
    recommendation = risk_result.get("final_recommendation", "approved")
    patches        = patch_result.get("patches", [])
    auto_safe      = patch_result.get("auto_patch_safe", False)

    if recommendation in ("requires_revision", "blocked"):
        return {
            "status":               "not_created",
            "verified_script_text": None,
            "patches_applied":      [],
            "patches_applied_count": 0,
            "remaining_warnings":   risk_result.get("total_issues", 0),
            "ready_for_publish_review": False,
            "reason":               recommendation,
        }

    # Load original script.md
    script_md_path = layer8_dir / "script.md"
    script_text    = script_md_path.read_text(encoding="utf-8")

    applied_ids = []
    if recommendation == "approved_with_warnings" and auto_safe and patches:
        script_text, applied_ids = _apply_patches(script_text, patches)

    remaining = risk_result.get("medium_count", 0) + risk_result.get("warning_count", 0) - len(applied_ids)
    remaining = max(0, remaining)

    return {
        "status":               "created",
        "verified_script_text": script_text,
        "patches_applied":      applied_ids,
        "patches_applied_count": len(applied_ids),
        "remaining_warnings":   remaining,
        "ready_for_publish_review": True,
        "reason":               recommendation,
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
    from pipelines.layer_9_verification_firewall.risk_scorer import score
    from pipelines.layer_9_verification_firewall.correction_patch_generator import generate

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
    risk          = score(coverage, traceability, support, overclaims,
                         cautious, leakage, contradiction, repetition, metadata, attribution)
    patch         = generate(risk, ctx)

    result = build(risk, patch, ctx, base / "layer_8")

    print(f"Status           : {result['status']}")
    print(f"Patches applied  : {result['patches_applied_count']} {result['patches_applied']}")
    print(f"Remaining warns  : {result['remaining_warnings']}")
    print(f"Ready for review : {result['ready_for_publish_review']}")
    if result["verified_script_text"]:
        print(f"\nVerified script (first 500 chars):")
        print(result["verified_script_text"][:500])
