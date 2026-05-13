"""
Layer 5 Orchestrator — Editorial Intelligence

Reads Layer 3 and Layer 4 outputs, runs all editorial scoring modules in
sequence, and writes the complete Layer 5 output including selected_video_brief.json.

Processing pipeline:
  1.  editorial_candidate_loader   → join L3+L4, build candidates
  2.  evidence_safety_gate         → per-story per-format safety
  3.  audience_fit_analyzer        → audience relevance + impact dimensions
  4.  viewer_value_analyzer        → LLM: viewer promise, question, value (async, 1/story)
  5.  novelty_checker              → memory comparison, follow-up detection
  6.  format_fit_scorer            → score each story vs roundup + deep_dive
  7.  format_router                → recommend format per story
  8.  video_opportunity_scorer     → composite opportunity score
  9.  editorial_decision_maker     → final selection + portfolio balance
  10. editorial_brief_builder      → LLM: selected_video_brief (1 call total)
  11. layer5_writer                → write all output files
  12. layer5_validation_gate       → validate before Layer 6

Output:
    data/runs/{run_id}/layer_5/
      editorial_candidates.json
      evidence_safety_decisions.json
      audience_fit_report.json
      viewer_value_report.json
      novelty_report.json
      format_fit_scores.json
      format_routing_decisions.json
      video_opportunity_scores.json
      selected_video_brief.json
      rejected_editorial_candidates.jsonl
      layer5_manifest.json
      layer5_validation_report.json

Usage:
    python run_layer_5.py --run-id run_2026_05_10_48h_auto
    python run_layer_5.py   # auto-discovers latest run with Layer 4 output
"""

import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.runtime_manifest import get_format_requirements, get_run_profile, load_manifest

from pipelines.layer_5_editorial_intelligence.editorial_candidate_loader import load
from pipelines.layer_5_editorial_intelligence.evidence_safety_gate       import gate_all
from pipelines.layer_5_editorial_intelligence.audience_fit_analyzer      import analyze_all as audience_fit_all
from pipelines.layer_5_editorial_intelligence.viewer_value_analyzer      import analyze_all as viewer_value_all
from pipelines.layer_5_editorial_intelligence.novelty_checker            import check_all, MEMORY_DIR
from pipelines.layer_5_editorial_intelligence.format_fit_scorer          import score_all as format_fit_all
from pipelines.layer_5_editorial_intelligence.format_router              import route_all
from pipelines.layer_5_editorial_intelligence.video_opportunity_scorer   import score_all as opportunity_all
from pipelines.layer_5_editorial_intelligence.editorial_decision_maker   import decide
from pipelines.layer_5_editorial_intelligence.editorial_brief_builder    import build as build_brief
from pipelines.layer_5_editorial_intelligence.layer5_writer              import write
from pipelines.layer_5_editorial_intelligence.layer5_validation_gate     import validate, write_report


