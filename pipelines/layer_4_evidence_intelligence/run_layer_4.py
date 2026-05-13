"""
Layer 4 Orchestrator — Evidence Intelligence

Reads Layer 3 output + Layer 2 source spans, runs all 10 processing
modules in sequence, and writes the complete Layer 4 output.

Processing pipeline:
  1.  evidence_loader         → load stories + build evidence bundles
  2.  span_selector           → select spans for LLM claim extraction
  3.  claim_extractor         → LLM: extract atomic claims (parallel async)
  4.  claim_evidence_linker   → attach source provenance to each claim
  5.  claim_deduplicator      → remove near-duplicate claims (token overlap)
  6.  claim_verifier          → rule-based: trust tier + support → verification
  7.  contradiction_detector  → keyword-based conflict detection
  8.  evidence_density_scorer → score evidence sufficiency + video format safety
  9.  story_fact_sheet_builder→ assemble safe/cautious/do-not-use per story
  10. layer4_writer            → write all output files
  11. layer4_validation_gate   → validate before Layer 5

Output:
    data/runs/{run_id}/layer_4/
      atomic_claims.jsonl
      verified_claims.jsonl
      rejected_claims.jsonl
      claim_evidence_map.jsonl
      claim_dedup_groups.jsonl
      contradictions.json
      uncertainty_report.json
      evidence_density_report.json
      evidence_gaps.json
      story_fact_sheets.json
      layer4_manifest.json
      layer4_validation_report.json

Usage:
    python run_layer_4.py --run-id run_2026_05_10_48h_auto
    python run_layer_4.py   # auto-discovers latest run with Layer 3 output
"""

import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.runtime_manifest import get_layer_limits, load_manifest

from pipelines.layer_4_evidence_intelligence.evidence_loader        import load
from pipelines.layer_4_evidence_intelligence.span_selector          import select_all
from pipelines.layer_4_evidence_intelligence.claim_extractor         import extract_all
from pipelines.layer_4_evidence_intelligence.claim_evidence_linker   import link_all
from pipelines.layer_4_evidence_intelligence.claim_deduplicator      import deduplicate_all
from pipelines.layer_4_evidence_intelligence.claim_verifier          import verify_all
from pipelines.layer_4_evidence_intelligence.contradiction_detector  import detect_all
from pipelines.layer_4_evidence_intelligence.evidence_density_scorer import score_all
from pipelines.layer_4_evidence_intelligence.story_fact_sheet_builder import build_all
from pipelines.layer_4_evidence_intelligence.layer4_writer           import write
from pipelines.layer_4_evidence_intelligence.layer4_validation_gate  import validate, write_report


