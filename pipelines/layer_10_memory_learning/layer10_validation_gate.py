"""
Layer 10 — Module 17: Layer 10 Validation Gate

Validates that memory was correctly written before marking Layer 10 complete.

Hard failures (block Layer 10 pass):
  1. video_memory.jsonl missing or empty
  2. claim_ledger.jsonl missing or empty
  3. memory_index.json missing
  4. memory_snapshot.json missing
  5. layer10_manifest.json (run copy) missing
  6. Any memory record missing run_id

Soft warnings (pass with warning):
  7. learning_signals.jsonl empty
  8. followups.jsonl empty despite evidence gaps existing

Returns: report dict with passed, errors, warnings, ready_for_future_runs
"""

import json
from pathlib import Path


def _load_jsonl(path: Path) -> list:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def validate(run_id: str, layer10_dir: Path, memory_dir: Path) -> dict:
    errors   = []
    warnings = []

    # Hard check 1: video_memory
    vm = _load_jsonl(memory_dir / "video_memory.jsonl")
    if not vm:
        errors.append("video_memory.jsonl missing or empty.")

    # Hard check 2: claim_ledger
    cl = _load_jsonl(memory_dir / "claim_ledger.jsonl")
    if not cl:
        errors.append("claim_ledger.jsonl missing or empty.")

    # Hard check 3: memory_index
    if not (memory_dir / "memory_index.json").exists():
        errors.append("memory_index.json missing.")
    else:
        idx = json.loads((memory_dir / "memory_index.json").read_text())
        if not idx.get("by_video_id") and not idx.get("by_story_id"):
            errors.append("memory_index.json is empty (no by_video_id or by_story_id).")

    # Hard check 4: memory_snapshot
    if not (memory_dir / "memory_snapshot.json").exists():
        errors.append("memory_snapshot.json missing.")

    # Hard check 5: layer10_manifest (run copy)
    if not (layer10_dir / "layer10_manifest.json").exists():
        errors.append("layer10_manifest.json (run copy) missing.")

    # Hard check 6: run_id present in all written records
    for fname in ("video_memory.jsonl", "claim_ledger.jsonl", "story_coverage_memory.jsonl"):
        records = _load_jsonl(memory_dir / fname)
        missing_run_id = [r for r in records if not r.get("run_id")]
        if missing_run_id:
            errors.append(f"{fname}: {len(missing_run_id)} records missing run_id.")

    # Soft check 7: learning signals
    ls = _load_jsonl(memory_dir / "learning_signals.jsonl")
    if not ls:
        warnings.append("learning_signals.jsonl is empty.")

    # Soft check 8: followups
    fu = _load_jsonl(memory_dir / "followups.jsonl")
    gw = _load_jsonl(memory_dir / "evidence_gap_watchlist.jsonl")
    if gw and not fu:
        warnings.append(f"{len(gw)} evidence gaps found but no follow-ups written.")

    passed             = len(errors) == 0
    ready_for_future   = passed

    return {
        "run_id":              run_id,
        "passed":              passed,
        "status":              "passed" if passed else "failed",
        "failure_reason":      errors[0] if errors else None,
        "errors":              errors,
        "warnings":            warnings,
        "ready_for_future_runs": ready_for_future,
        "memory_stats": {
            "video_records":   len(vm),
            "claim_records":   len(cl),
            "signal_records":  len(ls),
            "followup_records": len(fu),
            "gap_records":     len(gw),
        },
    }


def write_report(run_id: str, report: dict, layer10_dir: Path) -> Path:
    path = layer10_dir / "layer10_validation_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR, MEMORY_DIR

    run_id = "run_2026_05_10_48h_auto"
    layer10_dir = RUNS_DIR / run_id / "layer_10"
    report = validate(run_id, layer10_dir, MEMORY_DIR)
    write_report(run_id, report, layer10_dir)

    print(f"Passed  : {report['passed']}")
    print(f"Status  : {report['status']}")
    if report["errors"]:
        for e in report["errors"]:
            print(f"  ERROR   : {e}")
    if report["warnings"]:
        for w in report["warnings"]:
            print(f"  WARNING : {w}")
    print(f"\nMemory stats:")
    for k, v in report["memory_stats"].items():
        print(f"  {k:25}: {v}")
    print(f"\nReady for future runs: {report['ready_for_future_runs']}")
