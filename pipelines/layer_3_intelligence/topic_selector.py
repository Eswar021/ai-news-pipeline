"""
Topic Selector — Layer 3, Module 1

Takes ranked stories from Layer 2 and selects which story to cover.

Two modes:
  --manual   (default)  Show top stories, you pick by number
  --auto                LLM picks the most video-worthy story

After selection, it loads ALL source article texts for that cluster
from the deduplicated docs file. This "selected topic" file is what
the summarizer reads next.

Usage:
    python topic_selector.py                                       # manual pick
    python topic_selector.py --auto                                # LLM picks
    python topic_selector.py --pick 1                              # directly pick rank 1
    python topic_selector.py --ranked output/.../ranked_2026-05-08.json --pick 3
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import PROCESSED_DOCS, PROCESSED_RANKINGS, INTEL_OUTPUT, ensure_output_dirs
from config.llm_config import get_profile
from llm.llm_client import make_llm
from llm.llm_logger import call_llm


MODULE_NAME = "topic_selector"


def load_ranked_stories(ranked_path, top_n=10):
    """Load the top N ranked stories from Layer 2 output."""
    data = json.loads(Path(ranked_path).read_text(encoding="utf-8"))
    return data["stories"][:top_n]


def load_source_articles(docs_path, document_ids):
    """
    Load the full article data for each document_id in a cluster.
    Returns list of article dicts with their full raw_text.
    """
    all_docs = json.loads(Path(docs_path).read_text(encoding="utf-8"))
    docs_lookup = {d["document_id"]: d for d in all_docs}

    articles = []
    for did in document_ids:
        doc = docs_lookup.get(did)
        if doc:
            articles.append({
                "document_id": doc["document_id"],
                "title": doc.get("title", ""),
                "url": doc.get("url", ""),
                "publisher": doc.get("publisher", ""),
                "source_type": doc.get("source_type", ""),
                "trust_tier": doc.get("trust_tier", 3),
                "published_at": doc.get("published_at", ""),
                "raw_text": doc.get("raw_text", ""),
                "description": doc.get("description", ""),
                "community_score": doc.get("community_score", 0),
            })

    return articles


def display_stories(stories):
    """Print a numbered list of top stories for manual selection."""
    print(f"\n{'='*70}")
    print(f"  Top {len(stories)} Ranked Stories")
    print(f"{'='*70}\n")

    for s in stories:
        score_parts = s.get("score_breakdown", {})
        auth = score_parts.get("source_authority", {}).get("reason", "")[:30]
        print(f"  [{s['rank']:2}]  Score: {s['total_score']:3}/100  |  {s['source_count']} sources, {s['publisher_count']} publishers")
        print(f"       {s['best_title'][:65]}")
        print(f"       Authority: {auth}")
        ents = s.get("entities", {})
        companies = ents.get("companies", [])
        models = ents.get("models", [])
        if companies or models:
            print(f"       Entities: {', '.join(companies[:3])} {', '.join(models[:3])}")
        print()


def auto_select(stories):
    """
    Use the LLM to pick the most video-worthy story from the top candidates.
    Returns the selected story dict and the LLM's reasoning.
    """
    profile = get_profile(MODULE_NAME)

    # Build the prompt with story summaries
    stories_text = ""
    for s in stories[:10]:
        ents = s.get("entities", {})
        companies = ", ".join(ents.get("companies", []))
        models = ", ".join(ents.get("models", []))
        stories_text += f"""
Story #{s['rank']} — Score: {s['total_score']}/100
Title: {s['best_title']}
Sources: {s['source_count']} from {s['publisher_count']} publishers
Companies: {companies or 'none'}
Models/Products: {models or 'none'}
Source types: {', '.join(s.get('source_types_present', []))}
Trust tiers: {s['trust_tiers_present']}
---
"""

    prompt = f"""You are a YouTube content strategist for an AI-focused news channel.

Below are today's top {len(stories[:10])} AI stories, ranked by our system. Pick the ONE story that would make the best YouTube video.

Consider:
- Audience interest: Will AI enthusiasts, developers, and tech-curious people click on this?
- Depth: Is there enough substance for a 5-10 minute video?
- Freshness: Is this genuinely new, not just a rehash?
- Visual potential: Can this be demonstrated or shown on screen?
- Credibility: Does it have official sources, not just rumors?

{stories_text}