def run_layer_4(run_id: str) -> dict:
    """
    Execute the full Layer 4 evidence intelligence pipeline.
    Returns the layer4_manifest dict.
    """
    started_at = datetime.now(timezone.utc)
    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    layer4_dir = RUNS_DIR / run_id / "layer_4"

    print(f"[Layer 4] Run    : {run_id}")
    print(f"[Layer 4] Input  : {layer3_dir}")
    print(f"[Layer 4] Output : {layer4_dir}\n")

    manifest = load_manifest(run_id=run_id)
    layer4_limits = get_layer_limits(manifest, "layer_4")
    max_stories = int(layer4_limits.get("max_stories", 0))
    if max_stories <= 0:
        raise ValueError("execution_policy.layer_limits.layer_4.max_stories must be > 0")

    # ── Step 1: Load evidence bundles ─────────────────────────────────────────
    print("[Layer 4] Step 1 — Loading evidence bundles...")
    loader_result = load(run_id, layer3_dir, layer2_dir, max_stories=max_stories)
    evidence_bundles = loader_result["evidence_bundles"]
    spans_by_id = loader_result["spans_by_id"]
    docs_by_id  = loader_result["docs_by_id"]
    print(f"  Stories: {loader_result['stories_loaded']}  "
          f"Spans: {loader_result['counts']['total_spans_loaded']}  "
          f"Story cap: {max_stories}")

    # ── Step 2: Select spans for extraction ──────────────────────────────────
    print("[Layer 4] Step 2 — Selecting spans for claim extraction...")
    selections = select_all(evidence_bundles, spans_by_id)
    total_selected = sum(s["counts"]["selected"] for s in selections)
    total_excluded = sum(s["counts"]["excluded"] for s in selections)
    print(f"  Selected: {total_selected}  Excluded: {total_excluded}")

    # ── Step 3: Extract atomic claims (LLM, parallel) ────────────────────────
    print(f"[Layer 4] Step 3 — Extracting claims (LLM, {total_selected} spans)...")
    story_results = extract_all(selections, run_id)
    total_extracted = sum(r["counts"]["claims_extracted"] for r in story_results)
    print(f"  Claims extracted: {total_extracted}")

    # ── Step 4: Link evidence provenance ─────────────────────────────────────
    print("[Layer 4] Step 4 — Linking evidence provenance...")
    link_result = link_all(story_results, spans_by_id, docs_by_id)
    enriched_results  = link_result["enriched_story_results"]
    evidence_map_records = link_result["evidence_map_records"]
    print(f"  Evidence records: {len(evidence_map_records)}")

    # ── Step 5: Deduplicate claims ────────────────────────────────────────────
    print("[Layer 4] Step 5 — Deduplicating claims...")
    dedup_result = deduplicate_all(enriched_results)
    deduped_results = dedup_result["deduped_results"]
    dedup_groups    = dedup_result["dedup_groups"]
    total_deduped = sum(len(r["atomic_claims"]) for r in deduped_results)
    print(f"  After dedup: {total_deduped}  Groups: {len(dedup_groups)}")

    # ── Step 6: Verify claims ─────────────────────────────────────────────────
    print("[Layer 4] Step 6 — Verifying claims...")
    verified_results = verify_all(deduped_results)
    total_verified = sum(r["counts"].get("verified", 0) for r in verified_results)
    total_rejected = sum(r["counts"].get("rejected", 0) for r in verified_results)
    total_high     = sum(r["counts"].get("high_confidence", 0) for r in verified_results)
    print(f"  Verified: {total_verified}  Rejected: {total_rejected}  "
          f"High confidence: {total_high}")

    # ── Step 7: Detect contradictions ────────────────────────────────────────
    print("[Layer 4] Step 7 — Detecting contradictions...")
    contradiction_results = detect_all(verified_results)
    total_contras = sum(d["count"] for d in contradiction_results)
    print(f"  Contradictions: {total_contras}")

    # ── Step 8: Score evidence density ───────────────────────────────────────
    print("[Layer 4] Step 8 — Scoring evidence density...")
    density_results = score_all(verified_results, contradiction_results, evidence_bundles)
    roundup_ready   = sum(1 for d in density_results if d["density"].get("safe_for_roundup"))
    deep_dive_ready = sum(1 for d in density_results if d["density"].get("safe_for_deep_dive"))
    print(f"  Roundup-ready: {roundup_ready}  Deep-dive-ready: {deep_dive_ready}")

    # ── Step 9: Build fact sheets ─────────────────────────────────────────────
    print("[Layer 4] Step 9 — Building story fact sheets...")
    fact_sheets = build_all(verified_results, contradiction_results, density_results)
    total_safe    = sum(len(fs["safe_facts"])    for fs in fact_sheets)
    total_cautious = sum(len(fs["cautious_facts"]) for fs in fact_sheets)
    print(f"  Fact sheets: {len(fact_sheets)}  "
          f"Safe facts: {total_safe}  Cautious: {total_cautious}")

    # ── Step 10: Write output ─────────────────────────────────────────────────
    print("[Layer 4] Step 10 — Writing output files...")
    manifest = write(
        run_id=run_id,
        layer4_dir=layer4_dir,
        layer3_dir=layer3_dir,
        layer2_dir=layer2_dir,
        verified_results=verified_results,
        contradiction_results=contradiction_results,
        density_results=density_results,
        fact_sheets=fact_sheets,
        evidence_map_records=evidence_map_records,
        dedup_groups=dedup_groups,
    )
    print(f"  Output: {layer4_dir}")

    # ── Step 11: Validate ─────────────────────────────────────────────────────
    print("[Layer 4] Step 11 — Validating output...")
    report = validate(run_id, layer4_dir)
    write_report(run_id, report, layer4_dir)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*55}")
    print(f"Layer 4 {'PASSED' if report['passed'] else 'FAILED'} ({report['status']})")
    print(f"  Stories analyzed   : {manifest['counts']['stories_analyzed']}")
    print(f"  Atomic claims      : {manifest['counts']['atomic_claims_extracted']}")
    print(f"  Verified           : {manifest['counts']['verified_claims']}")
    print(f"  Rejected           : {manifest['counts']['rejected_claims']}")
    print(f"  Contradictions     : {manifest['counts']['contradictions']}")
    print(f"  Roundup-ready      : {manifest['handoff']['roundup_ready_stories']}")
    print(f"  Deep-dive-ready    : {manifest['handoff']['deep_dive_ready_stories']}")
    print(f"  Ready Layer 5      : {report['ready_for_layer_5']}")
    print(f"  Elapsed            : {elapsed:.1f}s")
    if report["warnings"]:
        for w in report["warnings"]:
            print(f"  ! {w}")
    if not report["passed"]:
        print(f"  Failure: {report['failure_reason']}")
    print(f"{'='*55}\n")

    return manifest


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 4 — Evidence Intelligence")
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

    result = run_layer_4(run_id)
    print(f"Layer 5 input: {result['outputs']['story_fact_sheets']}")
    print(f"Verified claims: {result['counts']['verified_claims']}")
    print(f"Stories ready: {result['handoff']['roundup_ready_stories']}")
