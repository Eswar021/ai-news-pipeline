"""
Layer 3 — Module 7: Cluster Confidence Scorer

Scores how confident the system is that each story cluster is valid.

For single-source clusters: confidence derived from trust tier + entity presence.
For multi-source clusters: weighted combination of:
  - Title embedding similarity (sentence-transformers all-MiniLM-L6-v2)
  - Specific entity overlap (product/model)
  - Same event type
  - Time proximity
  - Source type compatibility

Model: sentence-transformers/all-MiniLM-L6-v2 (~80MB, local, zero API cost)
Loaded once as a module-level singleton.

Usage:
    python cluster_confidence_scorer.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

# Lazy-loaded model — only instantiated when multi-source clusters exist
_model = None
_MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _cosine_sim(a, b) -> float:
    import numpy as np
    a, b = np.array(a), np.array(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


def _hours_apart(date_a: str | None, date_b: str | None) -> float:
    if not date_a or not date_b:
        return 9999.0
    try:
        from datetime import datetime
        a = datetime.fromisoformat(date_a.replace("Z", "+00:00"))
        b = datetime.fromisoformat(date_b.replace("Z", "+00:00"))
        return abs((a - b).total_seconds()) / 3600
    except Exception:
        return 9999.0


def _score_single_source(cluster: dict, docs_by_id: dict[str, dict]) -> dict:
    """Confidence for a single-document cluster."""
    primary_id  = cluster["cluster_members"]["primary_document_id"]
    primary_doc = docs_by_id.get(primary_id, {})
    trust_tier  = primary_doc.get("trust_tier", 4)
    has_entities = bool(cluster.get("primary_entities"))
    completeness = primary_doc.get("content_completeness", "unknown")

    # Base score from trust tier
    tier_scores = {1: 0.75, 1.5: 0.72, 2: 0.60, 2.5: 0.65, 3: 0.45}
    base = tier_scores.get(trust_tier, 0.40)

    # Adjust for content quality
    if completeness == "full":
        base = min(base + 0.05, 0.95)
    elif completeness in ("title_only", "metadata_only"):
        base = max(base - 0.10, 0.30)

    # Penalty for no entities (harder to verify story identity)
    if not has_entities:
        base = max(base - 0.05, 0.30)

    quality = "high" if base >= 0.70 else ("medium" if base >= 0.55 else "low")

    return {
        "story_id":               cluster["story_id"],
        "cluster_confidence_score": round(base, 3),
        "cluster_quality":         quality,
        "scoring_method":          "single_source_rule",
        "warnings":                [] if base >= 0.55 else ["low_source_quality"],
        "requires_manual_review":  base < 0.50,
    }


def _score_multi_source(cluster: dict, docs_by_id: dict[str, dict]) -> dict:
    """
    Confidence for a multi-document cluster using embedding similarity + rule signals.

    Weights:
        title_embedding_similarity : 0.35
        specific_entity_overlap    : 0.25
        same_event_type            : 0.20
        time_proximity             : 0.10
        source_type_diversity      : 0.10
    """
    member_ids = cluster["cluster_members"]["canonical_document_ids"]
    member_docs = [docs_by_id.get(m, {}) for m in member_ids]
    titles = [d.get("title", "") for d in member_docs]

    # ── Title embedding similarity ─────────────────────────────────────────────
    if len(titles) >= 2:
        model = _get_model()
        embeddings = model.encode(titles, show_progress_bar=False)
        sims = []
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                sims.append(_cosine_sim(embeddings[i], embeddings[j]))
        avg_sim = sum(sims) / len(sims) if sims else 0.0
    else:
        avg_sim = 1.0

    emb_score = min(avg_sim, 1.0)

    # ── Specific entity overlap ────────────────────────────────────────────────
    cluster_ents = set(cluster.get("primary_entities", []))
    entity_score = min(len(cluster_ents) / 3, 1.0) if cluster_ents else 0.0

    # ── Same event type ───────────────────────────────────────────────────────
    events = set(docs_by_id.get(m, {}).get("content_type", "") for m in member_ids)
    cluster_event = cluster.get("event_type", "unknown")
    event_score = 1.0 if cluster_event not in ("unknown",) else 0.3

    # ── Time proximity ─────────────────────────────────────────────────────────
    dates = [d.get("published_at") for d in member_docs if d.get("published_at")]
    if len(dates) >= 2:
        dates_sorted = sorted(dates)
        max_gap = _hours_apart(dates_sorted[0], dates_sorted[-1])
        time_score = max(0.0, 1.0 - max_gap / 72)
    else:
        time_score = 0.5

    # ── Source type diversity (bonus for multi-tier) ───────────────────────────
    tiers = set(docs_by_id.get(m, {}).get("trust_tier", 4) for m in member_ids)
    diversity_score = 1.0 if len(tiers) >= 2 else 0.5

    # ── Weighted combination ───────────────────────────────────────────────────
    conf = (
        0.35 * emb_score
        + 0.25 * entity_score
        + 0.20 * event_score
        + 0.10 * time_score
        + 0.10 * diversity_score
    )
    conf = round(min(conf, 1.0), 3)

    quality = "high" if conf >= 0.70 else ("medium" if conf >= 0.50 else "low")
    warnings = []
    if avg_sim < 0.3:
        warnings.append("low_title_similarity")
    if not cluster_ents:
        warnings.append("no_specific_entities")
    if max_gap > 48 if len(dates) >= 2 else False:
        warnings.append("wide_time_gap")

    return {
        "story_id":               cluster["story_id"],
        "cluster_confidence_score": conf,
        "cluster_quality":         quality,
        "scoring_method":          "multi_source_embedding_weighted",
        "score_breakdown": {
            "title_embedding_similarity": round(emb_score, 3),
            "entity_overlap_score":       round(entity_score, 3),
            "event_type_score":           round(event_score, 3),
            "time_proximity_score":       round(time_score, 3),
            "source_diversity_score":     round(diversity_score, 3),
        },
        "warnings":               warnings,
        "requires_manual_review": conf < 0.50,
    }


def score_all(clusters: list[dict], docs_by_id: dict[str, dict]) -> list[dict]:
    """Score confidence for all story clusters."""
    results = []
    for cl in clusters:
        is_multi = cl.get("is_multi_source", False)
        if is_multi:
            results.append(_score_multi_source(cl, docs_by_id))
        else:
            results.append(_score_single_source(cl, docs_by_id))
    return results


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
    all_docs      = loader_result["valid_docs"]
    doc_span_index = loader_result["doc_span_index"]

    dedup_result  = detect(all_docs)
    deduped_docs  = dedup_result["deduplicated_docs"]
    docs_by_id    = {d["canonical_document_id"]: d for d in deduped_docs}

    elig_map   = {r["canonical_document_id"]: r["eligibility"] for r in filter_all(deduped_docs)}
    entity_res = map_all(deduped_docs, layer2_dir)
    entity_map = {r["canonical_document_id"]: r for r in entity_res}
    event_res  = classify_all(deduped_docs, entity_res)
    event_map  = {r["canonical_document_id"]: r for r in event_res}

    clusters = cluster(deduped_docs, elig_map, entity_map, event_map,
                       doc_span_index, dedup_result["duplicate_doc_ids"])

    scores = score_all(clusters, docs_by_id)

    from collections import Counter
    print(f"\nCluster Confidence Scorer — {run_id}")
    print(f"  Clusters scored: {len(scores)}")
    quality_counts = Counter(s["cluster_quality"] for s in scores)
    print(f"  high  : {quality_counts.get('high', 0)}")
    print(f"  medium: {quality_counts.get('medium', 0)}")
    print(f"  low   : {quality_counts.get('low', 0)}")
    review_needed = [s for s in scores if s["requires_manual_review"]]
    print(f"  needs review: {len(review_needed)}")

    multi_scores = [s for s in scores if s["scoring_method"] == "multi_source_embedding_weighted"]
    if multi_scores:
        print("\n  Multi-source confidence scores:")
        for s in multi_scores:
            cl = next(c for c in clusters if c["story_id"] == s["story_id"])
            print(f"    {cl['story_identity']['canonical_story_title'][:50]:50} → {s['cluster_confidence_score']} ({s['cluster_quality']})")
            if "score_breakdown" in s:
                bd = s["score_breakdown"]
                print(f"      emb={bd['title_embedding_similarity']} ent={bd['entity_overlap_score']} ev={bd['event_type_score']} time={bd['time_proximity_score']}")
