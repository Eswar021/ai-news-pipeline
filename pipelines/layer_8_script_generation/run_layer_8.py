"""
Layer 8 Orchestrator — Script Generation

Reads Layer 7 script_writer_brief and writes the full video script.

Processing pipeline:
  1.  brief_loader             → load brief + claim_text_map + claim_source_map
  2.  evidence_context_builder → per-section evidence bundles
  3.  script writer            → LLM: write all sections async (roundup or deep_dive)
  4.  sentence_mapper          → sentence → claim/source maps
  5.  claim_usage_tracker      → claim_usage_report
  6.  cautious_language_checker → blocked phrase + cautious language check
  7.  shorts_clips_suggester   → clip moment suggestions
  8.  youtube_metadata_builder → chapters + description + source list
  9.  layer8_writer            → write all 12 output files
  10. layer8_validation_gate   → validate output, write report

Output:
    data/runs/{run_id}/layer_8/
      script.md
      script.txt
      generated_script.json
      section_scripts.json
      sentence_claim_map.jsonl
      sentence_source_map.jsonl
      claim_usage_report.json
      cautious_language_report.json
      shorts_clips_suggestions.json
      youtube_metadata.json
      script_generation_report.json
      layer8_manifest.json
      layer8_validation_report.json

Usage:
    python run_layer_8.py --run-id run_2026_05_10_48h_auto
    python run_layer_8.py   # auto-discovers latest run with Layer 7 output
"""

import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_8_script_generation.brief_loader              import load as load_brief
from pipelines.layer_8_script_generation.evidence_context_builder  import build as build_evidence
from pipelines.layer_8_script_generation.roundup_script_writer     import write as write_roundup
from pipelines.layer_8_script_generation.deep_dive_script_writer   import write as write_deep_dive
from pipelines.layer_8_script_generation.sentence_mapper           import build as build_sentence_maps
from pipelines.layer_8_script_generation.claim_usage_tracker       import track as track_claims
from pipelines.layer_8_script_generation.cautious_language_checker import check as check_language
from pipelines.layer_8_script_generation.shorts_clips_suggester    import suggest as suggest_clips
from pipelines.layer_8_script_generation.youtube_metadata_builder  import build as build_yt_metadata
from pipelines.layer_8_script_generation.layer8_writer             import write as write_outputs
from pipelines.layer_8_script_generation.layer8_validation_gate    import validate, write_report


