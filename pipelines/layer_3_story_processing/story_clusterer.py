"""
Layer 3 — Module 6: Story Clusterer

Groups related documents into story clusters using:
  1. URL-link matching — a community signal's canonical_url matches
     another document's canonical_url (HN linking to a blog/paper)
  2. Entity + event type overlap — same primary entity (company/model/product)
     AND same event type AND within time window
  3. Single-source stories — any story-creator that doesn't match anything
     becomes its own cluster (expected for research papers)

No embeddings here — that's the confidence scorer's job.

The clusterer's output is a list of StoryCluster dicts. Each cluster has:
  - story_id
  - primary_document_id (seed)
  - member_document_ids
  - all_span_ids (aggregated from member docs)
  - match_signals (why docs were grouped)
  - canonical_story_title (from primary doc)
  - event_type
  - entities (union of member entities)
  - topics (union of member topics)
  - first_seen_at / last_seen_at

Usage:
    python story_clusterer.py --run-id run_2026_05_10_48h_auto
"""

import re
import sys
import json
import hashlib
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_TIME_WINDOW_HOURS = 72   # max hours between cluster members
_ARXIV_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d+)", re.IGNORECASE)


def _story_id(seed_doc: dict) -> str:
    date_part = (seed_doc.get("published_at") or "00000000")[:10].replace("-", "")
    slug_raw  = seed_doc.get("title", "untitled")[:40].lower()
    slug      = re.sub(r"[^a-z0-9]+", "_", slug_raw).strip("_")
    h8        = hashlib.sha1(seed_doc["canonical_document_id"].encode()).hexdigest()[:6]
    return f"story_{date_part}_{slug}_{h8}"


def _hours_apart(date_a: str | None, date_b: str | None) -> float:
    """Return absolute hours between two ISO date strings. Returns large number if missing."""
    if not date_a or not date_b:
        return 9999.0
    try:
        a = datetime.fromisoformat(date_a.replace("Z", "+00:00"))
        b = datetime.fromisoformat(date_b.replace("Z", "+00:00"))
        return abs((a - b).total_seconds()) / 3600
    except Exception:
        return 9999.0


def _entity_overlap(entities_a: list[str], entities_b: list[str]) -> int:
    """Count shared primary entities."""
    return len(set(entities_a) & set(entities_b))


def _specific_entity_overlap(em_a: dict, em_b: dict) -> int:
    """
    Count shared product/model entities (ignoring company-only overlap).
    Company overlap alone (e.g., both mention 'OpenAI') is not enough
    to merge two story creators — they could be about different topics.
    """
    prod_a = set(em_a.get("entities", {}).get("models", []) +
                 em_a.get("entities", {}).get("products", []))
    prod_b = set(em_b.get("entities", {}).get("models", []) +
                 em_b.get("entities", {}).get("products", []))
    return len(prod_a & prod_b)


def _arxiv_id(url: str) -> str | None:
    m = _ARXIV_RE.search(url or "")
    return m.group(1) if m else None


