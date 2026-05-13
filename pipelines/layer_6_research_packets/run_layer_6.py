"""
Layer 6 Orchestrator — Format-Specific Research Packets

Reads Layer 5 output and all upstream data, builds the format-specific
research packet, and writes the complete Layer 6 output.

Processing pipeline:
  1.  brief_loader          → load + validate selected_video_brief
  2.  Load Layer 4 data     → fact_sheets, verified_claims, gaps
  3.  Load Layer 3 data     → story_timeline, entity_topic_map
  4.  Load Layer 2 data     → source_spans, canonical_documents
  5.  packet_builder        → roundup_packet_builder or deep_dive_packet_builder
  6.  evidence_boundary_enforcer → scan + enforce DNU boundaries
  7.  source_pack_builder   → resolve claims → spans → docs → source_pack
  8.  claim_section_mapper  → map claims to sections
  9.  packet_context_builder → compress for Layer 7 handoff
  10. packet_quality_scorer → score 5 dimensions
  11. layer6_writer         → write all 7 output files
  12. layer6_validation_gate → validate before Layer 7
  13. write validation report

Output:
    data/runs/{run_id}/layer_6/
      research_packet.json
      source_pack.json
      claim_section_map.json
      evidence_boundary_report.json
      packet_quality_report.json
      packet_context_for_layer7.json
      layer6_manifest.json
      layer6_validation_report.json

Usage:
    python run_layer_6.py --run-id run_2026_05_10_48h_auto
    python run_layer_6.py   # auto-discovers latest run with Layer 5 output
"""

import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_6_research_packets.brief_loader              import load as load_brief
from pipelines.layer_6_research_packets.roundup_packet_builder    import build as build_roundup
from pipelines.layer_6_research_packets.deep_dive_packet_builder  import build as build_deep_dive
from pipelines.layer_6_research_packets.evidence_boundary_enforcer import enforce
from pipelines.layer_6_research_packets.source_pack_builder       import build as build_sources
from pipelines.layer_6_research_packets.claim_section_mapper      import map_claims
from pipelines.layer_6_research_packets.packet_context_builder    import build as build_context
from pipelines.layer_6_research_packets.packet_quality_scorer     import score as score_quality
from pipelines.layer_6_research_packets.layer6_writer             import write
from pipelines.layer_6_research_packets.layer6_validation_gate    import validate, write_report