def run_layer_8(run_id: str) -> dict:
    started_at = datetime.now(timezone.utc)

    layer7_dir = RUNS_DIR / run_id / "layer_7"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    layer8_dir = RUNS_DIR / run_id / "layer_8"

    print(f"[Layer 8] Run    : {run_id}")
    print(f"[Layer 8] Input  : {layer7_dir}")
    print(f"[Layer 8] Output : {layer8_dir}\n")

    # ── Step 1: Load brief ───────────────────────────────────────────────────
    print("[Layer 8] Step 1 — Loading script writer brief...")
    ctx = load_brief(layer7_dir, layer4_dir)
    fmt = ctx["video_identity"]["selected_format"]
    print(f"  Format: {fmt}  Sections: {len(ctx['sections'])}  "
          f"Duration: {ctx['video_identity']['target_duration_seconds']}s  "
          f"Claims: {len(ctx['claim_text_map'])}")

    # ── Step 2: Evidence context ─────────────────────────────────────────────
    print("[Layer 8] Step 2 — Building evidence context...")
    evidence = build_evidence(ctx)
    total_req = sum(len(ev["required"]) for ev in evidence.values())
    print(f"  Sections: {len(evidence)}  Total required claims: {total_req}")

    # ── Step 3: Write script (LLM) ───────────────────────────────────────────
    print(f"[Layer 8] Step 3 — Writing script ({fmt}, async LLM)...")
    if fmt == "roundup":
        section_scripts = write_roundup(ctx, evidence)
    else:
        section_scripts = write_deep_dive(ctx, evidence)
    total_words = sum(s["word_count"] for s in section_scripts)
    total_est   = sum(s["estimated_seconds"] for s in section_scripts)
    print(f"  Sections written: {len(section_scripts)}  "
          f"Total words: {total_words}  Estimated: {total_est}s ({total_est/60:.1f} min)")

    # ── Step 4: Sentence maps ────────────────────────────────────────────────
    print("[Layer 8] Step 4 — Mapping sentences...")
    sentence_maps = build_sentence_maps(section_scripts, ctx)
    scm = sentence_maps["sentence_claim_map"]
    print(f"  Sentences: {len(scm)}")

    # ── Step 5: Claim usage ──────────────────────────────────────────────────
    print("[Layer 8] Step 5 — Tracking claim usage...")
    claim_usage_report = track_claims(section_scripts, ctx)
    print(f"  Used: {claim_usage_report['total_used']}/{claim_usage_report['total_safe']}  "
          f"Rate: {claim_usage_report['usage_rate']:.1%}")

    # ── Step 6: Cautious language check ──────────────────────────────────────
    print("[Layer 8] Step 6 — Checking cautious language...")
    cautious_report = check_language(section_scripts, ctx)
    print(f"  Passed: {cautious_report['passed']}  "
          f"Violations: {len(cautious_report['violations'])}  "
          f"Warnings: {len(cautious_report['warnings'])}")

    # ── Step 7: Shorts / clips ───────────────────────────────────────────────
    print("[Layer 8] Step 7 — Suggesting shorts / clips...")
    shorts = suggest_clips(section_scripts, ctx)
    print(f"  Clip suggestions: {len(shorts)}")

    # ── Step 8: YouTube metadata ─────────────────────────────────────────────
    print("[Layer 8] Step 8 — Building YouTube metadata...")
    yt_metadata = build_yt_metadata(section_scripts, ctx)
    print(f"  Chapters: {yt_metadata['chapter_count']}  "
          f"Sources: {yt_metadata['source_count']}  "
          f"Tags: {len(yt_metadata['tags'])}")

    # ── Step 9: Write output files ────────────────────────────────────────────
    print("[Layer 8] Step 9 — Writing output files...")
    manifest = write_outputs(
        run_id=run_id,
        layer8_dir=layer8_dir,
        layer7_dir=layer7_dir,
        layer8_ctx=ctx,
        section_scripts=section_scripts,
        sentence_maps=sentence_maps,
        claim_usage_report=claim_usage_report,
        cautious_language_report=cautious_report,
        shorts_suggestions=shorts,
        youtube_metadata=yt_metadata,
    )
    print(f"  Output: {layer8_dir}")

    # ── Step 10: Validate ────────────────────────────────────────────────────
    print("[Layer 8] Step 10 — Validating output...")
    val_report = validate(run_id, layer8_dir)
    write_report(run_id, val_report, layer8_dir)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*58}")
    print(f"Layer 8 {'PASSED' if val_report['passed'] else 'FAILED'} ({val_report['status']})")
    print(f"  Format         : {fmt}")
    print(f"  Word count     : {val_report['word_count']}")
    print(f"  Sections       : {manifest['summary']['section_count']}")
    print(f"  Claim usage    : {val_report['claim_usage_rate']:.1%}")
    print(f"  Sources        : {val_report['source_count']}")
    print(f"  Shorts         : {manifest['summary']['shorts_count']}")
    print(f"  Cautious check : {'PASS' if val_report['cautious_passed'] else 'FAIL'}")
    print(f"  Ready Layer 9  : {val_report['ready_for_layer_9']}")
    print(f"  Elapsed        : {elapsed:.1f}s")
    if val_report["warnings"]:
        for w in val_report["warnings"]:
            msg = w["message"] if isinstance(w, dict) else str(w)
            print(f"  ! {msg}")
    if not val_report["passed"]:
        print(f"  Failure: {val_report['failure_reason']}")
    print(f"{'='*58}\n")

    return manifest


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 8 — Script Generation")
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/layer_7/layer7_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            run_id = rp.parents[1].name
            break
        print(f"Auto-discovered run: {run_id}")

    result = run_layer_8(run_id)
    print(f"Script            : {result['handoff']['script_path']}")
    print(f"Section scripts   : {result['handoff']['section_scripts_path']}")
    print(f"Ready for Layer 9 : {result['handoff']['ready_for_layer_9']}")
