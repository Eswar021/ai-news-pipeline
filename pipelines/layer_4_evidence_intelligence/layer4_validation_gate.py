"""
Layer 4 — Validation Gate

Validates the lean Layer 4 outputs before Layer 5 and Layer 6.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from config.time_utils import now_project_iso


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(run_id: str, layer4_dir: Path | None = None) -> dict:
    layer4_dir = layer4_dir or (RUNS_DIR / run_id / "layer_4")
    checks = []
    warnings = []

    def _check(name: str, passed: bool, detail: str = "") -> bool:
        checks.append({"check": name, "passed": passed, "detail": detail})
        return passed

    verified_path = layer4_dir / "verified_claims.jsonl"
    rejected_path = layer4_dir / "rejected_claims.jsonl"
    fact_sheets_path = layer4_dir / "story_fact_sheets.json"
    density_path = layer4_dir / "evidence_density_report.json"
    contradictions_path = layer4_dir / "contradictions.json"

    verified_claims = _load_jsonl(verified_path) if verified_path.exists() else []
    rejected_claims = _load_jsonl(rejected_path) if rejected_path.exists() else []
    fact_sheets = _load_json(fact_sheets_path).get("story_fact_sheets", []) if fact_sheets_path.exists() else []
    density_stories = _load_json(density_path).get("stories", []) if density_path.exists() else []
    contradictions = _load_json(contradictions_path).get("contradictions", []) if contradictions_path.exists() else []

    _check("verified_claims_exists", bool(verified_claims), f"{len(verified_claims)} verified claims")
    _check("story_fact_sheets_exists", bool(fact_sheets), f"{len(fact_sheets)} fact sheets")
    _check("evidence_density_report_exists", density_path.exists(), str(density_path))

    bad_claims = [
        claim for claim in verified_claims
        if not claim.get("claim_id") or not claim.get("story_id")
    ]
    _check("verified_claims_have_ids", len(bad_claims) == 0, f"{len(bad_claims)} verified claims missing IDs")

    missing_spans = [claim for claim in verified_claims if not claim.get("source_span_ids")]
    _check("verified_claims_have_source_spans", len(missing_spans) == 0, f"{len(missing_spans)} verified claims missing source spans")

    bad_safe_facts = []
    for sheet in fact_sheets:
        for fact in sheet.get("safe_facts", []):
            if not fact.get("source_span_ids"):
                bad_safe_facts.append(fact.get("claim_id", "unknown"))
    _check("safe_facts_have_source_spans", len(bad_safe_facts) == 0, f"{len(bad_safe_facts)} safe facts missing source spans")

    roundup_ready = sum(1 for story in density_stories if story.get("safe_for_roundup"))
    _check("has_roundup_ready_stories", roundup_ready > 0, f"{roundup_ready} roundup-ready stories")

    deep_dive_ready = sum(1 for story in density_stories if story.get("safe_for_deep_dive"))
    if deep_dive_ready == 0:
        warnings.append("no stories ready for deep dive — all stories are roundup-only")

    unresolved_rejected = sum(1 for claim in rejected_claims if claim.get("rejection_reason") == "unresolved_provenance")
    if unresolved_rejected:
        warnings.append(f"{unresolved_rejected} claim(s) were rejected due to unresolved provenance")

    high_severity_contradictions = sum(1 for contradiction in contradictions if contradiction.get("severity") == "high")
    if high_severity_contradictions:
        warnings.append(f"{high_severity_contradictions} high-severity contradictions found")

    critical_failures = [check for check in checks[:3] if not check["passed"]]
    passed = len(critical_failures) == 0
    status = "passed" if passed and all(check["passed"] for check in checks) else ("passed_with_warnings" if passed else "failed")

    return {
        "passed": passed,
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "failure_reason": critical_failures[0]["detail"] if critical_failures else None,
        "ready_for_layer_5": passed and roundup_ready > 0,
        "evidence_available_for_layer_6": passed and len(verified_claims) > 0,
        "counts": {
            "verified_claims": len(verified_claims),
            "rejected_claims": len(rejected_claims),
            "fact_sheets": len(fact_sheets),
            "roundup_ready": roundup_ready,
            "deep_dive_ready": deep_dive_ready,
        },
    }


def write_report(run_id: str, report: dict, layer4_dir: Path | None = None) -> Path:
    layer4_dir = layer4_dir or (RUNS_DIR / run_id / "layer_4")
    path = layer4_dir / "layer4_validation_report.json"
    report["run_id"] = run_id
    report["checked_at"] = now_project_iso()
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
