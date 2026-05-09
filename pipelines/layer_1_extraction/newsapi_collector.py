"""
NewsAPI.org Collector — Layer 1 Extraction

Fetches AI-related news articles from NewsAPI.org.
Requires API key in .env as NewsAPI.

Usage:
    python newsapi_collector.py                        # default: "artificial intelligence", 10 results
    python newsapi_collector.py --query "OpenAI" --max 20
    python newsapi_collector.py --query "LLM AI agent" --sort publishedAt
"""

import os
import sys
import json
import hashlib
import argparse
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.parse import urlencode

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
from config.paths import RAW_NEWSAPI, ensure_output_dirs
from dotenv import load_dotenv

load_dotenv()


NEWSAPI_BASE = "https://newsapi.org/v2"


def fetch_news(query="artificial intelligence", max_results=10, sort_by="publishedAt", days_back=2):
    """
    Fetch news articles from NewsAPI /everything endpoint.
    
    Args:
        query:        Search query string
        max_results:  Number of articles (max 100 on free plan)
        sort_by:      "publishedAt", "relevancy", or "popularity"
        days_back:    How many days back to search
    
    Returns:
        List of article dicts in our standard document format.
    """
    api_key = os.getenv("NewsAPI")
    if not api_key:
        print("ERROR: NewsAPI key not found in .env")
        return []

    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params = {
        "q": query,
        "from": from_date,
        "sortBy": sort_by,
        "pageSize": min(max_results, 100),
        "language": "en",
        "apiKey": api_key,
    }

    url = f"{NEWSAPI_BASE}/everything?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "AI-Content-Creation/1.0"})
    
    response = urlopen(req, timeout=15)
    data = json.loads(response.read().decode("utf-8"))

    if data.get("status") != "ok":
        print(f"NewsAPI error: {data.get('message', 'unknown')}")
        return []

    articles = []
    for raw in data.get("articles", []):
        doc = parse_article(raw, query)
        articles.append(doc)

    return articles


def parse_article(raw, query_used):
    """Convert a NewsAPI article into our standard document format."""
    
    title = raw.get("title", "") or ""
    url = raw.get("url", "") or ""
    source_name = (raw.get("source") or {}).get("name", "")
    author = raw.get("author", "") or ""
    published_at = raw.get("publishedAt", "") or ""
    description = raw.get("description", "") or ""
    content = raw.get("content", "") or ""  # often truncated on free plan

    content_hash = hashlib.sha256(f"newsapi:{url}:{title}".encode()).hexdigest()[:16]

    return {
        "document_id": f"newsapi_{content_hash}",
        "source_id": "newsapi_ai",
        "module": "newsapi_collector",
        "source_type": "tech_news_api",
        "trust_tier": 2,
        "title": title,
        "url": url,
        "published_at": published_at,
        "author": author,
        "publisher": source_name,
        "description": description,
        "raw_text": content or description,   # content is truncated, fallback to description
        "query_used": query_used,
        "language": "en",
        "content_hash": content_hash,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def save_results(articles, query):
    """Save collected articles to output/layer_1_raw/newsapi/ as JSON."""
    ensure_output_dirs()

    date_str = datetime.now().strftime("%Y-%m-%d")
    query_slug = query.replace(" ", "_")[:30].lower()
    filename = f"{date_str}_{query_slug}.json"
    filepath = RAW_NEWSAPI / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
# Test run
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch AI news from NewsAPI.org")
    parser.add_argument("--query", default="artificial intelligence", help="Search query")
    parser.add_argument("--max", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--sort", default="publishedAt", choices=["publishedAt", "relevancy", "popularity"])
    parser.add_argument("--days", type=int, default=2, help="Days back to search (default: 2)")
    args = parser.parse_args()

    print(f"Fetching up to {args.max} articles from NewsAPI for '{args.query}'...")
    articles = fetch_news(query=args.query, max_results=args.max, sort_by=args.sort, days_back=args.days)

    print(f"Collected {len(articles)} articles:\n")
    for i, a in enumerate(articles, 1):
        print(f"  {i}. [{a['publisher']}] {a['title'][:75]}")
        print(f"     Published: {a['published_at'][:16]}")
        print(f"     URL: {a['url'][:80]}")
        print()

    filepath = save_results(articles, args.query)
    print(f"Saved to: {filepath}")
