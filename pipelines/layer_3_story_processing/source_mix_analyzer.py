"""
Layer 3 — Module 8: Source Mix Analyzer

Analyzes the type and quality of sources inside each story cluster.
Counts source roles and computes source strength flags.

Output per cluster:
  source_mix:    {official_source_count, independent_news_count, ...}
  source_strength: {has_primary_source, has_independent_confirmation, ...}

Usage:
    python source_mix_analyzer.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_ROLE_TO_CATEGORY = {
    "primary_evidence":    "official_source_count",
    "research_evidence":   "research_source_count",
    "secondary_evidence":  "independent_news_count",
    "technical_artifact":  "github_source_count",
    "trend_signal_only":   "community_signal_count",
    "not_for_claims":      "other_count",
}

_GROUP_TO_CATEGORY = {
    "youtube_podcast_transcripts": "video_transcript_count",
}


def analyze(cluster: dict, docs_by_id: dict[str, dict]) -> dict:
    """
    Compute source mix for a story cluster.

    Returns a dict with source_mix and source_strength.
    """
    member_ids = cluster["cluster_members"]["canonical_document_ids"]

    mix = {
        "official_source_count":   0,
        "research_source_count":   0,
        "independent_news_count":  0,
        "github_source_count":     0,
        "video_transcript_count":  0,
        "community_signal_count":  0,
        "other_count":             0,
    }

    trust_tiers = set()
    source_roles = []
    span_counts = []

    for doc_id in member_ids:
        doc = docs_by_id.get(doc_id, {})
        role = doc.get("source_role", "")
        group = doc.get("source_group", "")
        tier = doc.get("trust_tier", 4)
        trust_tiers.add(tier)
        source_roles.append(role)
        span_counts.append(doc.get("span_count", 0))

        if group in _GROUP_TO_CATEGORY:
            mix[_GROUP_TO_CATEGORY[group]] += 1
        elif role in _ROLE_TO_CATEGORY:
            mix[_ROLE_TO_CATEGORY[role]] += 1
        else:
            mix["other_count"] += 1

    total_spans = sum(span_counts)

    strength = {
        "has_primary_source":           mix["official_source_count"] > 0,
        "has_research_source":          mix["research_source_count"] > 0,
        "has_independent_confirmation": mix["independent_news_count"] >= 1,
        "has_technical_artifact":       mix["github_source_count"] > 0,
        "has_community_interest":       mix["community_signal_count"] > 0,
        "has_only_community_signal":    (
            mix["community_signal_count"] > 0
            and mix["official_source_count"] == 0
            and mix["research_source_count"] == 0
            and mix["independent_news_count"] == 0
        ),
        "multi_tier_coverage":          len(trust_tiers) >= 2,
        "total_source_spans":           total_spans,
    }

    return {
        "story_id":        cluster["story_id"],
        "source_mix":      mix,
        "source_strength": strength,
    }


def analyze_all(clusters: list[dict], docs_by_id: dict[str, dict]) -> list[dict]:
    return [analyze(cl, docs_by_id) for cl in clusters]


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
    mixes = analyze_all(clusters, docs_by_id)

    with_primary = [m for m in mixes if m["source_strength"]["has_primary_source"]]
    multi_tier   = [m for m in mixes if m["source_strength"]["multi_tier_coverage"]]

    print(f"\nSource Mix Analyzer — {run_id}")
    print(f"  Total clusters: {len(mixes)}")
    print(f"  With primary source: {len(with_primary)}")
    print(f"  Multi-tier coverage: {len(multi_tier)}")

    print("\n  Multi-source clusters source mix:")
    multi_clusters = [c for c in clusters if c["is_multi_source"]]
    for cl in multi_clusters:
        mix_data = next(m for m in mixes if m["story_id"] == cl["story_id"])
        print(f"  {cl['story_identity']['canonical_story_title'][:50]}")
        print(f"    mix={mix_data['source_mix']}")
        print(f"    strength={mix_data['source_strength']}")
