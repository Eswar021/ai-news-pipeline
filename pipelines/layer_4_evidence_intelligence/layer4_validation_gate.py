"""
Layer 4 — Module 11: Layer 4 Validation Gate

Validates Layer 4 output before passing to Layer 5 and Layer 6.

Hard failure checks (first 2 are blockers):
  1. atomic_claims.jsonl exists and non-empty
  2. story_fact_sheets.json exists and non-empty
  3. Every atomic claim has claim_id and story_id
  4. Every atomic claim has at least one source_span_id
  5. Every verified claim has verification_status
  6. Every safe fact in fact sheets has source_span_ids
  7. No community_signal_only claim is in safe_facts
  8. Evidence density report exists
  9. At least one story is roundup-ready

Usage:
    python layer4_validation_gate.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def validate(run_id: str, layer4_dir: Path = None) -> dict:
    if layer4_dir is None:
        layer4_dir = RUNS_DIR / run_id / "layer_4"

    checks   = []
    warnings = []

    def _check(name, ok, detail=""):
        checks.append({"check": name, "passed": ok, "detail": detail})
        return ok

    # Check 1: atomic_claims.jsonl
    atomic_path = layer4_dir / "atomic_claims.jsonl"
    atomic_claims = []
    if atomic_path.exists():
        for line in atomic_path.read_text().splitlines():
            if line.strip():
                atomic_claims.append(json.loads(line))
    _check("atomic_claims_exists", bool(atomic_claims),
           f"{len(atomic_claims)} atomic claims")

    # Check 2: story_fact_sheets.json
    sheets_path = layer4_dir / "story_fact_sheets.json"
    fact_sheets = []
    if sheets_path.exists():
        data = json.loads(sheets_path.read_text())
        fact_sheets = data.get("story_fact_sheets", [])
    _check("story_fact_sheets_exists", bool(fact_sheets),
           f"{len(fact_sheets)} fact sheets")

    # Check 3: every claim has claim_id and story_id
    bad_claims = [c for c in atomic_claims if not c.get("claim_id") or not c.get("story_id")]
    _check("all_claims_have_id_and_story", len(bad_claims) == 0,
           f"{len(bad_claims)} claims missing claim_id or story_id")

    # Check 4: every claim has at least one source_span_id
    no_span = [c for c in atomic_claims if not c.get("source_span_ids")]
    _check("all_claims_have_source_span", len(no_span) == 0,
           f"{len(no_span)} claims missing source_span_ids")

    # Check 5: verified_claims.jsonl — every entry has verification_status
    verified_path = layer4_dir / "verified_claims.jsonl"
    verified = []
    if verified_path.exists():
        for line in verified_path.read_text().splitlines():
            if line.strip():
                verified.append(json.loads(line))
    no_status = [c for c in verified if not c.get("verification_status")]
    _check("all_verified_claims_have_status", len(no_status) == 0,
           f"{len(no_status)} verified claims missing verification_status")

    # Check 6: every safe fact has source_span_ids
    bad_safe = []
    for fs in fact_sheets:
        for sf in fs.get("safe_facts", []):
            if not sf.get("source_span_ids"):
                bad_safe.append(sf.get("claim_id", "unknown"))
    _check("all_safe_facts_have_spans", len(bad_safe) == 0,
           f"{len(bad_safe)} safe facts missing source_span_ids")

    # Check 7: no community claims in safe_facts
    community_in_safe = []
    for c in verified:
        if c.get("verification_status") == "community_signal_only" and c.get("usable_in_script"):
            community_in_safe.append(c["claim_id"])
    _check("no_community_claims_as_verified_facts", len(community_in_safe) == 0,
           f"{len(community_in_safe)} community claims incorrectly marked usable")

    # Check 8: evidence_density_report exists
    density_path = layer4_dir / "evidence_density_report.json"
    _check("evidence_density_report_exists", density_path.exists(), str(density_path))

    # Check 9: at least one roundup-ready story
    roundup_ready = 0
    if density_path.exists():
        density_data = json.loads(density_path.read_text())
        roundup_ready = sum(
            1 for s in density_data.get("stories", []) if s.get("safe_for_roundup")
        )
    _check("has_roundup_ready_stories", roundup_ready > 0,
           f"{roundup_ready} roundup-ready stories")

    # Informational warnings
    deep_dive_ready = 0
    if density_path.exists():
        density_data = json.loads(density_path.read_text())
        deep_dive_ready = sum(
            1 for s in density_data.get("stories", []) if s.get("safe_for_deep_dive")
        )
    if deep_dive_ready == 0:
        warnings.append("no stories ready for deep dive — all stories are roundup-only")

    contras_path = layer4_dir / "contradictions.json"
    if contras_path.exists():
        contra_data = json.loads(contras_path.read_text())
        high_sev = sum(
            1 for c in contra_data.get("contradictions", [])
            if c.get("severity") == "high"
        )
        if high_sev > 0:
            warnings.append(f"{high_sev} high-severity contradictions found — check before script generation")

    # Pass/fail
    critical   = [c for c in checks[:2] if not c["passed"]]
    hard_fails = [c for c in checks     if not c["passed"]]
    passed     = len(critical) == 0
    status     = "passed" if (passed and not hard_fails) else (
                 "passed_with_warnings" if passed else "failed")

    return {
        "passed":            passed,
        "status":            status,
        "checks":            checks,
        "warnings":          warnings,
        "failure_reason":    critical[0]["detail"] if critical else None,
        "ready_for_layer_5": passed and roundup_ready > 0,
        "evidence_available_for_layer_6": passed and len(verified) > 0,
        "counts": {
            "atomic_claims":   len(atomic_claims),
            "verified_claims": len(verified),
            "fact_sheets":     len(fact_sheets),
            "roundup_ready":   roundup_ready,
            "deep_dive_ready": deep_dive_ready,
        },
    }


def write_report(run_id: str, report: dict, layer4_dir: Path = None) -> Path:
    if layer4_dir is None:
        layer4_dir = RUNS_DIR / run_id / "layer_4"
    path = layer4_dir / "layer4_validation_report.json"
    report["run_id"]     = run_id
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_4" / "story_fact_sheets.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    report = validate(run_id)
    print(f"\nLayer 4 Validation — {run_id}")
    print(f"  Status     : {report['status']}")
    print(f"  Passed     : {report['passed']}")
    print(f"  Layer 5 ok : {report['ready_for_layer_5']}")
    print(f"  Layer 6 ok : {report['evidence_available_for_layer_6']}")
    print(f"  Counts     : {report['counts']}")
    print("\nChecks:")
    for c in report["checks"]:
        mark = "✓" if c["passed"] else "✗"
        print(f"  {mark} {c['check']}: {c['detail']}")
    if report["warnings"]:
        print("\nWarnings:")
        for w in report["warnings"]:
            print(f"  ! {w}")
    if report["failure_reason"]:
        print(f"\nFailure: {report['failure_reason']}")
