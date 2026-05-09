"""
Newsdata.io Collector — Layer 1 Extraction

Fetches AI-related news from Newsdata.io API.
Requires API key in .env as NEWSDATA_API.

Usage:
    python newsdata_collector.py                       # default: "artificial intelligence", 10 results
    python newsdata_collector.py --query "generative AI"
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
from config.paths import RAW_NEWSDATA, ensure_output_dirs
from dotenv import load_dotenv

load_dotenv()


NEWSDATA_BASE = "https://newsdata.io/api/1/latest"


def fetch_news(query="artificial intelligence", max_results=10):
    """
    Fetch news articles from Newsdata.io.
    
    Args:
        query:        Search query string
        max_results:  Number of articles to return (API returns up to 10 per request on free plan)
    
    Returns:
        List of article dicts in our standard document format.
    """
    api_key = os.getenv("NEWSDATA_API")
    if not api_key:
        print("ERROR: NEWSDATA_API key not found in .env")
        return []

    params = {
        "apikey": api_key,
        "q": query,
        "language": "en",
        "size": min(max_results, 10),   # free plan max 10 per request
        # NOTE: full_content=1 is a paid feature — causes 422 on free plan
    }

    url = f"{NEWSDATA_BASE}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "AI-Content-Creation/1.0"})
    
    response = urlopen(req, timeout=15)
    data = json.loads(response.read().decode("utf-8"))

    if data.get("status") != "success":
        print(f"Newsdata error: {data.get('results', {}).get('message', 'unknown')}")
        return []

    articles = []
    for raw in data.get("results", []):
        doc = parse_article(raw, query)
        articles.append(doc)

    return articles


def parse_article(raw, query_used):
    """Convert a Newsdata article into our standard document format."""
    
    title = raw.get("title", "") or ""
    url = raw.get("link", "") or ""
    source_name = raw.get("source_name", "") or ""
    source_url = raw.get("source_url", "") or ""
    creator = raw.get("creator") or []
    author = ", ".join(creator) if isinstance(creator, list) else str(creator)
    published_at = raw.get("pubDate", "") or ""
    description = raw.get("description", "") or ""
    content = raw.get("content", "") or ""
    categories = raw.get("category") or []
    keywords = raw.get("keywords") or []
    country = raw.get("country") or []
    language = raw.get("language", "en") or "en"
    image_url = raw.get("image_url", "") or ""

    content_hash = hashlib.sha256(f"newsdata:{url}:{title}".encode()).hexdigest()[:16]

    return {
        "document_id": f"newsdata_{content_hash}",
        "source_id": "newsdata_ai",
        "module": "newsdata_collector",
        "source_type": "tech_news_api",
        "trust_tier": 2,
        "title": title,
        "url": url,
        "published_at": published_at,
        "author": author,
        "publisher": source_name,
        "publisher_url": source_url,
        "description": description,
        "raw_text": content or description,
        "categories": categories,
        "keywords": keywords,
        "country": country,
        "language": language,
        "image_url": image_url,
        "query_used": query_used,
        "content_hash": content_hash,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def save_results(articles, query):
    """Save collected articles to output/layer_1_raw/newsdata/ as JSON."""
    ensure_output_dirs()

    date_str = datetime.now().strftime("%Y-%m-%d")
    query_slug = query.replace(" ", "_")[:30].lower()
    filename = f"{date_str}_{query_slug}.json"
    filepath = RAW_NEWSDATA / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
# Test run
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch AI news from Newsdata.io")
    parser.add_argument("--query", default="artificial intelligence", help="Search query")
    parser.add_argument("--max", type=int, default=10, help="Max results (default: 10)")
    args = parser.parse_args()

    print(f"Fetching up to {args.max} articles from Newsdata.io for '{args.query}'...")
    articles = fetch_news(query=args.query, max_results=args.max)

    print(f"Collected {len(articles)} articles:\n")
    for i, a in enumerate(articles, 1):
        print(f"  {i}. [{a['publisher']}] {a['title'][:75]}")
        print(f"     Published: {a['published_at'][:16] if a['published_at'] else 'N/A'}")
        print(f"     URL: {a['url'][:80]}")
        print()

    filepath = save_results(articles, args.query)
    print(f"Saved to: {filepath}")
