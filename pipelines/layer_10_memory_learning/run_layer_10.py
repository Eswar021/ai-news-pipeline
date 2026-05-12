"""
Layer 10 Orchestrator — Memory + Learning

Runs all memory update steps after Layer 9 approval.

Processing pipeline:
  1. context_loader              → load all inputs from L3–L9
  2. eligibility_gate            → check what memory updates are allowed
  3. memory_context_extractor    → extract normalized memory context
  4. video_memory_writer         → memory/video_memory.jsonl
  5. story_coverage_memory_writer → memory/story_coverage_memory.jsonl
  6. claim_ledger_writer         → memory/claim_ledger.jsonl
  7. entity_topic_memory_writer  → memory/entity_topic_memory.jsonl
  8. source_memory_writer        → memory/source_memory.jsonl
  9. editorial_pattern_memory_writer → memory/editorial_pattern_memory.jsonl
  10. followup_tracker           → memory/followups.jsonl
  11. evidence_gap_watchlist_writer → memory/evidence_gap_watchlist.jsonl
  12. rejected_claim_pattern_writer → memory/rejected_claim_patterns.jsonl
  13. learning_signal_builder    → memory/learning_signals.jsonl
  14. memory_index_builder       → memory/memory_index.json
  15. memory_snapshot_builder    → memory/memory_snapshot.json
  16. layer10_writer             → layer_10/layer10_manifest.json
  17. layer10_validation_gate    → layer_10/layer10_validation_report.json

Output:
    memory/                       (persistent cross-run store)
    data/runs/{run_id}/layer_10/  (per-run manifest + validation)

Usage:
    python run_layer_10.py --run-id run_2026_05_10_48h_auto
    python run_layer_10.py   # auto-discovers latest run with layer_9 output
"""

import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR, MEMORY_DIR
from config.time_utils import now_project

from pipelines.layer_10_memory_learning.context_loader import load
from pipelines.layer_10_memory_learning.eligibility_gate import gate
from pipelines.layer_10_memory_learning.memory_context_extractor import extract
from pipelines.layer_10_memory_learning.video_memory_writer import write as write_video
from pipelines.layer_10_memory_learning.story_coverage_memory_writer import write as write_stories
from pipelines.layer_10_memory_learning.claim_ledger_writer import write as write_claims
from pipelines.layer_10_memory_learning.entity_topic_memory_writer import write as write_entities
from pipelines.layer_10_memory_learning.source_memory_writer import write as write_sources
from pipelines.layer_10_memory_learning.editorial_pattern_memory_writer import write as write_editorial
from pipelines.layer_10_memory_learning.followup_tracker import write as write_followups
from pipelines.layer_10_memory_learning.evidence_gap_watchlist_writer import write as write_gaps
from pipelines.layer_10_memory_learning.rejected_claim_pattern_writer import write as write_risk_patterns
from pipelines.layer_10_memory_learning.learning_signal_builder import build as build_signals
from pipelines.layer_10_memory_learning.memory_index_builder import build as build_index
from pipelines.layer_10_memory_learning.memory_snapshot_builder import build as build_snapshot
from pipelines.layer_10_memory_learning.layer10_writer import write as write_manifest
from pipelines.layer_10_memory_learning.layer10_validation_gate import validate, write_report