def cluster(
    docs: list[dict],
    eligibility_map: dict[str, dict],
    entity_map: dict[str, dict],
    event_type_map: dict[str, dict],
    doc_span_index: dict[str, list[str]],
    duplicate_doc_ids: dict[str, str] | None = None,
) -> list[dict]:
    """
    Cluster documents into story clusters.

    Args:
        docs:              All deduplicated canonical documents
        eligibility_map:   {doc_id: eligibility_dict}
        entity_map:        {doc_id: entity_topic_dict}
        event_type_map:    {doc_id: event_type_dict}
        doc_span_index:    {doc_id: [span_id, ...]}
        duplicate_doc_ids: {dup_id: rep_id} — collapsed by deduplicator

    Returns:
        List of story cluster dicts.
    """
    if duplicate_doc_ids is None:
        duplicate_doc_ids = {}

    # Index for fast lookup
    docs_by_id: dict[str, dict] = {d["canonical_document_id"]: d for d in docs}

    # Build URL index for URL-link matching
    url_to_doc_id: dict[str, str] = {}
    arxiv_to_doc_id: dict[str, str] = {}
    for doc in docs:
        url = (doc.get("canonical_url") or "").rstrip("/")
        if url:
            url_to_doc_id[url] = doc["canonical_document_id"]
        aid = _arxiv_id(url)
        if aid:
            arxiv_to_doc_id[aid] = doc["canonical_document_id"]

    # Separate creators from supporters
    creators   = [d for d in docs if eligibility_map.get(d["canonical_document_id"], {})
                  .get("eligible_for_story_creation")]
    supporters = [d for d in docs if not eligibility_map.get(d["canonical_document_id"], {})
                  .get("eligible_for_story_creation")]

    # ── Phase 1: Initialize one cluster per creator ────────────────────────────
    clusters: list[dict] = []
    doc_to_cluster: dict[str, int] = {}   # doc_id → cluster index

    for doc in creators:
        doc_id  = doc["canonical_document_id"]
        em      = entity_map.get(doc_id, {})
        ev      = event_type_map.get(doc_id, {})
        ci      = len(clusters)
        clusters.append({
            "_cluster_idx":       ci,
            "primary_document_id": doc_id,
            "member_document_ids": [doc_id],
            "primary_entities":    list(em.get("primary_entities", [])),
            "event_type":          ev.get("event_type", "unknown"),
            "first_seen_at":       doc.get("published_at"),
            "last_seen_at":        doc.get("published_at"),
            "match_signals":       {},
        })
        doc_to_cluster[doc_id] = ci

    # ── Phase 2: Merge creator clusters that belong to same story ─────────────
    # Merge rule: same primary entity + same event_type + within time window
    # Iterative: repeat until no more merges
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            if clusters[i] is None:
                continue
            for j in range(i + 1, len(clusters)):
                if clusters[j] is None:
                    continue
                ci, cj = clusters[i], clusters[j]

                same_event = ci["event_type"] == cj["event_type"] and ci["event_type"] != "unknown"
                time_ok    = _hours_apart(ci["first_seen_at"], cj["first_seen_at"]) <= _TIME_WINDOW_HOURS

                # Specific product/model entity overlap (not company-level)
                primary_em_i = entity_map.get(ci["primary_document_id"], {})
                primary_em_j = entity_map.get(cj["primary_document_id"], {})
                specific_ov = _specific_entity_overlap(primary_em_i, primary_em_j)

                should_merge = (
                    specific_ov >= 1 and same_event and time_ok
                )

                if should_merge:
                    # Merge j into i
                    ci["member_document_ids"].extend(cj["member_document_ids"])
                    ci["primary_entities"] = list(
                        set(ci["primary_entities"]) | set(cj["primary_entities"])
                    )
                    if cj["first_seen_at"] and (
                        not ci["first_seen_at"] or cj["first_seen_at"] < ci["first_seen_at"]
                    ):
                        ci["first_seen_at"] = cj["first_seen_at"]
                    if cj["last_seen_at"] and (
                        not ci["last_seen_at"] or cj["last_seen_at"] > ci["last_seen_at"]
                    ):
                        ci["last_seen_at"] = cj["last_seen_at"]
                    for mid in cj["member_document_ids"]:
                        doc_to_cluster[mid] = i
                    clusters[j] = None
                    merged = True

    active_clusters = [c for c in clusters if c is not None]

    # ── Phase 3: Attach supporters to existing clusters ────────────────────────

    for doc in supporters:
        doc_id   = doc["canonical_document_id"]
        doc_url  = (doc.get("canonical_url") or "").rstrip("/")
        em       = entity_map.get(doc_id, {})
        ev       = event_type_map.get(doc_id, {})
        doc_ents = set(em.get("primary_entities", []))
        doc_ev   = ev.get("event_type", "unknown")
        doc_date = doc.get("published_at")

        best_cluster_idx = None
        best_score       = 0

        for ci_idx, cluster_data in enumerate(active_clusters):
            score = 0

            # URL-link match: supporter's URL matches a cluster member's URL (strongest signal)
            url_linked = False
            for mid in cluster_data["member_document_ids"]:
                member_url = (docs_by_id.get(mid, {}).get("canonical_url") or "").rstrip("/")
                if doc_url and member_url and doc_url == member_url:
                    score += 10
                    url_linked = True
                    break

            # arxiv ID match
            doc_arxiv = _arxiv_id(doc_url)
            if doc_arxiv and not url_linked:
                for mid in cluster_data["member_document_ids"]:
                    mid_url = docs_by_id.get(mid, {}).get("canonical_url", "")
                    if _arxiv_id(mid_url) == doc_arxiv:
                        score += 10
                        url_linked = True
                        break

            if not url_linked:
                # Specific entity overlap (product/model — not company alone)
                em_doc = entity_map.get(doc_id, {})
                specific_ov = _specific_entity_overlap(
                    em_doc,
                    entity_map.get(cluster_data["primary_document_id"], {})
                )
                if specific_ov > 0:
                    score += specific_ov * 4

                # Same event type (only meaningful combined with entity match)
                if doc_ev == cluster_data["event_type"] and doc_ev not in ("unknown", "community_controversy"):
                    score += 2

                # Time proximity
                if _hours_apart(doc_date, cluster_data.get("first_seen_at")) <= _TIME_WINDOW_HOURS:
                    score += 1

            if score > best_score:
                best_score       = score
                best_cluster_idx = ci_idx

        # Require stronger signal to attach a supporter:
        # URL/arxiv link (10) or product+event+time overlap (>= 7)
        if best_score >= 7 and best_cluster_idx is not None:
            active_clusters[best_cluster_idx]["member_document_ids"].append(doc_id)
            active_clusters[best_cluster_idx]["primary_entities"] = list(
                set(active_clusters[best_cluster_idx]["primary_entities"]) | doc_ents
            )
            last = doc_date
            if last and (
                not active_clusters[best_cluster_idx]["last_seen_at"]
                or last > active_clusters[best_cluster_idx]["last_seen_at"]
            ):
                active_clusters[best_cluster_idx]["last_seen_at"] = last
            doc_to_cluster[doc_id] = active_clusters[best_cluster_idx]["_cluster_idx"]
        # else: supporter stays unattached (not a problem — some community signals are off-topic)

    # ── Phase 4: Build final StoryCluster records ──────────────────────────────
    story_clusters = []
    for cluster_data in active_clusters:
        primary_id = cluster_data["primary_document_id"]
        primary_doc = docs_by_id.get(primary_id, {})

        # Aggregate entities across all members
        all_companies: list[str] = []
        all_models:    list[str] = []
        all_products:  list[str] = []
        all_people:    list[str] = []
        all_topics:    list[dict] = []
        all_span_ids:  list[str] = []

        for mid in cluster_data["member_document_ids"]:
            em = entity_map.get(mid, {})
            for c in em.get("entities", {}).get("companies", []):
                if c not in all_companies:
                    all_companies.append(c)
            for m in em.get("entities", {}).get("models", []):
                if m not in all_models:
                    all_models.append(m)
            for p in em.get("entities", {}).get("products", []):
                if p not in all_products:
                    all_products.append(p)
            for pe in em.get("entities", {}).get("people", []):
                if pe not in all_people:
                    all_people.append(pe)
            for t in em.get("topics", []):
                if not any(x["topic_id"] == t["topic_id"] for x in all_topics):
                    all_topics.append(t)
            all_span_ids.extend(doc_span_index.get(mid, []))

        story_clusters.append({
            "story_id":              _story_id(primary_doc),
            "run_id":                primary_doc.get("run_id", ""),
            "story_identity": {
                "canonical_story_title": primary_doc.get("title", "Untitled"),
                "story_slug":            re.sub(r"[^a-z0-9]+", "-",
                                                primary_doc.get("title", "")[:50].lower()).strip("-"),
                "story_type":            cluster_data["event_type"],
                "story_status":          "active_news",
                "first_seen_at":         cluster_data.get("first_seen_at"),
                "last_seen_at":          cluster_data.get("last_seen_at"),
            },
            "cluster_members": {
                "canonical_document_ids":   cluster_data["member_document_ids"],
                "primary_document_id":      primary_id,
                "member_count":             len(cluster_data["member_document_ids"]),
                "source_span_ids":          all_span_ids,
            },
            "entities": {
                "companies": all_companies,
                "models":    all_models,
                "products":  all_products,
                "people":    all_people,
                "topics":    [t["label"] for t in sorted(all_topics, key=lambda x: -x.get("confidence", 0))[:5]],
            },
            "primary_entities":  cluster_data["primary_entities"],
            "event_type":        cluster_data["event_type"],
            "is_multi_source":   len(cluster_data["member_document_ids"]) > 1,
        })

    return story_clusters


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

    from pipelines.layer_3_story_processing.document_loader     import load
    from pipelines.layer_3_story_processing.exact_duplicate_detector import detect
    from pipelines.layer_3_story_processing.eligibility_filter  import filter_all
    from pipelines.layer_3_story_processing.entity_topic_mapper import map_all
    from pipelines.layer_3_story_processing.event_type_classifier import classify_all

    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer2_dir)
    all_docs   = loader_result["valid_docs"]
    doc_span_index = loader_result["doc_span_index"]

    dedup_result = detect(all_docs)
    deduped_docs = dedup_result["deduplicated_docs"]

    elig_results  = filter_all(deduped_docs)
    eligibility_map = {r["canonical_document_id"]: r["eligibility"] for r in elig_results}

    entity_results = map_all(deduped_docs, layer2_dir)
    entity_map = {r["canonical_document_id"]: r for r in entity_results}

    event_results  = classify_all(deduped_docs, entity_results)
    event_map = {r["canonical_document_id"]: r for r in event_results}

    clusters = cluster(
        docs=deduped_docs,
        eligibility_map=eligibility_map,
        entity_map=entity_map,
        event_type_map=event_map,
        doc_span_index=doc_span_index,
        duplicate_doc_ids=dedup_result["duplicate_doc_ids"],
    )

    multi = [c for c in clusters if c["is_multi_source"]]
    solo  = [c for c in clusters if not c["is_multi_source"]]

    print(f"\nStory Clusterer — {run_id}")
    print(f"  Input docs (deduped): {len(deduped_docs)}")
    print(f"  Story clusters:       {len(clusters)}")
    print(f"  Multi-source:         {len(multi)}")
    print(f"  Single-source:        {len(solo)}")

    print("\n  Multi-source clusters:")
    for c in multi:
        members = c["cluster_members"]["canonical_document_ids"]
        print(f"    [{c['event_type'][:20]}] {c['story_identity']['canonical_story_title'][:55]}")
        print(f"      members={len(members)} entities={c['entities']['companies']+c['entities']['models']}")
