"""
Layer 10 — Module 16: Layer 10 Writer

Writes the per-run Layer 10 manifest to:
  data/runs/{run_id}/layer_10/layer10_manifest.json

Also writes a copy to:
  memory/layer10_manifest.json  (latest run's manifest)

Manifest records what memory was updated, counts, and handoff status.
"""

import json
from datetime import datetime, timezone
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


def write(
    run_id: str,
    mc: dict,
    layer10_dir: Path,
    memory_dir: Path,
    started_at: str,
    write_results: dict,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    # Count records per memory file
    video_count    = len(_load_jsonl(memory_dir / "video_memory.jsonl"))
    story_count    = len(_load_jsonl(memory_dir / "story_coverage_memory.jsonl"))
    claim_count    = len(_load_jsonl(memory_dir / "claim_ledger.jsonl"))
    entity_count   = len(_load_jsonl(memory_dir / "entity_topic_memory.jsonl"))
    source_count   = len(_load_jsonl(memory_dir / "source_memory.jsonl"))
    editorial_count= len(_load_jsonl(memory_dir / "editorial_pattern_memory.jsonl"))
    followup_count = len(_load_jsonl(memory_dir / "followups.jsonl"))
    gap_count      = len(_load_jsonl(memory_dir / "evidence_gap_watchlist.jsonl"))
    risk_count     = len(_load_jsonl(memory_dir / "rejected_claim_patterns.jsonl"))
    signal_count   = len(_load_jsonl(memory_dir / "learning_signals.jsonl"))

    manifest = {
        "run_id":  run_id,
        "layer":   "layer_10_memory_learning",
        "version": "1.0",
        "started_at":   started_at,
        "completed_at": now,

        "inputs": {
            "layer9_manifest":          str(mc.get("layer9_dir", "")) + "/layer9_manifest.json",
            "final_publish_package":    str(mc.get("layer9_dir", "")) + "/final_publish_package.json",
            "verified_script":          str(mc.get("layer9_dir", "")) + "/verified_script.md",
            "verification_report":      str(mc.get("layer9_dir", "")) + "/verification_report.json",
        },

        "outputs": {
            "video_memory":              str(memory_dir / "video_memory.jsonl"),
            "story_coverage_memory":     str(memory_dir / "story_coverage_memory.jsonl"),
            "claim_ledger":              str(memory_dir / "claim_ledger.jsonl"),
            "entity_topic_memory":       str(memory_dir / "entity_topic_memory.jsonl"),
            "source_memory":             str(memory_dir / "source_memory.jsonl"),
            "editorial_pattern_memory":  str(memory_dir / "editorial_pattern_memory.jsonl"),
            "followups":                 str(memory_dir / "followups.jsonl"),
            "evidence_gap_watchlist":    str(memory_dir / "evidence_gap_watchlist.jsonl"),
            "rejected_claim_patterns":   str(memory_dir / "rejected_claim_patterns.jsonl"),
            "learning_signals":          str(memory_dir / "learning_signals.jsonl"),
            "memory_index":              str(memory_dir / "memory_index.json"),
            "memory_snapshot":           str(memory_dir / "memory_snapshot.json"),
        },

        "memory_update_summary": {
            "video_memory_records":          video_count,
            "story_coverage_records":        story_count,
            "claim_ledger_records":          claim_count,
            "entity_topic_records":          entity_count,
            "source_memory_records":         source_count,
            "editorial_pattern_records":     editorial_count,
            "followup_records":              followup_count,
            "evidence_gap_watchlist_records": gap_count,
            "rejected_claim_pattern_records": risk_count,
            "learning_signal_records":        signal_count,
        },

        "this_run_summary": write_results,

        "status": {
            "memory_update_status": "completed",
            "ready_for_future_runs": True,
        },

        "handoff": {
            "ready_for_future_runs": True,
            "memory_snapshot_path":  str(memory_dir / "memory_snapshot.json"),
            "memory_index_path":     str(memory_dir / "memory_index.json"),
        },
    }

    # Write to per-run layer_10 dir
    layer10_dir.mkdir(parents=True, exist_ok=True)
    run_path = layer10_dir / "layer10_manifest.json"
    run_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Write latest copy to memory dir
    mem_path = memory_dir / "layer10_manifest.json"
    mem_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "status":     "written",
        "run_path":   str(run_path),
        "mem_path":   str(mem_path),
        "manifest":   manifest,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR, MEMORY_DIR
    from pipelines.layer_10_memory_learning.context_loader import load
    from pipelines.layer_10_memory_learning.eligibility_gate import gate
    from pipelines.layer_10_memory_learning.memory_context_extractor import extract

    run_id = "run_2026_05_10_48h_auto"
    base   = RUNS_DIR / run_id
    ctx    = load(base / "layer_9", base / "layer_8", base / "layer_7",
                  base / "layer_5", base / "layer_4", base / "layer_3")
    elig   = gate(ctx)
    mc     = extract(ctx)

    started = datetime.now(timezone.utc).isoformat()
    mc["layer9_dir"] = base / "layer_9"

    result = write(run_id, mc, base / "layer_10", MEMORY_DIR, started, {})
    print(f"Status   : {result['status']}")
    print(f"Run path : {result['run_path']}")

    m = result["manifest"]
    print(f"\nMemory update summary:")
    for k, v in m["memory_update_summary"].items():
        print(f"  {k:40}: {v}")
    print(f"\nReady for future runs: {m['status']['ready_for_future_runs']}")
