"""
Layer 9 Orchestrator — Verification Firewall

Verifies the generated script from Layer 8 against all evidence sources.

Processing pipeline:
  1. context_loader              → load all inputs, build indexes
  2. script_structure_validator  → validate sections vs Layer 7 plan
  3. sentence_classification_validator → classify sentence types
  4. sentence_claim_coverage_checker   → sentence → claim coverage
  5. claim_source_traceability_checker → claim → source span check
  6. sentence_support_verifier         → LLM: sentence vs source spans
  7. overclaim_detector                → pattern-based overclaim scan
  8. cautious_language_verifier        → cautious claim language check
  9. rejected_claim_leakage_detector   → blocked claim/phrase check
  10. contradiction_evidence_gap_handler → informational gap report
  11. repetition_safety_checker        → published-memory repetition gate
  12. metadata_safety_checker          → title/thumbnail/description safety
  13. source_attribution_checker       → source list completeness
  14. risk_scorer                      → aggregate + final recommendation
  15. correction_patch_generator       → structured correction patches
  16. verified_script_builder          → build verified_script.md
  17. layer9_writer                    → write all outputs
  18. layer9_validation_gate           → validate output

Output:
    data/runs/{run_id}/layer_9/
      verification_report.json
      sentence_verification_results.jsonl
      unsupported_sentences.jsonl
      overclaim_report.json
      cautious_language_verification.json
      rejected_claim_leakage_report.json
      contradiction_handling_report.json
      repetition_safety_report.json
      metadata_safety_report.json
      source_attribution_report.json
      correction_patch.json
      verified_script.md
      verified_youtube_metadata.json
      final_publish_package.json
      layer9_manifest.json
      layer9_validation_report.json

Usage:
    python run_layer_9.py --run-id run_2026_05_10_48h_auto
    python run_layer_9.py   # auto-discovers latest run with Layer 8 output
"""

import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_9_verification_firewall.context_loader import load
from pipelines.layer_9_verification_firewall.script_structure_validator import validate as validate_structure
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
from pipelines.layer_9_verification_firewall.correction_patch_generator import generate as generate_patch
from pipelines.layer_9_verification_firewall.verified_script_builder import build as build_verified_script
from pipelines.layer_9_verification_firewall.layer9_writer import write as write_outputs
from pipelines.layer_9_verification_firewall.layer9_validation_gate import validate as validate_output, write_report


