"""
Mediastack Collector — Layer 1 Extraction

Fetches AI-related news from Mediastack API.
Requires API key in .env as MEDIASTACK_API.

NOTE: Mediastack free plan only supports HTTP (not HTTPS).

Usage:
    python mediastack_collector.py                     # default: "artificial intelligence"
    python mediastack_collector.py --query "AI startup"
"""

import os
import sys
import json
import hashlib
import argparse
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.parse import urlencode

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
from config.paths import RAW_MEDIASTACK, ensure_output_dirs
from dotenv import load_dotenv

load_dotenv()


# Free plan only supports HTTP, not HTTPS
MEDIASTACK_BASE = "http://api.mediastack.com/v1/news"


def fetch_news(query="artificial intelligence", max_results=10):
    """
    Fetch news articles from Mediastack API.
    
    Args:
        query:        Search keywords
        max_results:  Number of results (max 25 on free plan)
    
    Returns:
        List of article dicts in our standard document format.
    """
    api_key = os.getenv("MEDIASTACK_API")
    if not api_key:
        print("ERROR: MEDIASTACK_API key not found in .env")
        return []

    params = {
        "access_key": api_key,
        "keywords": query,
        "languages": "en",
        "categories": "technology",
        "limit": min(max_results, 25),
        "sort": "published_desc",
    }

    url = f"{MEDIASTACK_BASE}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "AI-Content-Creation/1.0"})
    
    response = urlopen(req, timeout=15)
    data = json.loads(response.read().decode("utf-8"))

    if "error" in data:
        print(f"Mediastack error: {data['error'].get('message', 'unknown')}")
        return []

    articles = []
    for raw in data.get("data", []):
        doc = parse_article(raw, query)
        articles.append(doc)

    return articles


def parse_article(raw, query_used):
    """Convert a Mediastack article into our standard document format."""
    
    title = raw.get("title", "") or ""
    url = raw.get("url", "") or ""
    source = raw.get("source", "") or ""
    author = raw.get("author", "") or ""
    published_at = raw.get("published_at", "") or ""
    description = raw.get("description", "") or ""
    category = raw.get("category", "") or ""
    country = raw.get("country", "") or ""
    language = raw.get("language", "en") or "en"
    image = raw.get("image", "") or ""

    content_hash = hashlib.sha256(f"mediastack:{url}:{title}".encode()).hexdigest()[:16]

    return {
        "document_id": f"mediastack_{content_hash}",
        "source_id": "mediastack_ai",
        "module": "mediastack_collector",
        "source_type": "tech_news_api",
        "trust_tier": 2,
        "title": title,
        "url": url,
        "published_at": published_at,
        "author": author,
        "publisher": source,
        "description": description,
        "raw_text": description,       # mediastack doesn't provide full content
        "category": category,
        "country": country,
        "language": language,
        "image_url": image,
        "query_used": query_used,
        "content_hash": content_hash,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def save_results(articles, query):
    """Save collected articles to output/layer_1_raw/mediastack/ as JSON."""
    ensure_output_dirs()

    date_str = datetime.now().strftime("%Y-%m-%d")
    query_slug = query.replace(" ", "_")[:30].lower()
    filename = f"{date_str}_{query_slug}.json"
    filepath = RAW_MEDIASTACK / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
# Test run
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch AI news from Mediastack")
    parser.add_argument("--query", default="artificial intelligence", help="Search keywords")
    parser.add_argument("--max", type=int, default=10, help="Max results (default: 10)")
    args = parser.parse_args()

    print(f"Fetching up to {args.max} articles from Mediastack for '{args.query}'...")
    articles = fetch_news(query=args.query, max_results=args.max)

    print(f"Collected {len(articles)} articles:\n")
    for i, a in enumerate(articles, 1):
        print(f"  {i}. [{a['publisher']}] {a['title'][:75]}")
        print(f"     Published: {a['published_at'][:16] if a['published_at'] else 'N/A'}")
        print(f"     URL: {a['url'][:80]}")
        print()

    filepath = save_results(articles, args.query)
    print(f"Saved to: {filepath}")
