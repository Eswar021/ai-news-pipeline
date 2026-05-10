"""
Layer 3 — Module 11: Layer 3 Writer

Writes all Layer 3 output files to data/runs/{run_id}/layer_3/:
  story_clusters.json
  ranked_stories.json
  cluster_membership.jsonl
  duplicate_groups.jsonl
  story_entity_topic_map.json
  story_timeline.json
  story_rank_report.json
  layer3_manifest.json

Usage:
    Called by run_layer_3.py orchestrator.
"""

import sys
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _write_jsonl(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write(
    run_id: str,
    layer3_dir: Path,
    clusters: list[dict],
    ranked_stories: list[dict],
    source_mixes: list[dict],
    confidences: list[dict],
    timelines: list[dict],
    duplicate_groups: list[dict],
    entity_maps: list[dict],
    docs_by_id: dict[str, dict],
) -> dict:
    """
    Write all Layer 3 output files.

    Returns the layer3_manifest dict (also written to disk).
    """
    layer3_dir.mkdir(parents=True, exist_ok=True)

    # Build lookup indexes
    mix_index   = {m["story_id"]: m for m in source_mixes}
    conf_index  = {c["story_id"]: c for c in confidences}
    tl_index    = {t["story_id"]: t for t in timelines}
    rank_index  = {r["story_id"]: r for r in ranked_stories}
    emap_index  = {e["canonical_document_id"]: e for e in entity_maps}

    # ── story_clusters.json ────────────────────────────────────────────────────
    story_clusters_out = []
    for cl in clusters:
        sid = cl["story_id"]
        mix = mix_index.get(sid, {})
        conf = conf_index.get(sid, {})
        ranked = rank_index.get(sid, {})

        story_clusters_out.append({
            "story_id":   sid,
            "run_id":     run_id,
            "story_identity": cl["story_identity"],
            "cluster_members": cl["cluster_members"],
            "entities":   cl["entities"],
            "primary_entities": cl["primary_entities"],
            "event_type": cl["event_type"],
            "is_multi_source": cl["is_multi_source"],
            "source_mix":  mix.get("source_mix", {}),
            "source_strength": mix.get("source_strength", {}),
            "ranking": {
                "total_story_score":       ranked.get("total_story_score", 0),
                "ranking_bucket":          ranked.get("ranking_bucket", "not_ranked"),
                "rank":                    ranked.get("rank", 0),
                "recommended_for_layer_4": ranked.get("recommended_for_layer_4", False),
            },
            "cluster_confidence_score": conf.get("cluster_confidence_score", 0),
            "cluster_quality":          conf.get("cluster_quality", "low"),
        })

    _write_json(layer3_dir / "story_clusters.json", {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "story_cluster_count": len(story_clusters_out),
        "story_clusters": story_clusters_out,
    })

    # ── ranked_stories.json ────────────────────────────────────────────────────
    _write_json(layer3_dir / "ranked_stories.json", {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ranked_story_count": len(ranked_stories),
        "ranked_stories": ranked_stories,
    })

    # ── cluster_membership.jsonl ───────────────────────────────────────────────
    membership_records = []
    for cl in clusters:
        sid = cl["story_id"]
        primary_id = cl["cluster_members"]["primary_document_id"]
        conf = conf_index.get(sid, {})
        cluster_conf = conf.get("cluster_confidence_score", 0.5)

        for doc_id in cl["cluster_members"]["canonical_document_ids"]:
            doc = docs_by_id.get(doc_id, {})
            is_primary = doc_id == primary_id
            em = emap_index.get(doc_id, {})

            membership_type = "primary_source" if is_primary else (
                "supporting_source" if doc.get("trust_tier", 4) <= 2 else "trend_signal"
            )

            match_reasons = []
            if is_primary:
                match_reasons.append("seed_document")
            else:
                doc_ents = set(em.get("primary_entities", []))
                cluster_ents = set(cl.get("primary_entities", []))
                if doc_ents & cluster_ents:
                    match_reasons.append(f"shared_entity_{list(doc_ents & cluster_ents)[0]}")
                if doc.get("source_role") == cl["event_type"]:
                    match_reasons.append("same_event_type")

            membership_records.append({
                "story_id":              sid,
                "canonical_document_id": doc_id,
                "membership_type":       membership_type,
                "membership_confidence": cluster_conf if not is_primary else 1.0,
                "source_role":           doc.get("source_role", ""),
                "trust_tier":            doc.get("trust_tier", 4),
                "match_reasons":         match_reasons,
            })

    _write_jsonl(layer3_dir / "cluster_membership.jsonl", membership_records)

    # ── duplicate_groups.jsonl ─────────────────────────────────────────────────
    _write_jsonl(layer3_dir / "duplicate_groups.jsonl", duplicate_groups)

    # ── story_entity_topic_map.json ────────────────────────────────────────────
    entity_topic_map = []
    for cl in clusters:
        sid = cl["story_id"]
        entity_topic_map.append({
            "story_id":  sid,
            "entities":  cl["entities"],
            "topics":    cl["entities"].get("topics", []),
            "event_type": cl["event_type"],
        })

    _write_json(layer3_dir / "story_entity_topic_map.json", {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "story_entity_topic_map": entity_topic_map,
    })

    # ── story_timeline.json ────────────────────────────────────────────────────
    _write_json(layer3_dir / "story_timeline.json", {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "story_timelines": timelines,
    })

    # ── story_rank_report.json ─────────────────────────────────────────────────
    bucket_counts = Counter(r["ranking_bucket"] for r in ranked_stories)
    top_stories = [r["story_id"] for r in ranked_stories[:15] if r["recommended_for_layer_4"]]

    rank_report = {
        "run_id":         run_id,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "total_ranked":   len(ranked_stories),
        "bucket_summary": dict(bucket_counts),
        "top_story_ids":  top_stories,
        "stories_for_layer_4": [r["story_id"] for r in ranked_stories if r["recommended_for_layer_4"]],
        "stories_for_layer_5": [r["story_id"] for r in ranked_stories if r["recommended_for_layer_5"]],
        "score_stats": {
            "max_score": max((r["total_story_score"] for r in ranked_stories), default=0),
            "min_score": min((r["total_story_score"] for r in ranked_stories), default=0),
        },
    }
    _write_json(layer3_dir / "story_rank_report.json", rank_report)

    # ── layer3_manifest.json ───────────────────────────────────────────────────
    manifest = {
        "run_id":     run_id,
        "layer":      "layer_3_story_processing",
        "created_at": datetime.now(timezone.utc).isoformat(),

        "inputs": {
            "canonical_documents": str(layer3_dir.parent / "layer_2" / "canonical_documents.jsonl"),
            "source_spans":        str(layer3_dir.parent / "layer_2" / "source_spans.jsonl"),
            "layer2_manifest":     str(layer3_dir.parent / "layer_2" / "layer2_manifest.json"),
        },

        "outputs": {
            "story_clusters":        str(layer3_dir / "story_clusters.json"),
            "ranked_stories":        str(layer3_dir / "ranked_stories.json"),
            "cluster_membership":    str(layer3_dir / "cluster_membership.jsonl"),
            "duplicate_groups":      str(layer3_dir / "duplicate_groups.jsonl"),
            "story_entity_topic_map": str(layer3_dir / "story_entity_topic_map.json"),
            "story_timeline":        str(layer3_dir / "story_timeline.json"),
            "story_rank_report":     str(layer3_dir / "story_rank_report.json"),
        },

        "counts": {
            "canonical_documents_received": len(docs_by_id),
            "story_clusters_created":       len(clusters),
            "multi_source_clusters":        sum(1 for c in clusters if c["is_multi_source"]),
            "ranked_stories":               len(ranked_stories),
            "duplicate_groups":             len(duplicate_groups),
            "stories_for_layer_4":          len(rank_report["stories_for_layer_4"]),
        },

        "handoff": {
            "ready_for_layer_4":             len(rank_report["stories_for_layer_4"]) > 0,
            "available_for_layer_5_precheck": len(rank_report["stories_for_layer_5"]) > 0,
            "next_layer":                    "layer_4_evidence_intelligence",
        },
    }
    _write_json(layer3_dir / "layer3_manifest.json", manifest)

    return manifest
