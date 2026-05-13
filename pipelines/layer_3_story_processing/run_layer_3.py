"""
Layer 3 Orchestrator — Story Processing

Reads Layer 2 output, runs all 12 processing modules in sequence,
and writes the complete Layer 3 story processing output.

Processing pipeline:
  1.  document_loader          → load Layer 2 docs + build span index
  2.  exact_duplicate_detector → detect and group duplicate documents
  3.  eligibility_filter       → classify story creators vs supporters
  4.  entity_topic_mapper      → extract entities and topics
  5.  event_type_classifier    → classify event type per document
  6.  story_clusterer          → group docs into story clusters
  7.  cluster_confidence_scorer → score cluster confidence
  8.  source_mix_analyzer      → analyze source type mix per cluster
  9.  story_timeline_builder   → build chronological timeline per cluster
  10. story_ranker              → rank clusters by importance
  11. layer3_writer             → write all output files
  12. layer3_validation_gate    → validate output before Layer 4

Output:
    data/runs/{run_id}/layer_3/
      story_clusters.json
      ranked_stories.json
      cluster_membership.jsonl
      duplicate_groups.jsonl
      story_entity_topic_map.json
      story_timeline.json
      story_rank_report.json
      layer3_manifest.json
      layer3_validation_report.json

Usage:
    python run_layer_3.py --run-id run_2026_05_10_48h_auto
    python run_layer_3.py   # auto-discovers latest run with Layer 2 output
"""

import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_3_story_processing.document_loader          import load
from pipelines.layer_3_story_processing.exact_duplicate_detector  import detect
from pipelines.layer_3_story_processing.eligibility_filter        import filter_all
from pipelines.layer_3_story_processing.entity_topic_mapper       import map_all
from pipelines.layer_3_story_processing.event_type_classifier     import classify_all
from pipelines.layer_3_story_processing.story_clusterer           import cluster
from pipelines.layer_3_story_processing.cluster_confidence_scorer import score_all
from pipelines.layer_3_story_processing.source_mix_analyzer       import analyze_all
from pipelines.layer_3_story_processing.story_timeline_builder    import build_all
from pipelines.layer_3_story_processing.story_ranker              import rank_all
from pipelines.layer_3_story_processing.layer3_writer             import write
from pipelines.layer_3_story_processing.layer3_validation_gate    import validate, write_report


