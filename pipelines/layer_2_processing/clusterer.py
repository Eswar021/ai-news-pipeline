"""
Clusterer — Layer 2, Module 3

Groups deduplicated documents that are about the same story.

Clustering logic:
  For each pair of documents, they belong in the same cluster if at least 2 of these 3 are true:
    1. Share 2+ entity names (company or model)
    2. Published within 48 hours of each other
    3. Title word overlap > 50%

Algorithm: single-pass greedy. For each doc, check against existing clusters.
If it matches any doc in a cluster → add to that cluster. Otherwise → new cluster.

Each cluster gets a topic label = the most common entities + most frequent title words.

Usage:
    python clusterer.py                                        # uses today's deduplicated file
    python clusterer.py --input output/layer_2_processed/documents/deduplicated_2026-05-08.json
"""

import sys
import json
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import PROCESSED_DOCS, PROCESSED_CLUSTERS, ensure_output_dirs


# ── Matching helpers ──────────────────────────────────────────────────────────

def _entity_set(doc):
    """Get combined set of company + model entities from a document."""
    entities = doc.get("entities", {})
    combined = set()
    for name in entities.get("companies", []):
        combined.add(name.lower())
    for name in entities.get("models", []):
        combined.add(name.lower())
    return combined


def _title_words(title):
    """Extract meaningful words from title (3+ chars, lowercase)."""
    return set(re.findall(r"[a-zA-Z]{3,}", title.lower()))


def _parse_date(date_str):
    """Parse ISO date string to datetime. Returns None if unparseable."""
    if not date_str:
        return None
    # Handle various ISO formats
    for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str[:26].replace("+00:00", "+0000").rstrip("Z"), fmt.rstrip("%z"))
        except ValueError:
            continue
    return None


def should_cluster(doc_a, doc_b):
    """
    Check if two documents should be in the same cluster.
    Returns True if at least 2 of 3 conditions are met.
    """
    conditions_met = 0

    # Condition 1: Share 2+ entities
    ents_a = _entity_set(doc_a)
    ents_b = _entity_set(doc_b)
    shared_entities = ents_a & ents_b
    if len(shared_entities) >= 2:
        conditions_met += 1

    # Condition 2: Published within 48 hours
    date_a = _parse_date(doc_a.get("published_at", ""))
    date_b = _parse_date(doc_b.get("published_at", ""))
    if date_a and date_b:
        diff = abs((date_a - date_b).total_seconds())
        if diff <= 48 * 3600:
            conditions_met += 1
    else:
        # If we can't parse dates, give benefit of the doubt
        conditions_met += 1

    # Condition 3: Title word overlap > 50%
    words_a = _title_words(doc_a.get("title", ""))
    words_b = _title_words(doc_b.get("title", ""))
    if words_a and words_b:
        shared_words = words_a & words_b
        smaller = min(len(words_a), len(words_b))
        overlap = len(shared_words) / smaller if smaller > 0 else 0
        if overlap > 0.50:
            conditions_met += 1

    return conditions_met >= 2


# ── Cluster builder ───────────────────────────────────────────────────────────

def build_clusters(docs):
    """
    Greedy single-pass clustering.
    For each doc, check against existing clusters. If it matches any member → join.
    """
    clusters = []  # each cluster is a list of doc indices

    for i, doc in enumerate(docs):
        placed = False
        for cluster in clusters:
            # Check if this doc matches ANY doc already in the cluster
            for member_idx in cluster:
                if should_cluster(doc, docs[member_idx]):
                    cluster.append(i)
                    placed = True
                    break
            if placed:
                break

        if not placed:
            clusters.append([i])

    return clusters


