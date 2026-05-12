"""
Hacker News Collector — Layer 1 Extraction

Fetches top AI-related stories from Hacker News using their public Firebase API.
No API key required. Filters stories by AI-related keywords.

Usage:
    python hackernews_collector.py                     # default: top 30, filter AI keywords
    python hackernews_collector.py --max 50
    python hackernews_collector.py --type new           # "top", "new", or "best"
"""

import sys
import json
import hashlib
import argparse
from datetime import datetime, timezone
from config.time_utils import now_project
from config.time_utils import now_project_iso
from urllib.request import urlopen, Request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
from config.paths import RAW_HACKERNEWS, ensure_output_dirs


HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

# Keywords to filter AI-related stories
AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "gpt", "openai", "anthropic", "claude",
    "gemini", "google deepmind", "meta ai", "llama", "mistral",
    "transformer", "neural network", "diffusion", "stable diffusion",
    "midjourney", "chatgpt", "copilot", "ai agent", "rag",
    "embedding", "fine-tuning", "fine tuning", "nvidia", "cuda",
    "hugging face", "huggingface", "langchain", "vector database",
    "generative ai", "gen ai", "foundation model", "ai safety",
    "alignment", "ai regulation", "computer vision", "nlp",
    "natural language", "reinforcement learning", "robotics",
]


def fetch_story_ids(story_type="top"):
    """
    Fetch story IDs from Hacker News.
    
    Args:
        story_type: "top", "new", or "best"
    
    Returns:
        List of story IDs (ints).
    """
    url = f"{HN_API_BASE}/{story_type}stories.json"
    req = Request(url, headers={"User-Agent": "AI-Content-Creation/1.0"})
    response = urlopen(req, timeout=15)
    return json.loads(response.read().decode("utf-8"))


def fetch_item(item_id):
    """Fetch a single HN item (story, comment, etc.) by ID."""
    url = f"{HN_API_BASE}/item/{item_id}.json"
    req = Request(url, headers={"User-Agent": "AI-Content-Creation/1.0"})
    response = urlopen(req, timeout=10)
    return json.loads(response.read().decode("utf-8"))


def is_ai_related(story):
    """Check if a story title/url contains AI-related keywords."""
    title = (story.get("title") or "").lower()
    url = (story.get("url") or "").lower()
    text = f"{title} {url}"
    return any(kw in text for kw in AI_KEYWORDS)


def fetch_ai_stories(story_type="top", max_stories=30, scan_depth=100):
    """
    Fetch AI-related stories from Hacker News.
    
    Args:
        story_type:  "top", "new", or "best"
        max_stories: Max AI stories to return
        scan_depth:  How many top stories to scan for AI keywords
    
    Returns:
        List of story dicts in our standard document format.
    """
    story_ids = fetch_story_ids(story_type)
    story_ids = story_ids[:scan_depth]

    ai_stories = []
    for sid in story_ids:
        story = fetch_item(sid)
        if story is None:
            continue
        if story.get("type") != "story":
            continue
        if not is_ai_related(story):
            continue

        doc = parse_story(story)
        ai_stories.append(doc)

        if len(ai_stories) >= max_stories:
            break

    return ai_stories


def parse_story(story):
    """Convert a HN story into our standard document format."""
    
    title = story.get("title", "")
    url = story.get("url", "")
    hn_url = f"https://news.ycombinator.com/item?id={story['id']}"
    score = story.get("score", 0)
    comment_count = story.get("descendants", 0)
    author = story.get("by", "")
    timestamp = story.get("time", 0)
    text = story.get("text", "")  # for Ask HN / Show HN posts
    
    published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp else ""
    content_hash = hashlib.sha256(f"hn:{story['id']}:{title}".encode()).hexdigest()[:16]

    return {
        "document_id": f"hn_{story['id']}",
        "source_id": "hackernews_ai",
        "module": "hackernews_collector",
        "source_type": "community_signal",
        "trust_tier": 3,
        "title": title,
        "url": url or hn_url,            # external URL if exists, else HN discussion
        "hn_discussion_url": hn_url,
        "published_at": published_at,
        "author": author,
        "raw_text": text,                 # text content (for self-posts)
        "score": score,
        "comment_count": comment_count,
        "signal_type": "developer_discussion",
        "content_hash": content_hash,
        "collected_at": now_project_iso(),
    }


def save_results(stories, story_type):
    """Save collected stories to output/layer_1_raw/hackernews/ as JSON."""
    ensure_output_dirs()

    date_str = now_project().strftime("%Y-%m-%d")
    filename = f"{date_str}_{story_type}.json"
    filepath = RAW_HACKERNEWS / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(stories, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
# Test run
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch AI stories from Hacker News")
    parser.add_argument("--type", default="top", choices=["top", "new", "best"], help="Story type")
    parser.add_argument("--max", type=int, default=15, help="Max AI stories to return (default: 15)")
    parser.add_argument("--scan", type=int, default=100, help="How many stories to scan (default: 100)")
    args = parser.parse_args()

    print(f"Scanning top {args.scan} HN {args.type} stories for AI content...")
    stories = fetch_ai_stories(story_type=args.type, max_stories=args.max, scan_depth=args.scan)

    print(f"Found {len(stories)} AI-related stories:\n")
    for i, s in enumerate(stories, 1):
        print(f"  {i}. [{s['score']}⬆ {s['comment_count']}💬] {s['title'][:75]}")
        print(f"     URL: {s['url'][:80]}")
        print(f"     HN:  {s['hn_discussion_url']}")
        print()

    filepath = save_results(stories, args.type)
    print(f"Saved to: {filepath}")
