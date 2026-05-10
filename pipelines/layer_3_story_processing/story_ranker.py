"""
Layer 3 — Module 10: Story Importance Ranker

Ranks story clusters by importance using additive scoring across:
  authority_score           (max 30) — official/research sources present
  coverage_score            (max 15) — independent news coverage
  evidence_availability     (max 10) — source spans available for claim extraction
  audience_signal_score     (max 10) — community engagement
  impact_signal_score       (max 15) — event type + entity importance
  recency_score             (max 10) — how recent the story is
  cluster_confidence_bonus  (max 10) — high-confidence clusters get a boost

Total max: 100

Ranking buckets:
  high_priority  : score >= 65
  medium_priority: score >= 40
  low_priority   : score >= 20
  not_ranked     : score < 20

Usage:
    python story_ranker.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_HIGH_IMPACT_EVENTS = {
    "model_release", "product_launch", "open_source_release", "funding_or_acquisition"
}
_MEDIUM_IMPACT_EVENTS = {
    "benchmark_result", "infrastructure_or_chip_news", "regulation_or_policy",
    "pricing_or_plan_change", "partnership"
}
_LOW_IMPACT_EVENTS = {
    "research_paper", "safety_or_risk_issue", "community_controversy", "tutorial_or_demo"
}

_MAJOR_COMPANIES = {"OpenAI", "Anthropic", "Google", "Google DeepMind", "Meta", "Microsoft", "NVIDIA"}


def _days_ago(date_str: str | None) -> float:
    """Return how many days ago the date was, relative to now."""
    if not date_str:
        return 999.0
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() / 86400
    except Exception:
        return 999.0


def rank(
    cluster: dict,
    source_mix: dict,
    confidence: dict,
    timeline: dict,
    docs_by_id: dict[str, dict],
) -> dict:
    """
    Compute importance score for a single story cluster.

    Returns:
        {
            "story_id": str,
            "rank": int (set later),
            "total_story_score": int,
            "ranking_bucket": str,
            "score_breakdown": {...},
            "ranking_reasons": [str],
            "recommended_for_layer_4": bool,
            "recommended_for_layer_5": bool,
        }
    """
    story_id = cluster["story_id"]
    mix      = source_mix.get("source_mix", {})
    strength = source_mix.get("source_strength", {})
    conf     = confidence.get("cluster_confidence_score", 0.5)
    event_type = cluster.get("event_type", "unknown")
    entities = cluster.get("entities", {})

    reasons: list[str] = []
    scores: dict[str, int] = {}

    # ── Authority score (max 30) ───────────────────────────────────────────────
    auth = 0
    if mix.get("official_source_count", 0) > 0:
        auth += 25
        reasons.append("official_source_present")
    if mix.get("research_source_count", 0) > 0:
        auth += 18
        reasons.append("research_source_present")
    if mix.get("github_source_count", 0) > 0:
        auth += 8
        reasons.append("technical_artifact_present")
    scores["authority_score"] = min(auth, 30)

    # ── Coverage score (max 15) ────────────────────────────────────────────────
    news_count = mix.get("independent_news_count", 0)
    if news_count >= 3:
        cov = 15
        reasons.append("strong_news_coverage")
    elif news_count == 2:
        cov = 10
        reasons.append("moderate_news_coverage")
    elif news_count == 1:
        cov = 5
        reasons.append("some_news_coverage")
    else:
        cov = 0
    scores["coverage_score"] = cov

    # ── Evidence availability (max 10) ────────────────────────────────────────
    total_spans = strength.get("total_source_spans", 0)
    if total_spans >= 10:
        ev_av = 10
    elif total_spans >= 5:
        ev_av = 7
    elif total_spans >= 2:
        ev_av = 4
    elif total_spans >= 1:
        ev_av = 2
    else:
        ev_av = 0

    # Penalize if all content is partial/title-only
    primary_id = cluster["cluster_members"]["primary_document_id"]
    primary_doc = docs_by_id.get(primary_id, {})
    if primary_doc.get("content_completeness") in ("title_only", "metadata_only"):
        ev_av = max(ev_av - 5, 0)
        reasons.append("weak_primary_content")
    elif primary_doc.get("usable_for_claim_extraction"):
        reasons.append("claim_extractable")

    scores["evidence_availability_score"] = ev_av

    # ── Audience signal (max 10) ───────────────────────────────────────────────
    community = mix.get("community_signal_count", 0)
    if community >= 3:
        aud = 10
        reasons.append("strong_community_signal")
    elif community >= 1:
        aud = 5
        reasons.append("some_community_signal")
    else:
        aud = 0
    scores["audience_signal_score"] = aud

    # ── Impact signal (max 15) ────────────────────────────────────────────────
    impact = 0
    if event_type in _HIGH_IMPACT_EVENTS:
        impact += 12
        reasons.append(f"high_impact_event_{event_type}")
    elif event_type in _MEDIUM_IMPACT_EVENTS:
        impact += 7
    elif event_type in _LOW_IMPACT_EVENTS:
        impact += 3

    # Major company entity bonus
    major_companies = set(entities.get("companies", [])) & _MAJOR_COMPANIES
    if major_companies:
        impact = min(impact + 3, 15)
        reasons.append(f"major_company_{list(major_companies)[0]}")

    scores["impact_signal_score"] = min(impact, 15)

    # ── Recency score (max 10) ─────────────────────────────────────────────────
    first_seen = cluster.get("story_identity", {}).get("first_seen_at")
    days_old = _days_ago(first_seen)
    if days_old <= 1:
        rec = 10
    elif days_old <= 2:
        rec = 8
    elif days_old <= 3:
        rec = 5
    elif days_old <= 7:
        rec = 3
    else:
        rec = 0
    scores["recency_score"] = rec

    # ── Cluster confidence bonus (max 10) ─────────────────────────────────────
    conf_bonus = round(conf * 10)
    scores["cluster_confidence_bonus"] = conf_bonus
    if conf >= 0.80:
        reasons.append("high_cluster_confidence")
    elif conf < 0.50:
        reasons.append("low_cluster_confidence_penalty")

    total = sum(scores.values())
    scores["total_story_score"] = total

    if total >= 65:
        bucket = "high_priority"
    elif total >= 40:
        bucket = "medium_priority"
    elif total >= 20:
        bucket = "low_priority"
    else:
        bucket = "not_ranked"

    return {
        "story_id":                 story_id,
        "rank":                     0,   # filled in after sorting all clusters
        "story_title":              cluster["story_identity"]["canonical_story_title"],
        "story_type":               event_type,
        "total_story_score":        total,
        "ranking_bucket":           bucket,
        "score_breakdown":          scores,
        "ranking_reasons":          reasons,
        "recommended_for_layer_4":  bucket in ("high_priority", "medium_priority"),
        "recommended_for_layer_5":  bucket in ("high_priority", "medium_priority", "low_priority"),
    }


def rank_all(
    clusters: list[dict],
    source_mixes: list[dict],
    confidences: list[dict],
    timelines: list[dict],
    docs_by_id: dict[str, dict],
) -> list[dict]:
    """Rank all clusters and assign final rank numbers."""
    mix_index   = {m["story_id"]: m for m in source_mixes}
    conf_index  = {c["story_id"]: c for c in confidences}
    tl_index    = {t["story_id"]: t for t in timelines}

    results = []
    for cl in clusters:
        sid = cl["story_id"]
        results.append(rank(
            cluster=cl,
            source_mix=mix_index.get(sid, {}),
            confidence=conf_index.get(sid, {}),
            timeline=tl_index.get(sid, {}),
            docs_by_id=docs_by_id,
        ))

    results.sort(key=lambda r: -r["total_story_score"])
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_2" / "canonical_documents.jsonl").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_3_story_processing.document_loader          import load
    from pipelines.layer_3_story_processing.exact_duplicate_detector  import detect
    from pipelines.layer_3_story_processing.eligibility_filter        import filter_all
    from pipelines.layer_3_story_processing.entity_topic_mapper       import map_all
    from pipelines.layer_3_story_processing.event_type_classifier     import classify_all
    from pipelines.layer_3_story_processing.story_clusterer           import cluster
    from pipelines.layer_3_story_processing.cluster_confidence_scorer import score_all
    from pipelines.layer_3_story_processing.source_mix_analyzer       import analyze_all
    from pipelines.layer_3_story_processing.story_timeline_builder    import build_all

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

    confidences = score_all(clusters, docs_by_id)
    mixes       = analyze_all(clusters, docs_by_id)
    timelines   = build_all(clusters, docs_by_id)
    ranked      = rank_all(clusters, mixes, confidences, timelines, docs_by_id)

    from collections import Counter
    buckets = Counter(r["ranking_bucket"] for r in ranked)
    print(f"\nStory Ranker — {run_id}")
    print(f"  Total clusters ranked: {len(ranked)}")
    print(f"  high_priority   : {buckets.get('high_priority', 0)}")
    print(f"  medium_priority : {buckets.get('medium_priority', 0)}")
    print(f"  low_priority    : {buckets.get('low_priority', 0)}")
    print(f"  not_ranked      : {buckets.get('not_ranked', 0)}")

    print(f"\n  Top {args.top} stories:")
    for r in ranked[:args.top]:
        bucket_short = r["ranking_bucket"].split("_")[0].upper()[:3]
        print(f"  [{r['rank']:2}] [{bucket_short}] score={r['total_story_score']:3} | {r['story_title'][:60]}")