def run_layer_3(run_id: str) -> dict:
    """
    Execute the full Layer 3 story processing pipeline.

    Returns the layer3_manifest dict.
    """
    started_at = datetime.now(timezone.utc)
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    layer3_dir = RUNS_DIR / run_id / "layer_3"

    print(f"[Layer 3] Run    : {run_id}")
    print(f"[Layer 3] Input  : {layer2_dir}")
    print(f"[Layer 3] Output : {layer3_dir}\n")

    # ── Step 1: Load documents and build span index ────────────────────────────
    print("[Layer 3] Step 1 — Loading Layer 2 documents...")
    loader_result = load(run_id, layer2_dir)
    all_docs       = loader_result["valid_docs"]
    doc_span_index = loader_result["doc_span_index"]
    print(f"  Loaded: {loader_result['counts']['valid_docs']} docs, "
          f"{loader_result['counts']['spans_loaded']} spans")

    # ── Step 2: Exact duplicate detection ─────────────────────────────────────
    print("[Layer 3] Step 2 — Detecting duplicates...")
    dedup_result = detect(all_docs)
    deduped_docs = dedup_result["deduplicated_docs"]
    print(f"  Removed {dedup_result['counts']['removed_duplicates']} duplicates → "
          f"{dedup_result['counts']['deduplicated_docs']} unique docs "
          f"({dedup_result['counts']['duplicate_groups']} groups)")

    docs_by_id = {d["canonical_document_id"]: d for d in deduped_docs}

    # ── Step 3: Eligibility filter ─────────────────────────────────────────────
    print("[Layer 3] Step 3 — Filtering eligibility...")
    elig_results = filter_all(deduped_docs)
    elig_map     = {r["canonical_document_id"]: r["eligibility"] for r in elig_results}
    creators  = sum(1 for r in elig_results if r["eligibility"]["eligible_for_story_creation"])
    print(f"  Story creators: {creators} | Supporters/signals: {len(deduped_docs) - creators}")

    # ── Step 4: Entity + topic mapping ────────────────────────────────────────
    print("[Layer 3] Step 4 — Mapping entities and topics...")
    entity_results = map_all(deduped_docs, layer2_dir, run_id=run_id)
    entity_map     = {r["canonical_document_id"]: r for r in entity_results}
    with_entities  = sum(1 for r in entity_results if r["primary_entities"])
    print(f"  Docs with entities: {with_entities}/{len(deduped_docs)}")

    # ── Step 5: Event type classification ─────────────────────────────────────
    print("[Layer 3] Step 5 — Classifying event types...")
    event_results = classify_all(deduped_docs, entity_results)
    event_map     = {r["canonical_document_id"]: r for r in event_results}
    from collections import Counter
    ev_counts = Counter(r["event_type"] for r in event_results)
    top_ev = ", ".join(f"{ev}:{n}" for ev, n in ev_counts.most_common(4))
    print(f"  Top event types: {top_ev}")

    # ── Step 6: Story clustering ───────────────────────────────────────────────
    print("[Layer 3] Step 6 — Clustering documents into stories...")
    clusters = cluster(
        docs=deduped_docs,
        eligibility_map=elig_map,
        entity_map=entity_map,
        event_type_map=event_map,
        doc_span_index=doc_span_index,
        duplicate_doc_ids=dedup_result["duplicate_doc_ids"],
    )
    multi = sum(1 for c in clusters if c["is_multi_source"])
    print(f"  Clusters: {len(clusters)} ({multi} multi-source, {len(clusters)-multi} single-source)")

    # ── Step 7: Cluster confidence scoring ────────────────────────────────────
    print("[Layer 3] Step 7 — Scoring cluster confidence...")
    confidences = score_all(clusters, docs_by_id)
    high_conf = sum(1 for s in confidences if s["cluster_quality"] == "high")
    print(f"  High confidence: {high_conf} | Medium: "
          f"{sum(1 for s in confidences if s['cluster_quality'] == 'medium')} | "
          f"Low: {sum(1 for s in confidences if s['cluster_quality'] == 'low')}")

    # ── Step 8: Source mix analysis ────────────────────────────────────────────
    print("[Layer 3] Step 8 — Analyzing source mix...")
    source_mixes = analyze_all(clusters, docs_by_id)
    with_primary = sum(1 for m in source_mixes if m["source_strength"]["has_primary_source"])
    print(f"  Clusters with official source: {with_primary}")

    # ── Step 9: Story timeline building ───────────────────────────────────────
    print("[Layer 3] Step 9 — Building story timelines...")
    timelines = build_all(clusters, docs_by_id)
    print(f"  Timelines built: {len(timelines)}")

    # ── Step 10: Story ranking ─────────────────────────────────────────────────
    print("[Layer 3] Step 10 — Ranking stories...")
    ranked_stories = rank_all(clusters, source_mixes, confidences, timelines, docs_by_id)
    buckets = Counter(r["ranking_bucket"] for r in ranked_stories)
    print(f"  high={buckets.get('high_priority',0)} medium={buckets.get('medium_priority',0)} "
          f"low={buckets.get('low_priority',0)}")
    top_story = ranked_stories[0]["story_title"][:50] if ranked_stories else "none"
    print(f"  Top story: {top_story}")

    # ── Step 11: Write output ──────────────────────────────────────────────────
    print("[Layer 3] Step 11 — Writing output files...")
    manifest = write(
        run_id=run_id,
        layer3_dir=layer3_dir,
        clusters=clusters,
        ranked_stories=ranked_stories,
        source_mixes=source_mixes,
        confidences=confidences,
        timelines=timelines,
        duplicate_groups=dedup_result["duplicate_groups"],
        entity_maps=entity_results,
        docs_by_id=docs_by_id,
    )
    print(f"  Output: {layer3_dir}")

    # ── Step 12: Validate ──────────────────────────────────────────────────────
    print("[Layer 3] Step 12 — Validating output...")
    report = validate(run_id, layer3_dir)
    write_report(run_id, report, layer3_dir)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*55}")
    print(f"Layer 3 {'PASSED' if report['passed'] else 'FAILED'} ({report['status']})")
    print(f"  Docs processed    : {len(all_docs)}")
    print(f"  After dedup       : {len(deduped_docs)}")
    print(f"  Story clusters    : {len(clusters)}")
    print(f"  Multi-source      : {multi}")
    print(f"  Ranked stories    : {len(ranked_stories)}")
    print(f"  For Layer 4       : {manifest['counts']['stories_for_layer_4']}")
    print(f"  Ready Layer 4     : {report['ready_for_layer_4']}")
    print(f"  Elapsed           : {elapsed:.1f}s")
    if report["warnings"]:
        for w in report["warnings"]:
            print(f"  ! {w}")
    if not report["passed"]:
        print(f"  Failure: {report['failure_reason']}")
    print(f"{'='*55}\n")

    return manifest


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 3 — Story Processing")
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_2" / "canonical_documents.jsonl").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    result = run_layer_3(run_id)
    print(f"Layer 4 input: {result['outputs']['story_clusters']}")
    print(f"Story clusters: {result['counts']['story_clusters_created']}")
    print(f"Stories for Layer 4: {result['counts']['stories_for_layer_4']}")