def label_cluster(docs, doc_indices):
    """
    Generate a topic label for a cluster from entity frequency + title words.
    """
    # Count entity mentions across all docs in the cluster
    entity_counter = Counter()
    for idx in doc_indices:
        doc = docs[idx]
        for name in doc.get("entities", {}).get("companies", []):
            entity_counter[name] += 1
        for name in doc.get("entities", {}).get("models", []):
            entity_counter[name] += 1

    # Count title words
    word_counter = Counter()
    for idx in doc_indices:
        words = _title_words(docs[idx].get("title", ""))
        word_counter.update(words)

    # Remove generic words
    generic = {"the", "for", "and", "with", "new", "how", "what", "why", "can", "from",
               "that", "this", "are", "not", "all", "has", "have", "its", "but", "was",
               "will", "now", "your", "you", "about", "into", "more", "show", "using"}
    for g in generic:
        word_counter.pop(g, None)

    # Build label: top entities + top words
    top_entities = [e for e, _ in entity_counter.most_common(3)]
    top_words = [w for w, _ in word_counter.most_common(5) if w.lower() not in {e.lower() for e in top_entities}]

    if top_entities:
        label = " ".join(top_entities)
        if top_words:
            label += ": " + " ".join(top_words[:3])
    else:
        label = " ".join(top_words[:5]) if top_words else "unlabeled"

    return label


def format_clusters(docs, raw_clusters):
    """
    Convert raw cluster indices into structured output format.
    """
    formatted = []

    for i, doc_indices in enumerate(raw_clusters):
        cluster_docs = [docs[idx] for idx in doc_indices]

        # Collect all entities
        all_companies = set()
        all_models = set()
        for d in cluster_docs:
            all_companies.update(d.get("entities", {}).get("companies", []))
            all_models.update(d.get("entities", {}).get("models", []))

        # Trust tiers present
        trust_tiers = sorted(set(d.get("trust_tier", 3) for d in cluster_docs))

        # Source types present
        source_types = sorted(set(d.get("source_type", "") for d in cluster_docs))

        # Best title = the one from the highest-trust source, or most content
        best_doc = sorted(cluster_docs, key=lambda d: (d.get("trust_tier", 3), -len(d.get("raw_text", ""))))[0]

        # Earliest publication date
        dates = [d.get("published_at", "") for d in cluster_docs if d.get("published_at")]
        earliest = min(dates) if dates else ""

        # Distinct publishers
        publishers = sorted(set(d.get("publisher", "") for d in cluster_docs if d.get("publisher")))

        cluster = {
            "cluster_id": f"cluster_{i+1:03d}",
            "topic": label_cluster(docs, doc_indices),
            "source_count": len(cluster_docs),
            "publisher_count": len(publishers),
            "publishers": publishers,
            "entities": {
                "companies": sorted(all_companies),
                "models": sorted(all_models),
            },
            "trust_tiers_present": trust_tiers,
            "source_types_present": source_types,
            "earliest_published": earliest,
            "best_title": best_doc.get("title", ""),
            "document_ids": [d["document_id"] for d in cluster_docs],
        }

        formatted.append(cluster)

    # Sort by source_count descending (most covered stories first — ranking happens in ranker.py)
    formatted.sort(key=lambda c: c["source_count"], reverse=True)

    # Re-number after sorting
    for i, c in enumerate(formatted):
        c["cluster_id"] = f"cluster_{i+1:03d}"

    return formatted


def save_clusters(clusters, date_str=None):
    """Save clusters to output/layer_2_processed/clusters/"""
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    filepath = PROCESSED_CLUSTERS / f"clusters_{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(clusters, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cluster deduplicated documents by story")
    parser.add_argument("--input", help="Path to deduplicated JSON (default: today's)")
    args = parser.parse_args()

    if args.input:
        input_path = args.input
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        input_path = PROCESSED_DOCS / f"deduplicated_{date_str}.json"

    print(f"Loading: {input_path}")
    docs = json.loads(Path(input_path).read_text(encoding="utf-8"))
    print(f"Input: {len(docs)} documents")

    raw_clusters = build_clusters(docs)
    formatted = format_clusters(docs, raw_clusters)

    multi_source = [c for c in formatted if c["source_count"] > 1]
    single_source = [c for c in formatted if c["source_count"] == 1]

    print(f"\nClustering results:")
    print(f"  Total clusters:        {len(formatted)}")
    print(f"  Multi-source stories:  {len(multi_source)}")
    print(f"  Single-source items:   {len(single_source)}")

    print(f"\n  Top clusters (by source count):")
    for c in formatted[:10]:
        print(f"    [{c['source_count']} sources, {c['publisher_count']} publishers] {c['topic'][:55]}")
        print(f"      Best title: {c['best_title'][:65]}")
        print(f"      Tiers: {c['trust_tiers_present']}  Types: {c['source_types_present']}")
        print()

    filepath = save_clusters(formatted)
    print(f"Saved to: {filepath}")