def run_layer_9(run_id: str) -> dict:
    started_at = datetime.now(timezone.utc)

    base       = RUNS_DIR / run_id
    layer8_dir = base / "layer_8"
    layer7_dir = base / "layer_7"
    layer4_dir = base / "layer_4"
    layer2_dir = base / "layer_2"
    layer9_dir = base / "layer_9"
    layer9_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Layer 9] Run    : {run_id}")
    print(f"[Layer 9] Input  : {layer8_dir}")
    print(f"[Layer 9] Output : {layer9_dir}\n")

    # ── Step 1: Load context ──────────────────────────────────────────────────
    print("[Layer 9] Step 1 — Loading verification context...")
    ctx = load(layer8_dir, layer7_dir, layer4_dir, layer2_dir)
    print(f"  Sentences: {len(ctx['sentence_list'])}  "
          f"Claims: {len(ctx['claim_map'])}  "
          f"Rejected: {len(ctx['rejected_claim_map'])}  "
          f"Spans: {len(ctx['span_map'])}")

    # ── Step 2: Script structure ──────────────────────────────────────────────
    print("[Layer 9] Step 2 — Validating script structure...")
    structure_result = validate_structure(ctx)
    print(f"  Status: {structure_result['status']}  "
          f"Format: {structure_result['selected_format']}  "
          f"Sections: {len(structure_result['generated_sections'])}  "
          f"Duration: {structure_result['actual_duration_s']}s")
    if structure_result["warnings"]:
        for w in structure_result["warnings"]:
            print(f"  ! {w}")

    # ── Step 3: Sentence classification ──────────────────────────────────────
    print("[Layer 9] Step 3 — Classifying sentences...")
    classified = classify(ctx)
    needs_support = sum(1 for s in classified if s.get("requires_claim_support"))
    print(f"  Total: {len(classified)}  Needs support: {needs_support}")

    # ── Step 4: Sentence-to-claim coverage ───────────────────────────────────
    print("[Layer 9] Step 4 — Checking sentence-to-claim coverage...")
    coverage = check_coverage(classified, ctx)
    print(f"  Covered: {coverage['covered']}  "
          f"Analysis-only: {coverage['analysis_only']}  "
          f"Uncovered: {coverage['uncovered']}  "
          f"Rejected used: {coverage['rejected_used']}")

    # ── Step 5: Claim-to-source traceability ──────────────────────────────────
    print("[Layer 9] Step 5 — Checking claim-to-source traceability...")
    traceability = check_traceability(coverage, ctx)
    print(f"  Claims checked: {traceability['total_checked']}  "
          f"Passed: {traceability['passed_count']}  "
          f"No spans: {traceability['no_spans']}  "
          f"Missing: {traceability['missing_claims']}")

    # ── Step 6: LLM sentence support verification ─────────────────────────────
    print("[Layer 9] Step 6 — Verifying sentence support (LLM, async)...")
    support = verify_support(classified, ctx)
    from collections import Counter
    status_counts = Counter(r["support_status"] for r in support)
    issues_count  = sum(1 for r in support if r["support_status"] in ("overclaim", "unsupported"))
    print(f"  Total: {len(support)}  Issues: {issues_count}  Statuses: {dict(status_counts)}")

    # ── Step 7: Overclaim detection ───────────────────────────────────────────
    print("[Layer 9] Step 7 — Pattern-based overclaim detection...")
    overclaims = detect_overclaims(classified, ctx)
    print(f"  Overclaims: {overclaims['overclaim_count']}  "
          f"Critical: {overclaims['critical_count']}  "
          f"High: {overclaims['high_count']}")

    # ── Step 8: Cautious language ─────────────────────────────────────────────
    print("[Layer 9] Step 8 — Verifying cautious language...")
    cautious = verify_cautious(classified, ctx)
    print(f"  Cautious claims: {cautious['cautious_claim_count']}  "
          f"Checked: {cautious['sentences_checked']}  "
          f"Failures: {cautious['failures']}")

    # ── Step 9: Rejected claim leakage ────────────────────────────────────────
    print("[Layer 9] Step 9 — Detecting rejected claim leakage...")
    leakage = detect_leakage(coverage, support, ctx)
    print(f"  Rejected checked: {leakage['rejected_claims_checked']}  "
          f"Leaks: {leakage['leak_count']}  "
          f"Status: {leakage['status']}")

    # ── Step 10: Contradictions + evidence gaps ───────────────────────────────
    print("[Layer 9] Step 10 — Checking contradiction and evidence gap handling...")
    contradiction = handle_contradictions(ctx)
    print(f"  Contradictions: {contradiction['contradictions_checked']}  "
          f"Gaps: {contradiction['evidence_gaps_checked']}  "
          f"Blocking: {contradiction['blocking_gaps']}")

    # ── Step 11: Repetition safety ────────────────────────────────────────────
    print("[Layer 9] Step 11 — Checking repetition safety...")
    repetition = check_repetition(ctx)
    print(f"  Status: {repetition['status']}  "
          f"Issues: {repetition['issue_count']}  "
          f"Warnings: {len(repetition['warnings'])}  "
          f"Published refs: {repetition['checked_against_published_videos']}")

    # ── Step 12: Metadata safety ──────────────────────────────────────────────
    print("[Layer 9] Step 12 — Checking metadata safety...")
    metadata = check_metadata(ctx)
    print(f"  Status: {metadata['status']}  "
          f"Titles: {len(metadata['title_checks'])}  "
          f"Errors: {len(metadata['errors'])}")

    # ── Step 13: Source attribution ───────────────────────────────────────────
    print("[Layer 9] Step 13 — Checking source attribution...")
    attribution = check_attribution(ctx)
    print(f"  Sources in script: {attribution['sources_used_in_script']}  "
          f"In list: {attribution['sources_in_list']}  "
          f"Missing: {attribution['missing_from_list']}")

    # ── Step 14: Risk scoring ─────────────────────────────────────────────────
    print("[Layer 9] Step 14 — Scoring risk...")
    risk = score(
        coverage, traceability, support, overclaims,
        cautious, leakage, contradiction, repetition, metadata, attribution
    )
    print(f"  Risk: {risk['overall_risk_level']}  "
          f"Score: {risk['risk_score']}  "
          f"Critical: {risk['critical_count']}  "
          f"High: {risk['high_count']}  "
          f"Medium: {risk['medium_count']}  "
          f"Recommendation: {risk['final_recommendation']}")

    # ── Step 15: Correction patches ───────────────────────────────────────────
    print("[Layer 9] Step 15 — Generating correction patches...")
    patch = generate_patch(risk, ctx)
    print(f"  Patches: {patch['patch_count']}  Auto-safe: {patch['auto_patch_safe']}")

    # ── Step 16: Verified script ──────────────────────────────────────────────
    print("[Layer 9] Step 16 — Building verified script...")
    verified = build_verified_script(risk, patch, ctx, layer8_dir)
    print(f"  Status: {verified['status']}  "
          f"Patches applied: {verified['patches_applied_count']}  "
          f"Remaining warns: {verified['remaining_warnings']}")

    # ── Step 17: Write outputs ────────────────────────────────────────────────
    print("[Layer 9] Step 17 — Writing output files...")
    manifest = write_outputs(
        run_id=run_id,
        layer9_dir=layer9_dir,
        layer8_dir=layer8_dir,
        layer7_dir=layer7_dir,
        layer4_dir=layer4_dir,
        layer2_dir=layer2_dir,
        ctx=ctx,
        classified=classified,
        coverage_result=coverage,
        traceability_result=traceability,
        support_results=support,
        overclaim_result=overclaims,
        cautious_result=cautious,
        leakage_result=leakage,
        contradiction_result=contradiction,
        repetition_result=repetition,
        metadata_result=metadata,
        attribution_result=attribution,
        risk_result=risk,
        patch_result=patch,
        verified_script=verified,
        structure_result=structure_result,
    )
    print(f"  Output: {layer9_dir}")

    # ── Step 18: Validation gate ──────────────────────────────────────────────
    print("[Layer 9] Step 18 — Validating output...")
    val_report = validate_output(run_id, layer9_dir)
    write_report(run_id, val_report, layer9_dir)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*60}")
    print(f"Layer 9 {'PASSED' if val_report['passed'] else 'FAILED'}")
    print(f"  Recommendation   : {risk['final_recommendation']}")
    print(f"  Risk level       : {risk['overall_risk_level']}")
    print(f"  Risk score       : {risk['risk_score']}")
    print(f"  Critical issues  : {risk['critical_count']}")
    print(f"  High issues      : {risk['high_count']}")
    print(f"  Medium issues    : {risk['medium_count']}")
    print(f"  Patches applied  : {verified['patches_applied_count']}")
    print(f"  Ready Layer 10   : {val_report['ready_for_layer_10']}")
    print(f"  Elapsed          : {elapsed:.1f}s")
    if val_report["warnings"]:
        for w in val_report["warnings"]:
            print(f"  ! {w}")
    if not val_report["passed"]:
        print(f"  Failure: {val_report['failure_reason']}")
    print(f"{'='*60}\n")

    return manifest


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 9 — Verification Firewall")
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/layer_8/layer8_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            run_id = rp.parents[1].name
            break
        print(f"Auto-discovered run: {run_id}")

    result = run_layer_9(run_id)
    print(f"Verified script  : {result['outputs']['verified_script']}")
    print(f"Ready for L10    : {result['handoff']['ready_for_layer_10']}")
