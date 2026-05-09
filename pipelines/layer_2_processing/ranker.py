"""
Ranker — Layer 2, Module 4

Scores each cluster across 5 dimensions (max 100 points total):
  1. Source Authority    (max 30) — best trust tier in cluster
  2. Source Coverage     (max 25) — distinct publishers covering the story
  3. Community Engagement(max 20) — HN upvotes, GitHub stars, comments
  4. Entity Significance (max 15) — major AI company or product involved
  5. Content Richness    (max 10) — variety of source types

Output: ranked_YYYY-MM-DD.json — sorted story clusters with scores + breakdown.
This is the FINAL output of Layer 2, consumed by Layer 3.

Usage:
    python ranker.py                                           # uses today's files
    python ranker.py --clusters output/.../clusters_2026-05-08.json --docs output/.../deduplicated_2026-05-08.json
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import PROCESSED_DOCS, PROCESSED_CLUSTERS, PROCESSED_RANKINGS, ensure_output_dirs


# ── Entity lists for scoring ──────────────────────────────────────────────────

MAJOR_COMPANIES = {
    "openai", "anthropic", "google", "deepmind", "google deepmind",
    "meta", "microsoft", "nvidia", "apple", "amazon", "aws",
}

KNOWN_PRODUCTS = {
    "gpt-5", "gpt-4", "gpt-4o", "chatgpt", "o1", "o3",
    "claude", "claude opus", "claude sonnet", "claude haiku",
    "gemini", "gemma", "llama", "mistral", "mixtral",
    "dall-e", "midjourney", "stable diffusion", "sora",
    "copilot", "grok", "deepseek", "qwen", "phi",
    "alphaevolve", "alphafold",
}


# ── Dimension scorers ─────────────────────────────────────────────────────────

def score_source_authority(cluster, docs_lookup):
    """
    Dimension 1: Source Authority (max 30)
    What's the most trustworthy source covering this story?
    Checks the BEST (lowest number) trust tier in the cluster.
    """
    best_tier = 99
    for doc_id in cluster["document_ids"]:
        doc = docs_lookup.get(doc_id)
        if doc:
            tier = doc.get("trust_tier", 3)
            if tier < best_tier:
                best_tier = tier

    if best_tier <= 1:
        return 30, "Tier 1 — official company source"
    elif best_tier <= 1.5:
        return 20, "Tier 1.5 — research paper"
    elif best_tier <= 2:
        return 10, "Tier 2 — established media"
    else:
        return 0, "Tier 3 only — community signals"


def score_source_coverage(cluster):
    """
    Dimension 2: Source Coverage (max 25)
    How many independent publishers covered this story?
    """
    count = cluster.get("publisher_count", 1)

    if count >= 5:
        return 25, f"{count} publishers"
    elif count >= 3:
        return 15, f"{count} publishers"
    elif count >= 2:
        return 10, f"{count} publishers"
    else:
        return 0, "single publisher"


def score_community_engagement(cluster, docs_lookup):
    """
    Dimension 3: Community Engagement (max 20)
    Are developers/people actually talking about this?
    Looks at max community_score and comment_count across all docs.
    """
    max_score = 0
    max_comments = 0

    for doc_id in cluster["document_ids"]:
        doc = docs_lookup.get(doc_id)
        if doc:
            cs = doc.get("community_score", 0) or 0
            cc = doc.get("comment_count", 0) or 0
            if cs > max_score:
                max_score = cs
            if cc > max_comments:
                max_comments = cc

    points = 0
    reason_parts = []

    # Main engagement score
    if max_score > 500:
        points += 15
        reason_parts.append(f"score {max_score} > 500")
    elif max_score > 200:
        points += 10
        reason_parts.append(f"score {max_score} > 200")
    elif max_score > 50:
        points += 5
        reason_parts.append(f"score {max_score} > 50")
    else:
        reason_parts.append(f"low engagement (score {max_score})")

    # Comment bonus
    if max_comments > 100:
        points += 5
        reason_parts.append(f"comments {max_comments} > 100")

    return min(points, 20), ", ".join(reason_parts)


def score_entity_significance(cluster):
    """
    Dimension 4: Entity Significance (max 15)
    Is a major company or known product involved?
    """
    companies = {c.lower() for c in cluster.get("entities", {}).get("companies", [])}
    models = {m.lower() for m in cluster.get("entities", {}).get("models", [])}

    # Check major companies
    if companies & MAJOR_COMPANIES:
        matched = companies & MAJOR_COMPANIES
        return 15, f"major company: {', '.join(matched)}"

    # Check known products
    if models & KNOWN_PRODUCTS:
        matched = models & KNOWN_PRODUCTS
        return 10, f"known product: {', '.join(matched)}"

    # Any entity at all?
    if companies or models:
        return 5, f"other entity: {', '.join(companies | models)}"

    return 0, "no recognized entity"


def score_content_richness(cluster):
    """
    Dimension 5: Content Richness (max 10)
    What variety of source types does this cluster have?
    """
    source_types = set(cluster.get("source_types_present", []))

    points = 0
    present = []

    if "official_company_blog" in source_types:
        points += 4
        present.append("blog")
    if "research_paper" in source_types:
        points += 3
        present.append("paper")
    if "community_signal" in source_types:
        points += 2
        present.append("community")
    if "tech_news_api" in source_types:
        points += 2
        present.append("news")
    if "video_or_podcast" in source_types:
        points += 2
        present.append("video")

    capped = min(points, 10)
    return capped, f"types: {', '.join(present)}" if present else "no source types"


# ── Main ranker ───────────────────────────────────────────────────────────────

def rank_clusters(clusters, docs):
    """
    Score all clusters across all 5 dimensions and sort by total score.
    Returns ranked list with score breakdowns.
    """
    # Build lookup for fast doc access
    docs_lookup = {d["document_id"]: d for d in docs}

    ranked = []
    for cluster in clusters:
        d1_score, d1_reason = score_source_authority(cluster, docs_lookup)
        d2_score, d2_reason = score_source_coverage(cluster)
        d3_score, d3_reason = score_community_engagement(cluster, docs_lookup)
        d4_score, d4_reason = score_entity_significance(cluster)
        d5_score, d5_reason = score_content_richness(cluster)

        total = d1_score + d2_score + d3_score + d4_score + d5_score

        result = {
            **cluster,
            "total_score": total,
            "score_breakdown": {
                "source_authority":     {"score": d1_score, "max": 30, "reason": d1_reason},
                "source_coverage":      {"score": d2_score, "max": 25, "reason": d2_reason},
                "community_engagement": {"score": d3_score, "max": 20, "reason": d3_reason},
                "entity_significance":  {"score": d4_score, "max": 15, "reason": d4_reason},
                "content_richness":     {"score": d5_score, "max": 10, "reason": d5_reason},
            }
        }
        ranked.append(result)

    # Sort by total score descending
    ranked.sort(key=lambda c: c["total_score"], reverse=True)

    # Assign ranks
    for i, r in enumerate(ranked):
        r["rank"] = i + 1

    return ranked


def save_ranked(ranked, date_str=None):
    """Save final ranked output — this is the FINAL Layer 2 output."""
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    filepath = PROCESSED_RANKINGS / f"ranked_{date_str}.json"

    output = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "total_stories": len(ranked),
        "stories": ranked,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rank story clusters by importance")
    parser.add_argument("--clusters", help="Path to clusters JSON")
    parser.add_argument("--docs", help="Path to deduplicated docs JSON")
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")

    clusters_path = args.clusters or PROCESSED_CLUSTERS / f"clusters_{date_str}.json"
    docs_path     = args.docs or PROCESSED_DOCS / f"deduplicated_{date_str}.json"

    print(f"Loading clusters: {clusters_path}")
    print(f"Loading docs:     {docs_path}")

    clusters = json.loads(Path(clusters_path).read_text(encoding="utf-8"))
    docs     = json.loads(Path(docs_path).read_text(encoding="utf-8"))

    ranked = rank_clusters(clusters, docs)

    print(f"\nRanked {len(ranked)} stories\n")
    print(f"{'Rank':<5} {'Score':<6} {'Srcs':<5} {'Topic':<50} {'Authority'}")
    print("-" * 100)
    for r in ranked[:15]:
        auth = r["score_breakdown"]["source_authority"]["reason"][:25]
        print(f"  {r['rank']:<3}  {r['total_score']:<5} {r['source_count']:<4}  {r['topic'][:48]:<48}  {auth}")

    filepath = save_ranked(ranked, date_str)
    print(f"\nSaved to: {filepath}")
