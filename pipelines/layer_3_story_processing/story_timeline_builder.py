"""
Layer 3 — Module 9: Story Timeline Builder

Builds a chronological timeline for each story cluster.
Sorts member documents by published_at and labels each event.

Event labels:
  primary_evidence    → "Official announcement" (first) / "Official update"
  research_evidence   → "Research paper published"
  secondary_evidence  → "Independent media coverage" (first) / "Media follow-up"
  technical_artifact  → "Open source release"
  trend_signal_only   → "Community discussion"
  video              → "Video/podcast coverage"
  (first doc with missing date) → "First seen (date unknown)"

Usage:
    python story_timeline_builder.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_ROLE_FIRST_LABEL = {
    "primary_evidence":   "Official announcement",
    "research_evidence":  "Research paper published",
    "secondary_evidence": "Independent media coverage",
    "technical_artifact": "Open source release",
    "trend_signal_only":  "Community discussion",
}

_ROLE_SUBSEQUENT_LABEL = {
    "primary_evidence":   "Official update",
    "research_evidence":  "Related research",
    "secondary_evidence": "Media follow-up",
    "technical_artifact": "Related open source project",
    "trend_signal_only":  "Community discussion",
}


def build(cluster: dict, docs_by_id: dict[str, dict]) -> dict:
    """
    Build a timeline for a single story cluster.

    Returns:
        {
            "story_id": str,
            "timeline": [timeline_event, ...],
            "timeline_quality": {...},
        }
    """
    member_ids  = cluster["cluster_members"]["canonical_document_ids"]
    member_docs = [docs_by_id.get(m, {}) for m in member_ids]

    # Sort: docs with dates first (by published_at), then undated
    dated   = sorted([d for d in member_docs if d.get("published_at")],
                     key=lambda d: d["published_at"])
    undated = [d for d in member_docs if not d.get("published_at")]
    ordered = dated + undated

    timeline   = []
    seen_roles = set()

    for idx, doc in enumerate(ordered):
        doc_id = doc.get("canonical_document_id", "?")
        role   = doc.get("source_role", "unknown")
        group  = doc.get("source_group", "")
        date   = doc.get("published_at")

        if group == "youtube_podcast_transcripts":
            label = "Video/podcast coverage"
        elif role in seen_roles:
            label = _ROLE_SUBSEQUENT_LABEL.get(role, "Related coverage")
        else:
            label = _ROLE_FIRST_LABEL.get(role, "Coverage")

        if not date:
            label = f"{label} (date unknown)"

        seen_roles.add(role)

        timeline.append({
            "event_order":            idx + 1,
            "event_time":             date,
            "event_label":            label,
            "canonical_document_id":  doc_id,
            "source_role":            role,
            "source_group":           group,
            "trust_tier":             doc.get("trust_tier", 4),
            "title":                  doc.get("title", ""),
        })

    # ── Timeline quality flags ─────────────────────────────────────────────────
    has_official = any(e["source_role"] == "primary_evidence" for e in timeline)
    has_research = any(e["source_role"] == "research_evidence" for e in timeline)
    has_independent = any(e["source_role"] == "secondary_evidence" for e in timeline)
    has_community = any(e["source_role"] == "trend_signal_only" for e in timeline)
    missing_dates = sum(1 for e in timeline if not e["event_time"])

    quality = {
        "has_official_time":            has_official and dated,
        "has_research_time":            has_research and dated,
        "has_independent_coverage_time": has_independent and dated,
        "has_community_signal_time":    has_community and dated,
        "missing_dates_count":          missing_dates,
        "total_events":                 len(timeline),
    }

    return {
        "story_id":         cluster["story_id"],
        "timeline":         timeline,
        "timeline_quality": quality,
    }


def build_all(clusters: list[dict], docs_by_id: dict[str, dict]) -> list[dict]:
    return [build(cl, docs_by_id) for cl in clusters]


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
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

    from pipelines.layer_3_story_processing.document_loader         import load
    from pipelines.layer_3_story_processing.exact_duplicate_detector import detect
    from pipelines.layer_3_story_processing.eligibility_filter       import filter_all
    from pipelines.layer_3_story_processing.entity_topic_mapper      import map_all
    from pipelines.layer_3_story_processing.event_type_classifier    import classify_all
    from pipelines.layer_3_story_processing.story_clusterer          import cluster

    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer2_dir)
    all_docs  = loader_result["valid_docs"]
    doc_span_index = loader_result["doc_span_index"]
    dedup_result = detect(all_docs)
    deduped = dedup_result["deduplicated_docs"]
    docs_by_id = {d["canonical_document_id"]: d for d in deduped}

    elig_map   = {r["canonical_document_id"]: r["eligibility"] for r in filter_all(deduped)}
    entity_res = map_all(deduped, layer2_dir)
    entity_map = {r["canonical_document_id"]: r for r in entity_res}
    event_res  = classify_all(deduped, entity_res)
    event_map  = {r["canonical_document_id"]: r for r in event_res}

    clusters = cluster(deduped, elig_map, entity_map, event_map,
                       doc_span_index, dedup_result["duplicate_doc_ids"])
    timelines = build_all(clusters, docs_by_id)

    print(f"\nStory Timeline Builder — {run_id}")
    print(f"  Timelines built: {len(timelines)}")
    missing = sum(1 for t in timelines if t["timeline_quality"]["missing_dates_count"] > 0)
    print(f"  With missing dates: {missing}")

    multi = [c for c in clusters if c["is_multi_source"]]
    print("\n  Multi-source timelines:")
    for cl in multi:
        tl = next(t for t in timelines if t["story_id"] == cl["story_id"])
        print(f"\n  Story: {cl['story_identity']['canonical_story_title'][:55]}")
        for ev in tl["timeline"]:
            print(f"    [{ev['event_order']}] {ev['event_time'] or 'no date'[:20]:20} | {ev['event_label']:35} | {ev['title'][:40]}")
