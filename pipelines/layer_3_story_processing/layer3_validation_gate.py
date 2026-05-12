"""
Layer 3 — Module 12: Layer 3 Validation Gate

Validates Layer 3 output before passing to Layer 4 and Layer 5.

Checks:
  1. story_clusters.json exists and non-empty
  2. ranked_stories.json exists and non-empty
  3. Every story has story_id and at least one member doc
  4. Every story has source_mix
  5. Every story has cluster_confidence_score
  6. Every ranked story has total_story_score
  7. At least one story is recommended_for_layer_4
  8. cluster_membership.jsonl exists
  9. story_timeline.json exists

Usage:
    python layer3_validation_gate.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def validate(run_id: str, layer3_dir: Path = None) -> dict:
    if layer3_dir is None:
        layer3_dir = RUNS_DIR / run_id / "layer_3"

    checks  = []
    warnings = []

    def _check(name, ok, detail=""):
        checks.append({"check": name, "passed": ok, "detail": detail})
        return ok

    # Check 1: story_clusters.json
    clusters_path = layer3_dir / "story_clusters.json"
    clusters = []
    if clusters_path.exists():
        data = json.loads(clusters_path.read_text())
        clusters = data.get("story_clusters", [])
    _check("story_clusters_exists", bool(clusters), f"{len(clusters)} story clusters")

    # Check 2: ranked_stories.json
    ranked_path = layer3_dir / "ranked_stories.json"
    ranked = []
    if ranked_path.exists():
        data = json.loads(ranked_path.read_text())
        ranked = data.get("ranked_stories", [])
    _check("ranked_stories_exists", bool(ranked), f"{len(ranked)} ranked stories")

    # Check 3: every story has story_id and member docs
    bad_stories = [c for c in clusters
                   if not c.get("story_id") or not c.get("cluster_members", {}).get("canonical_document_ids")]
    _check("all_stories_have_id_and_members", len(bad_stories) == 0,
           f"{len(bad_stories)} stories missing story_id or member docs")

    # Check 4: every story has source_mix
    no_mix = [c for c in clusters if not c.get("source_mix")]
    _check("all_stories_have_source_mix", len(no_mix) == 0,
           f"{len(no_mix)} stories missing source_mix")

    # Check 5: cluster_confidence_score present on all
    no_conf = [c for c in clusters if "cluster_confidence_score" not in c]
    _check("all_stories_have_confidence_score", len(no_conf) == 0,
           f"{len(no_conf)} stories missing cluster_confidence_score")

    # Check 6: ranked stories have total_story_score
    no_score = [r for r in ranked if "total_story_score" not in r]
    _check("all_ranked_stories_have_score", len(no_score) == 0,
           f"{len(no_score)} ranked stories missing total_story_score")

    # Check 7: at least one story for Layer 4
    for_l4 = [r for r in ranked if r.get("recommended_for_layer_4")]
    has_l4 = len(for_l4) > 0
    _check("has_stories_for_layer_4", has_l4, f"{len(for_l4)} stories recommended for Layer 4")
    if not has_l4:
        warnings.append("no_stories_for_layer_4 — Layer 4 will have no input")

    # Check 8: cluster_membership.jsonl exists
    membership_path = layer3_dir / "cluster_membership.jsonl"
    _check("cluster_membership_exists", membership_path.exists(), str(membership_path))

    # Check 9: story_timeline.json exists
    timeline_path = layer3_dir / "story_timeline.json"
    _check("story_timeline_exists", timeline_path.exists(), str(timeline_path))

    # Informational warnings
    low_conf = [c for c in clusters if c.get("cluster_confidence_score", 1.0) < 0.50]
    if low_conf:
        warnings.append(f"{len(low_conf)} low-confidence clusters (< 0.50)")

    single_source = [c for c in clusters if not c.get("is_multi_source")]
    if len(single_source) > len(clusters) * 0.8:
        warnings.append(f"{len(single_source)}/{len(clusters)} clusters are single-source (expected for research-heavy runs)")

    # Determine pass/fail — first 2 checks are hard failures
    critical = [c for c in checks[:2] if not c["passed"]]
    passed   = len(critical) == 0
    hard_fails = [c for c in checks if not c["passed"]]
    status = "passed" if (passed and not hard_fails) else (
        "passed_with_warnings" if passed else "failed"
    )

    return {
        "passed":                    passed,
        "status":                    status,
        "checks":                    checks,
        "warnings":                  warnings,
        "failure_reason":            critical[0]["detail"] if critical else None,
        "ready_for_layer_4":         passed and has_l4,
        "available_for_layer_5_precheck": passed and len(ranked) > 0,
        "counts": {
            "story_clusters":    len(clusters),
            "ranked_stories":    len(ranked),
            "for_layer_4":       len(for_l4),
        },
    }


def write_report(run_id: str, report: dict, layer3_dir: Path = None) -> Path:
    if layer3_dir is None:
        layer3_dir = RUNS_DIR / run_id / "layer_3"
    path = layer3_dir / "layer3_validation_report.json"
    report["run_id"]     = run_id
    report["checked_at"] = now_project_iso()
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_3" / "story_clusters.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    report = validate(run_id)
    print(f"\nLayer 3 Validation — {run_id}")
    print(f"  Status     : {report['status']}")
    print(f"  Passed     : {report['passed']}")
    print(f"  Layer 4 ok : {report['ready_for_layer_4']}")
    print(f"  Layer 5 ok : {report['available_for_layer_5_precheck']}")
    print(f"  Counts     : {report['counts']}")
    print(f"\nChecks:")
    for c in report["checks"]:
        mark = "✓" if c["passed"] else "✗"
        print(f"  {mark} {c['check']}: {c['detail']}")
    if report["warnings"]:
        print(f"\nWarnings:")
        for w in report["warnings"]:
            print(f"  ! {w}")
    if report["failure_reason"]:
        print(f"\nFailure: {report['failure_reason']}")