def run_layer_10(run_id: str) -> dict:
    started_at = now_project()

    base        = RUNS_DIR / run_id
    layer9_dir  = base / "layer_9"
    layer8_dir  = base / "layer_8"
    layer7_dir  = base / "layer_7"
    layer5_dir  = base / "layer_5"
    layer4_dir  = base / "layer_4"
    layer3_dir  = base / "layer_3"
    layer10_dir = base / "layer_10"
    layer10_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Layer 10] Run    : {run_id}")
    print(f"[Layer 10] Input  : {layer9_dir}")
    print(f"[Layer 10] Memory : {MEMORY_DIR}\n")

    # ── Step 1: Load context ──────────────────────────────────────────────────
    print("[Layer 10] Step 1 — Loading context...")
    ctx = load(layer9_dir, layer8_dir, layer7_dir, layer5_dir, layer4_dir, layer3_dir)
    print(f"  Verified claims: {len(ctx['verified_claims'])}  "
          f"Rejected: {len(ctx['rejected_claims'])}  "
          f"Gaps: {len(ctx['evidence_gaps'])}  "
          f"Stories in entity map: {len(ctx['story_entity_topic_map'])}")

    # ── Step 2: Eligibility gate ──────────────────────────────────────────────
    print("[Layer 10] Step 2 — Checking eligibility...")
    elig = gate(ctx)
    print(f"  Status: {elig['status']}  "
          f"Durable memory: {elig['durable_memory_allowed']}  "
          f"L9 approval: {elig.get('l9_approval_status', elig.get('reason', 'n/a'))}")

    # ── Step 3: Extract memory context ────────────────────────────────────────
    print("[Layer 10] Step 3 — Extracting memory context...")
    mc = extract(ctx)
    mc["layer9_dir"] = layer9_dir  # add for manifest
    print(f"  video_id: {mc['video_id']}  "
          f"format: {mc['selected_format']}  "
          f"stories: {len(mc['story_ids'])}  "
          f"claims: {len(mc['used_claim_ids'])}  "
          f"sources: {len(mc['sources'])}")
    print(f"  entities: {mc['entities']}")
    print(f"  topics  : {mc['topics']}")

    write_results = {}

    # ── Step 4: Video memory ──────────────────────────────────────────────────
    print("[Layer 10] Step 4 — Writing video memory...")
    r = write_video(mc, ctx, elig, MEMORY_DIR)
    write_results["video_memory"] = r
    print(f"  {r['status']}  video_id: {r.get('video_id', '')}")

    # ── Step 5: Story coverage ────────────────────────────────────────────────
    print("[Layer 10] Step 5 — Writing story coverage memory...")
    r = write_stories(mc, ctx, elig, MEMORY_DIR)
    write_results["story_coverage"] = r
    print(f"  Written: {r.get('written', 0)}  Skipped: {r.get('skipped', 0)}  ({r['status']})")

    # ── Step 6: Claim ledger ──────────────────────────────────────────────────
    print("[Layer 10] Step 6 — Writing claim ledger...")
    r = write_claims(mc, ctx, elig, MEMORY_DIR)
    write_results["claim_ledger"] = r
    print(f"  Written: {r.get('written', 0)}  Skipped: {r.get('skipped', 0)}  Missing: {r.get('missing_in_map', 0)}  ({r['status']})")

    # ── Step 7: Entity + topic memory ─────────────────────────────────────────
    print("[Layer 10] Step 7 — Writing entity/topic memory...")
    r = write_entities(mc, ctx, elig, MEMORY_DIR)
    write_results["entity_topic"] = r
    print(f"  Written: {r.get('written', 0)}  Skipped: {r.get('skipped', 0)}  ({r['status']})")

    # ── Step 8: Source memory ─────────────────────────────────────────────────
    print("[Layer 10] Step 8 — Writing source memory...")
    r = write_sources(mc, ctx, elig, MEMORY_DIR)
    write_results["source_memory"] = r
    print(f"  Written: {r.get('written', 0)}  Skipped: {r.get('skipped', 0)}  ({r['status']})")

    # ── Step 9: Editorial pattern ─────────────────────────────────────────────
    print("[Layer 10] Step 9 — Writing editorial pattern memory...")
    r = write_editorial(mc, ctx, elig, MEMORY_DIR)
    write_results["editorial_pattern"] = r
    print(f"  {r['status']}")

    # ── Step 10: Follow-up tracker ────────────────────────────────────────────
    print("[Layer 10] Step 10 — Writing follow-up opportunities...")
    r = write_followups(mc, ctx, elig, MEMORY_DIR)
    write_results["followups"] = r
    print(f"  Written: {r.get('written', 0)}  Skipped: {r.get('skipped', 0)}  ({r['status']})")

    # ── Step 11: Evidence gap watchlist ───────────────────────────────────────
    print("[Layer 10] Step 11 — Writing evidence gap watchlist...")
    r = write_gaps(mc, ctx, MEMORY_DIR)
    write_results["evidence_gaps"] = r
    print(f"  Written: {r.get('written', 0)}  Skipped: {r.get('skipped', 0)}  ({r['status']})")

    # ── Step 12: Rejected claim patterns ─────────────────────────────────────
    print("[Layer 10] Step 12 — Writing rejected claim patterns...")
    r = write_risk_patterns(mc, ctx, elig, MEMORY_DIR)
    write_results["risk_patterns"] = r
    print(f"  Written: {r.get('written', 0)}  ({r['status']})")

    # ── Step 13: Learning signals ─────────────────────────────────────────────
    print("[Layer 10] Step 13 — Building learning signals...")
    r = build_signals(mc, ctx, MEMORY_DIR)
    write_results["learning_signals"] = r
    print(f"  Signals: {r.get('signals_written', 0)}")

    # ── Step 14: Memory index ─────────────────────────────────────────────────
    print("[Layer 10] Step 14 — Building memory index...")
    r = build_index(MEMORY_DIR)
    write_results["memory_index"] = r
    print(f"  {r['status']}  stats: {r['stats']}")

    # ── Step 15: Memory snapshot ──────────────────────────────────────────────
    print("[Layer 10] Step 15 — Building memory snapshot...")
    r = build_snapshot(MEMORY_DIR)
    write_results["memory_snapshot"] = r
    print(f"  {r['status']}")

    # ── Step 16: Write manifest ───────────────────────────────────────────────
    print("[Layer 10] Step 16 — Writing manifest...")
    manifest_result = write_manifest(
        run_id, mc, layer10_dir, MEMORY_DIR,
        started_at.isoformat(), write_results,
    )
    print(f"  Run path : {manifest_result['run_path']}")

    # ── Step 17: Validation gate ──────────────────────────────────────────────
    print("[Layer 10] Step 17 — Validating output...")
    val_report = validate(run_id, layer10_dir, MEMORY_DIR)
    write_report(run_id, val_report, layer10_dir)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*60}")
    print(f"Layer 10 {'PASSED' if val_report['passed'] else 'FAILED'}")
    print(f"  Eligibility     : {elig['status']}")
    print(f"  Video recorded  : {write_results['video_memory']['status']}")
    print(f"  Stories written : {write_results['story_coverage'].get('written', 0)}")
    print(f"  Claims written  : {write_results['claim_ledger'].get('written', 0)}")
    print(f"  Entities/topics : {write_results['entity_topic'].get('written', 0)}")
    print(f"  Follow-ups      : {write_results['followups'].get('written', 0)}")
    print(f"  Risk patterns   : {write_results['risk_patterns'].get('written', 0)}")
    print(f"  Signals built   : {write_results['learning_signals'].get('signals_written', 0)}")
    print(f"  Ready           : {val_report['ready_for_future_runs']}")
    print(f"  Elapsed         : {elapsed:.1f}s")
    if val_report["warnings"]:
        for w in val_report["warnings"]:
            print(f"  ! {w}")
    if not val_report["passed"]:
        print(f"  Failure: {val_report['failure_reason']}")
    print(f"{'='*60}\n")

    return manifest_result["manifest"]


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 10 — Memory + Learning")
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/layer_9/layer9_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            run_id = rp.parents[1].name
            break
        print(f"Auto-discovered run: {run_id}")

    result = run_layer_10(run_id)
    print(f"Memory snapshot : {result['handoff']['memory_snapshot_path']}")
    print(f"Ready           : {result['status']['ready_for_future_runs']}")
