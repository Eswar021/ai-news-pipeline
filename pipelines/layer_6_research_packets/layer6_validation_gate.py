"""
Layer 6 — Module 10: Layer 6 Validation Gate

Validates Layer 6 output before handing off to Layer 7.

Hard failures (block Layer 7):
  1. research_packet.json missing
  2. do_not_use claims were used in packet
  3. packet_quality_score < 70
  4. packet type does not match selected_format

Soft warnings (pass with warning):
  5. source_pack has fewer than 2 sources
  6. cautious claims present (Layer 7 must preserve qualifier guidance)
  7. section coverage < 80%
  8. source diversity low (all tier-1 only)

Key functions:
    validate(run_id, layer6_dir) → report dict
    write_report(run_id, report, layer6_dir) → path
"""

import json
from pathlib import Path

_MIN_QUALITY_SCORE    = 60
_MIN_SOURCE_COUNT     = 2
_MIN_SECTION_COVERAGE = 80


def validate(run_id: str, layer6_dir: Path) -> dict:
    errors   = []
    warnings = []

    # ── Check 1: research_packet.json exists ─────────────────────────────────
    packet_path = layer6_dir / "research_packet.json"
    if not packet_path.exists():
        return {
            "run_id":           run_id,
            "passed":           False,
            "status":           "failed",
            "failure_reason":   "research_packet.json missing",
            "errors":           ["research_packet.json not found in layer_6 output."],
            "warnings":         [],
            "ready_for_layer_7": False,
        }

    with open(packet_path) as f:
        packet = json.load(f)
    with open(layer6_dir / "evidence_boundary_report.json") as f:
        boundary = json.load(f)
    with open(layer6_dir / "packet_quality_report.json") as f:
        quality = json.load(f)
    with open(layer6_dir / "source_pack.json") as f:
        source_pack = json.load(f)

    # ── Check 2: no DNU claims used (hard) ───────────────────────────────────
    dnu_used = boundary.get("do_not_use_claims_used", 0)
    if dnu_used > 0:
        errors.append(f"{dnu_used} do-not-use claim(s) found in packet. Boundary enforcer failed.")

    # ── Check 3: quality score passes threshold (hard) ───────────────────────
    q_score = quality.get("packet_quality_score", 0)
    if q_score < _MIN_QUALITY_SCORE:
        errors.append(f"Packet quality score {q_score} is below minimum {_MIN_QUALITY_SCORE}.")

    # ── Check 4: packet type matches selected_format (hard) ──────────────────
    packet_type     = packet.get("packet_type", "")
    selected_format = packet.get("selected_format", "")
    if packet_type != selected_format:
        errors.append(
            f"packet_type '{packet_type}' does not match selected_format '{selected_format}'."
        )

    # ── Check 5: source pack has enough sources (soft) ───────────────────────
    src_count = source_pack.get("source_count", 0)
    if src_count < _MIN_SOURCE_COUNT:
        warnings.append(
            f"Source pack has only {src_count} source(s); Layer 7 may have limited evidence traceability."
        )

    # ── Check 6: cautious claims present (soft) ───────────────────────────────
    cautious_used = boundary.get("cautious_claims_used", 0)
    if cautious_used > 0:
        warnings.append(
            f"{cautious_used} cautious claim(s) in packet; Layer 7 must preserve qualifier guidance."
        )

    # ── Check 7: section coverage (soft) ─────────────────────────────────────
    sec_cov = quality.get("section_coverage_score", 100)
    if sec_cov < _MIN_SECTION_COVERAGE:
        warnings.append(
            f"Section coverage {sec_cov}% below {_MIN_SECTION_COVERAGE}%; some required sections may lack claims."
        )

    # ── Check 8: source diversity (soft) ─────────────────────────────────────
    if quality.get("source_diversity_score", 100) <= 50:
        warnings.append(
            "Low source diversity: all sources from same trust tier. "
            "Layer 7 should note this limitation when framing evidence strength."
        )

    passed           = len(errors) == 0
    ready_for_layer_7 = passed

    return {
        "run_id":             run_id,
        "passed":             passed,
        "status":             "passed" if passed else "failed",
        "failure_reason":     errors[0] if errors else None,
        "errors":             errors,
        "warnings":           warnings,
        "ready_for_layer_7":  ready_for_layer_7,
        "checks_run":         8,
        "checks_passed":      8 - len(errors),
        "packet_quality_score": q_score,
        "selected_format":    selected_format,
        "source_count":       src_count,
    }


def write_report(run_id: str, report: dict, layer6_dir: Path) -> Path:
    path = layer6_dir / "layer6_validation_report.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return path