def _load_jsonl(path: Path) -> list:
    records = []
    with open(path) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def run_layer_6(run_id: str) -> dict:
    started_at = datetime.now(timezone.utc)

    layer2_dir = RUNS_DIR / run_id / "layer_2"
    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    layer5_dir = RUNS_DIR / run_id / "layer_5"
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    print(f"[Layer 6] Run    : {run_id}")
    print(f"[Layer 6] Input  : {layer5_dir}")
    print(f"[Layer 6] Output : {layer6_dir}\n")

    # ── Step 1: Load brief ───────────────────────────────────────────────────
    print("[Layer 6] Step 1 — Loading selected video brief...")
    brief_ctx = load_brief(layer5_dir)
    print(f"  Format: {brief_ctx['selected_format']}  "
          f"Stories: {len(brief_ctx['selected_story_ids'])}  "
          f"Safe claims: {len(brief_ctx['safe_claim_ids'])}")

    # ── Step 2: Load Layer 4 data ────────────────────────────────────────────
    print("[Layer 6] Step 2 — Loading Layer 4 data...")
    with open(layer4_dir / "story_fact_sheets.json") as f:
        raw_sheets = json.load(f)
    fact_sheets_by_id = {fs["story_id"]: fs for fs in raw_sheets["story_fact_sheets"]}

    verified_claims_by_id = {c["claim_id"]: c for c in _load_jsonl(layer4_dir / "verified_claims.jsonl")}

    raw_gaps  = json.load(open(layer4_dir / "evidence_gaps.json"))
    gap_list  = raw_gaps if isinstance(raw_gaps, list) else raw_gaps.get("evidence_gaps", [])
    gaps_by_story: dict = {}
    for g in gap_list:
        sid = g.get("story_id", "")
        gaps_by_story.setdefault(sid, []).append(g)

    print(f"  Fact sheets: {len(fact_sheets_by_id)}  "
          f"Verified claims: {len(verified_claims_by_id)}")

    # ── Step 3: Load Layer 3 data ────────────────────────────────────────────
    print("[Layer 6] Step 3 — Loading Layer 3 data...")
    with open(layer3_dir / "story_timeline.json") as f:
        raw_tl = json.load(f)
    timelines_by_story = {t["story_id"]: t for t in raw_tl["story_timelines"]}
    print(f"  Timelines: {len(timelines_by_story)}")

    # ── Step 4: Load Layer 2 data ────────────────────────────────────────────
    print("[Layer 6] Step 4 — Loading Layer 2 data...")
    spans_by_id = {s["span_id"]: s for s in _load_jsonl(layer2_dir / "source_spans.jsonl")}
    docs_by_id  = {d["canonical_document_id"]: d
                   for d in _load_jsonl(layer2_dir / "canonical_documents.jsonl")}
    print(f"  Source spans: {len(spans_by_id)}  Canonical docs: {len(docs_by_id)}")

    # ── Step 5: Build format-specific packet ─────────────────────────────────
    fmt = brief_ctx["selected_format"]
    print(f"[Layer 6] Step 5 — Building {fmt} packet...")
    if fmt == "roundup":
        packet = build_roundup(brief_ctx, fact_sheets_by_id, verified_claims_by_id)
        n_segments = len(packet.get("segments", []))
        print(f"  Segments: {n_segments}  "
              f"Total seconds: {packet['episode']['target_duration_seconds']}")
    elif fmt == "deep_dive":
        packet = build_deep_dive(
            brief_ctx, fact_sheets_by_id, verified_claims_by_id,
            timelines_by_story, gaps_by_story
        )
        n_sections = len(packet.get("research_sections", []))
        print(f"  Sections: {n_sections}  "
              f"Story: {packet['story']['canonical_story_title'][:60]}")
    else:
        raise ValueError(f"No packet builder for format: {fmt}")

    # ── Step 6: Enforce evidence boundaries ──────────────────────────────────
    print("[Layer 6] Step 6 — Enforcing evidence boundaries...")
    boundary_report = enforce(packet, brief_ctx, verified_claims_by_id)
    print(f"  Status: {boundary_report['evidence_boundary_status']}  "
          f"Safe: {boundary_report['safe_claims_used']}  "
          f"DNU used: {boundary_report['do_not_use_claims_used']}")

    # ── Step 7: Build source pack ────────────────────────────────────────────
    print("[Layer 6] Step 7 — Building source pack...")
    all_cids    = brief_ctx["safe_claim_ids"] | brief_ctx["cautious_claim_ids"]
    source_pack = build_sources(all_cids, verified_claims_by_id, spans_by_id, docs_by_id, run_id)
    print(f"  Sources: {source_pack['source_count']}  "
          f"Recommended (YT): {source_pack['recommended_count']}")

    # ── Step 8: Map claims to sections ───────────────────────────────────────
    print("[Layer 6] Step 8 — Mapping claims to sections...")
    claim_section_map = map_claims(packet)
    print(f"  Sections mapped: {len(claim_section_map)}")

    # ── Step 9: Build packet context for Layer 7 ─────────────────────────────
    print("[Layer 6] Step 9 — Building packet context for Layer 7...")
    packet_context = build_context(
        packet, claim_section_map, verified_claims_by_id, brief_ctx, layer6_dir
    )
    print(f"  Sections in context: {len(packet_context['sections'])}  "
          f"Warnings: {len(packet_context['warnings'])}")

    # ── Step 10: Score packet quality ────────────────────────────────────────
    print("[Layer 6] Step 10 — Scoring packet quality...")
    quality_report = score_quality(packet, source_pack, boundary_report, brief_ctx)
    print(f"  Quality score: {quality_report['packet_quality_score']}  "
          f"Ready: {quality_report['ready_for_layer_7']}")

    # ── Step 11: Write output files ──────────────────────────────────────────
    print("[Layer 6] Step 11 — Writing output files...")
    manifest = write(
        run_id=run_id,
        layer6_dir=layer6_dir,
        layer5_dir=layer5_dir,
        layer4_dir=layer4_dir,
        layer3_dir=layer3_dir,
        layer2_dir=layer2_dir,
        packet=packet,
        source_pack=source_pack,
        claim_section_map=claim_section_map,
        boundary_report=boundary_report,
        quality_report=quality_report,
        packet_context=packet_context,
        brief_ctx=brief_ctx,
    )
    print(f"  Output: {layer6_dir}")

    # ── Step 12: Validate ────────────────────────────────────────────────────
    print("[Layer 6] Step 12 — Validating output...")
    report = validate(run_id, layer6_dir)
    write_report(run_id, report, layer6_dir)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*55}")
    print(f"Layer 6 {'PASSED' if report['passed'] else 'FAILED'} ({report['status']})")
    print(f"  Format          : {manifest['packet']['selected_format']}")
    print(f"  Stories         : {manifest['counts']['selected_story_count']}")
    print(f"  Safe claims     : {manifest['counts']['safe_claim_count']}")
    print(f"  Sources         : {manifest['counts']['source_count']}")
    print(f"  Quality score   : {manifest['packet']['packet_quality_score']}")
    print(f"  Ready Layer 7   : {report['ready_for_layer_7']}")
    print(f"  Elapsed         : {elapsed:.1f}s")
    if report["warnings"]:
        for w in report["warnings"]:
            print(f"  ! {w}")
    if not report["passed"]:
        print(f"  Failure: {report['failure_reason']}")
    print(f"{'='*55}\n")

    return manifest


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 6 — Format-Specific Research Packets")
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/layer_5/selected_video_brief.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            run_id = rp.parents[1].name
            break
        print(f"Auto-discovered run: {run_id}")

    result = run_layer_6(run_id)
    print(f"Packet context : {result['handoff']['packet_context_path']}")
    print(f"Research packet: {result['handoff']['research_packet_path']}")
    print(f"Format         : {result['packet']['selected_format']}")
    print(f"Stories        : {result['counts']['selected_story_count']}")