Respond in this exact format:
PICK: [story number]
REASON: [2-3 sentences explaining why this story is the best video topic]
HEADLINE: [suggested video title that would get clicks, max 60 chars]
"""

    llm = make_llm(**profile)
    response_text = call_llm(llm, prompt, module=MODULE_NAME, metadata={"top_n": len(stories[:10])})

    # Parse the response
    pick = 1
    reason = ""
    headline = ""

    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("PICK:"):
            try:
                pick = int(line.replace("PICK:", "").strip().lstrip("#"))
            except ValueError:
                pick = 1
        elif line.startswith("REASON:"):
            reason = line.replace("REASON:", "").strip()
        elif line.startswith("HEADLINE:"):
            headline = line.replace("HEADLINE:", "").strip()

    # Find the matching story
    selected = None
    for s in stories:
        if s["rank"] == pick:
            selected = s
            break

    if not selected:
        selected = stories[0]

    return selected, reason, headline, response_text


def build_selected_topic(story, articles, reason="", headline="", selection_mode="manual"):
    """
    Build the selected_topic output document.
    This is what the summarizer reads.
    """
    return {
        "selected_at": datetime.now().isoformat(),
        "selection_mode": selection_mode,
        "selected_rank": story["rank"],
        "selected_score": story["total_score"],
        "topic": story["topic"],
        "best_title": story["best_title"],
        "headline_suggestion": headline,
        "selection_reason": reason,
        "score_breakdown": story.get("score_breakdown", {}),
        "entities": story.get("entities", {}),
        "source_count": story["source_count"],
        "publisher_count": story["publisher_count"],
        "source_articles": articles,
    }


def save_selected(selected_topic, date_str=None):
    """Save selected topic to output/layer_3_intelligence/"""
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    filepath = INTEL_OUTPUT / f"selected_topic_{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(selected_topic, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Select which story to cover")
    parser.add_argument("--ranked", help="Path to ranked JSON (default: today's)")
    parser.add_argument("--docs", help="Path to deduplicated docs JSON (default: today's)")
    parser.add_argument("--auto", action="store_true", help="LLM auto-selects the story")
    parser.add_argument("--pick", type=int, help="Directly pick a story by rank number")
    parser.add_argument("--top", type=int, default=10, help="Show top N stories (default: 10)")
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")
    ranked_path = args.ranked or PROCESSED_RANKINGS / f"ranked_{date_str}.json"
    docs_path   = args.docs or PROCESSED_DOCS / f"deduplicated_{date_str}.json"

    stories = load_ranked_stories(ranked_path, top_n=args.top)

    if args.auto:
        # LLM picks
        print(f"LLM auto-selecting from top {len(stories)} stories...")
        profile = get_profile(MODULE_NAME)
        print(f"Using: {profile['provider']}/{profile['model']}")
        selected_story, reason, headline, raw_response = auto_select(stories)
        print(f"\nLLM picked #{selected_story['rank']}: {selected_story['best_title'][:60]}")
        print(f"Reason: {reason}")
        print(f"Headline: {headline}")
        selection_mode = "auto"

    elif args.pick:
        # Direct pick
        selected_story = None
        for s in stories:
            if s["rank"] == args.pick:
                selected_story = s
                break
        if not selected_story:
            print(f"No story with rank {args.pick}")
            sys.exit(1)
        reason = f"Manually selected rank {args.pick}"
        headline = selected_story["best_title"][:60]
        selection_mode = "manual"
        print(f"Selected #{args.pick}: {selected_story['best_title'][:60]}")

    else:
        # Interactive manual pick
        display_stories(stories)
        choice = input("Pick a story number (1-10): ").strip()
        try:
            pick_rank = int(choice)
        except ValueError:
            pick_rank = 1

        selected_story = None
        for s in stories:
            if s["rank"] == pick_rank:
                selected_story = s
                break
        if not selected_story:
            selected_story = stories[0]

        reason = f"Manually selected rank {pick_rank}"
        headline = selected_story["best_title"][:60]
        selection_mode = "manual"

    # Load full source articles for the selected cluster
    print(f"\nLoading source articles for cluster...")
    articles = load_source_articles(docs_path, selected_story["document_ids"])

    total_text = sum(len(a.get("raw_text", "")) for a in articles)
    print(f"  {len(articles)} articles loaded, {total_text:,} chars of source text")

    for a in articles:
        text_len = len(a.get("raw_text", ""))
        print(f"    [{a['source_type'][:15]:15}] {text_len:6} chars | {a['title'][:50]}")

    # Build and save
    selected_topic = build_selected_topic(
        story=selected_story,
        articles=articles,
        reason=reason,
        headline=headline,
        selection_mode=selection_mode,
    )

    filepath = save_selected(selected_topic, date_str)
    print(f"\nSaved to: {filepath}")
    print(f"\nNext: python pipelines/layer_3_intelligence/summarizer.py")
