"""
OpenAI News Blog Collector — company_blogs/

OpenAI provides an RSS feed at https://openai.com/news/rss/
Each item has: title, link, pubDate, description, and full content via content:encoded.

Usage:
    python openai_blog.py               # fetch latest 10 posts
    python openai_blog.py --max 20
"""

import sys
import json
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from config.time_utils import now_project

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent.parent))
from config.paths import RAW_BLOGS, ensure_output_dirs
from pipelines.layer_1_extraction.company_blogs.blog_utils import fetch_rss, strip_html, make_document, fetch_article_text


OPENAI_RSS_URL = "https://openai.com/blog/rss.xml"
SOURCE_ID      = "openai_news"
COMPANY        = "OpenAI"

# RSS namespaces
NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
    "atom":    "http://www.w3.org/2005/Atom",
}


def fetch_posts(max_results=10, fetch_full=True):
    """
    Fetch recent posts from OpenAI's RSS feed.

    Args:
        max_results: Max posts to return.
        fetch_full:  If True (default), fetch each article's full page when RSS
                     provides only a short description. OpenAI's RSS does not include
                     content:encoded, so fetch_full=True is required for real content.

    Returns:
        List of post dicts in our standard document format.
    """
    import time
    xml_data = fetch_rss(OPENAI_RSS_URL)
    root = ET.fromstring(xml_data)
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else root.findall("item")

    posts = []
    for item in items[:max_results]:
        post = parse_item(item, fetch_full=fetch_full)
        posts.append(post)
        if fetch_full:
            time.sleep(0.5)  # polite delay between article fetches

    return posts


def parse_item(item, fetch_full=True):
    """Parse a single RSS <item> into our standard document format."""

    title       = (item.findtext("title") or "").strip()
    url         = (item.findtext("link") or "").strip()
    pub_date    = (item.findtext("pubDate") or "").strip()
    description = (item.findtext("description") or "").strip()
    author      = (item.findtext("dc:creator", namespaces=NS) or COMPANY).strip()

    # Try content:encoded first (full HTML body, if provided by the feed)
    full_html = item.findtext("content:encoded", namespaces=NS) or ""
    if full_html:
        raw_text = strip_html(full_html)
    else:
        raw_text = strip_html(description) if description else ""

    # OpenAI RSS only provides short descriptions (~150 chars). Fetch the article page
    # to get the actual content when we have the URL and the text is too short.
    if fetch_full and url and len(raw_text) < 500:
        article_text = fetch_article_text(url)
        if len(article_text) > len(raw_text):
            raw_text = article_text

    return make_document(
        source_id=SOURCE_ID,
        company=COMPANY,
        title=title,
        url=url,
        published_at=pub_date,
        raw_text=raw_text,
        author=author,
    )


def save_results(posts):
    """Save to output/layer_1_raw/blogs/openai/"""
    ensure_output_dirs()

    out_dir = RAW_BLOGS / "openai"
    out_dir.mkdir(parents=True, exist_ok=True)

    date_str = now_project().strftime("%Y-%m-%d")
    filepath = out_dir / f"{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch OpenAI blog posts via RSS")
    parser.add_argument("--max", type=int, default=10, help="Max posts to fetch (default: 10)")
    args = parser.parse_args()

    print(f"Fetching latest {args.max} posts from OpenAI News...")
    posts = fetch_posts(max_results=args.max)

    print(f"Collected {len(posts)} posts:\n")
    for i, p in enumerate(posts, 1):
        print(f"  {i}. {p['title'][:75]}")
        print(f"     Published: {p['published_at'][:25]}")
        print(f"     Text length: {len(p['raw_text'])} chars")
        print(f"     URL: {p['url'][:80]}")
        print()

    filepath = save_results(posts)
    print(f"Saved to: {filepath}")