def run_layer_5(run_id: str) -> dict:
    """Execute the full Layer 5 editorial intelligence pipeline. Returns manifest."""
    started_at  = datetime.now(timezone.utc)
    layer3_dir  = RUNS_DIR / run_id / "layer_3"
    layer4_dir  = RUNS_DIR / run_id / "layer_4"
    layer5_dir  = RUNS_DIR / run_id / "layer_5"
    layer5_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Layer 5] Run    : {run_id}")
    print(f"[Layer 5] Input  : {layer4_dir}")
    print(f"[Layer 5] Output : {layer5_dir}\n")

    # ── Load format requirements from run manifest ────────────────────────────
    manifest = load_manifest(run_id=run_id)
    fmt_cfg = get_format_requirements(manifest)
    run_profile = get_run_profile(manifest)
    routing_rules = manifest.get("format_strategy", {}).get("routing_rules", {})
    allowed_formats = list(run_profile.get("allowed_formats", []))

    # ── Step 1: Load editorial candidates ────────────────────────────────────
    print("[Layer 5] Step 1 — Loading editorial candidates...")
    loader_result = load(run_id, layer3_dir, layer4_dir)
    candidates    = loader_result["editorial_candidates"]
    c             = loader_result["counts"]
    print(f"  Candidates: {c['total_candidates']}  "
          f"Roundup-eligible: {c['roundup_eligible']}  "
          f"Deep-dive-eligible: {c['deep_dive_eligible']}")

    # ── Step 2: Evidence safety gate ─────────────────────────────────────────
    print("[Layer 5] Step 2 — Running evidence safety gate...")
    safety_decisions = gate_all(candidates)
    n_safe    = sum(1 for s in safety_decisions if s["overall_status"] == "safe")
    n_blocked = sum(1 for s in safety_decisions if s["overall_status"] == "blocked")
    print(f"  Safe: {n_safe}  Blocked: {n_blocked}")

    # ── Step 3: Audience fit analysis ─────────────────────────────────────────
    print("[Layer 5] Step 3 — Analyzing audience fit...")
    audience_fits = audience_fit_all(candidates)
    avg_fit = int(sum(af["audience_fit_score"] for af in audience_fits) / max(len(audience_fits), 1))
    print(f"  Avg audience fit score: {avg_fit}")

    # ── Step 4: Viewer value analysis (LLM, parallel) ────────────────────────
    print(f"[Layer 5] Step 4 — Analyzing viewer value (LLM, {len(candidates)} stories)...")
    viewer_values = viewer_value_all(candidates, run_id=run_id)
    avg_vv = int(sum(vv["viewer_value_score"] for vv in viewer_values) / max(len(viewer_values), 1))
    print(f"  Avg viewer value score: {avg_vv}")

    # ── Step 5: Novelty check ─────────────────────────────────────────────────
    print("[Layer 5] Step 5 — Checking novelty against memory...")
    novelty_results = check_all(candidates, MEMORY_DIR)
    new_topics  = sum(1 for n in novelty_results if n["coverage_status"] == "new_topic")
    follow_ups  = sum(1 for n in novelty_results if n["is_follow_up_candidate"])
    print(f"  New topics: {new_topics}  Follow-up candidates: {follow_ups}")

    # ── Step 6: Format fit scoring ────────────────────────────────────────────
    print("[Layer 5] Step 6 — Scoring format fit...")
    format_fit_scores = format_fit_all(candidates, safety_decisions, audience_fits,
                                       viewer_values, novelty_results,
                                       allowed_formats=allowed_formats)
    print(f"  Scored {len(format_fit_scores)} stories vs {', '.join(allowed_formats)}")

    # ── Step 7: Format routing ────────────────────────────────────────────────
    print("[Layer 5] Step 7 — Routing stories to formats...")
    routing_decisions = route_all(
        candidates,
        format_fit_scores,
        safety_decisions,
        novelty_results,
        allowed_formats=allowed_formats,
        routing_rules=routing_rules,
    )
    dd_count  = sum(1 for r in routing_decisions if r["recommended_format"] == "deep_dive")
    rnd_count = sum(1 for r in routing_decisions if r["recommended_format"] == "roundup_segment")
    skip_count = sum(1 for r in routing_decisions if r["recommended_format"] in ("skip", "monitor_only"))
    print(f"  Deep-dive: {dd_count}  Roundup: {rnd_count}  Skip/monitor: {skip_count}")

    # ── Step 8: Video opportunity scoring ─────────────────────────────────────
    print("[Layer 5] Step 8 — Scoring video opportunity...")
    opportunity_scores = opportunity_all(candidates, safety_decisions, audience_fits,
                                         viewer_values, novelty_results)
    strong = sum(1 for o in opportunity_scores if o["overall_recommendation"] == "strong_video_candidate")
    print(f"  Strong candidates: {strong}/{len(opportunity_scores)}")

    # ── Step 9: Editorial decision ────────────────────────────────────────────
    print("[Layer 5] Step 9 — Making editorial decision...")
    editorial_decision = decide(
        candidates,
        routing_decisions,
        opportunity_scores,
        fmt_cfg,
        run_profile=run_profile,
        routing_rules=routing_rules,
    )
    editorial_decision["run_id"] = run_id
    fmt  = editorial_decision.get("selected_format", "no_video")
    dec  = editorial_decision.get("decision")
    n_sel = len(editorial_decision.get("selected_story_ids") or
                ([editorial_decision.get("primary_story_id")] if editorial_decision.get("primary_story_id") else []))
    print(f"  Decision: {dec}  Format: {fmt}  Stories: {n_sel}  "
          f"Rejected: {len(editorial_decision.get('rejected_candidates', []))}")

    # ── Step 10: Build editorial brief (LLM, 1 call) ──────────────────────────
    print("[Layer 5] Step 10 — Building editorial brief (1 LLM call)...")
    candidates_by_id = {c["story_id"]: c for c in candidates}
    vv_by_id         = {v["story_id"]: v for v in viewer_values}

    if dec == "create_video":
        selected_video_brief = build_brief(editorial_decision, candidates_by_id,
                                           vv_by_id, fmt_cfg)
    else:
        selected_video_brief = {
            "selected_video_id": "no_video",
            "selected_format":   None,
            "handoff":           {"ready_for_layer_6": False},
            "content_direction": {},
            "evidence_boundaries": {"safe_claim_ids": [], "cautious_claim_ids": [],
                                    "do_not_use_claim_ids": [], "contradiction_ids": [],
                                    "evidence_gap_ids": []},
        }
    print(f"  Brief ready: {selected_video_brief.get('handoff', {}).get('ready_for_layer_6', False)}")

    # ── Step 11: Write output ─────────────────────────────────────────────────
    print("[Layer 5] Step 11 — Writing output files...")
    manifest = write(
        run_id=run_id,
        layer5_dir=layer5_dir,
        layer3_dir=layer3_dir,
        layer4_dir=layer4_dir,
        candidates=candidates,
        safety_decisions=safety_decisions,
        audience_fits=audience_fits,
        viewer_values=viewer_values,
        novelty_results=novelty_results,
        format_fit_scores=format_fit_scores,
        routing_decisions=routing_decisions,
        opportunity_scores=opportunity_scores,
        editorial_decision=editorial_decision,
        selected_video_brief=selected_video_brief,
    )
    print(f"  Output: {layer5_dir}")

    # ── Step 12: Validate ─────────────────────────────────────────────────────
    print("[Layer 5] Step 12 — Validating output...")
    report = validate(run_id, layer5_dir)
    write_report(run_id, report, layer5_dir)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*55}")
    print(f"Layer 5 {'PASSED' if report['passed'] else 'FAILED'} ({report['status']})")
    print(f"  Candidates evaluated : {manifest['counts']['candidate_story_count']}")
    print(f"  Decision             : {manifest['decision']['create_video']}")
    print(f"  Selected format      : {manifest['decision']['selected_format'] or 'none'}")
    print(f"  Stories selected     : {manifest['counts']['selected_story_count']}")
    print(f"  Rejected             : {manifest['counts']['rejected_candidate_count']}")
    print(f"  Ready Layer 6        : {report['ready_for_layer_6']}")
    print(f"  Elapsed              : {elapsed:.1f}s")
    if report["warnings"]:
        for w in report["warnings"]:
            print(f"  ! {w}")
    if not report["passed"]:
        print(f"  Failure: {report['failure_reason']}")
    print(f"{'='*55}\n")

    return manifest


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 5 — Editorial Intelligence")
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

    result = run_layer_5(run_id)
    print(f"Layer 6 input: {result['handoff']['selected_video_brief_path']}")
    print(f"Selected format: {result['decision']['selected_format']}")
    print(f"Stories: {result['counts']['selected_story_count']}")
