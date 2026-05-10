"""
Anthropic News Blog Collector — company_blogs/

Anthropic doesn't provide a public RSS feed, so we parse their HTML news page.
Page: https://www.anthropic.com/news

Each post card on the page has: title, date, category, and link.
We then fetch the article page to get the full text.

Usage:
    python anthropic_blog.py             # fetch latest 10 posts (with full text)
    python anthropic_blog.py --max 5
    python anthropic_blog.py --no-full   # skip full article fetch (titles only)
"""

import sys
import json
import argparse
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent.parent))
from config.paths import RAW_BLOGS, ensure_output_dirs
from pipelines.layer_1_extraction.company_blogs.blog_utils import fetch_html, strip_html, make_document, fetch_article_text


ANTHROPIC_NEWS_URL = "https://www.anthropic.com/news"
ANTHROPIC_BASE_URL = "https://www.anthropic.com"
SOURCE_ID          = "anthropic_news"
COMPANY            = "Anthropic"


class AnthropicNewsParser(HTMLParser):
    """
    Parse the Anthropic news listing page to extract post cards.
    
    Anthropic news page uses a pattern where each post is wrapped in an <a> tag
    with a heading and a date inside. We track anchor context to extract both.
    """

    def __init__(self):
        super().__init__()
        self._posts = []
        self._current_link = None
        self._current_title = None
        self._current_date = None
        self._in_heading = False
        self._heading_text = []
        self._depth = 0
        self._in_anchor = False
        self._anchor_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._depth += 1

        # Track anchor links that look like post links
        if tag == "a" and "href" in attrs:
            href = attrs["href"]
            # Anthropic posts are at /news/{slug} or /research/{slug} etc.
            if href.startswith("/") and any(x in href for x in ["/news/", "/research/", "/index/"]):
                self._in_anchor = True
                self._anchor_depth = self._depth
                self._current_link = href
                self._current_title = None
                self._current_date = None

        # Detect headings inside an anchor
        if self._in_anchor and tag in ("h2", "h3", "h4", "p"):
            if tag in ("h2", "h3", "h4"):
                self._in_heading = True
                self._heading_text = []

    def handle_endtag(self, tag):
        if self._in_heading and tag in ("h2", "h3", "h4"):
            self._in_heading = False
            text = " ".join(self._heading_text).strip()
            if text and not self._current_title:
                self._current_title = text

        if self._in_anchor and self._depth == self._anchor_depth and tag == "a":
            # Exiting the anchor — save the post if we have enough info
            if self._current_link and self._current_title:
                self._posts.append({
                    "link": self._current_link,
                    "title": self._current_title,
                    "date": self._current_date or "",
                })
            self._in_anchor = False
            self._current_link = None
            self._current_title = None
            self._current_date = None

        self._depth -= 1

    def handle_data(self, data):
        if self._in_heading:
            stripped = data.strip()
            if stripped:
                self._heading_text.append(stripped)

        # Look for date-like strings (e.g. "May 7, 2026" or "2026-05-07")
        if self._in_anchor and not self._current_date:
            data = data.strip()
            if re.match(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\s+\d{4}", data):
                self._current_date = data

    def get_posts(self):
        # Deduplicate by link
        seen = set()
        unique = []
        for p in self._posts:
            if p["link"] not in seen:
                seen.add(p["link"])
                unique.append(p)
        return unique


def fetch_post_text(relative_url):
    """
    Fetch the full text of an Anthropic article page.
    Uses <article> tag extraction to get only the article body,
    not the navigation / footer that surrounds it.
    Returns (clean_text, full_url).
    """
    full_url = f"{ANTHROPIC_BASE_URL}{relative_url}"
    text = fetch_article_text(full_url)
    return text, full_url


def fetch_posts(max_results=10, include_full_text=True):
    """
    Fetch recent posts from Anthropic's news page.
    
    Args:
        max_results:       Max number of posts to return
        include_full_text: If True, fetch each article's full page text
    
    Returns:
        List of post dicts in standard document format.
    """
    html = fetch_html(ANTHROPIC_NEWS_URL)
    parser = AnthropicNewsParser()
    parser.feed(html)
    cards = parser.get_posts()[:max_results]

    posts = []
    for card in cards:
        full_url = f"{ANTHROPIC_BASE_URL}{card['link']}"
        raw_text = ""

        if include_full_text:
            raw_text = fetch_article_text(full_url)

        doc = make_document(
            source_id=SOURCE_ID,
            company=COMPANY,
            title=card["title"],
            url=full_url,
            published_at=card["date"],
            raw_text=raw_text,
            author=COMPANY,
        )
        posts.append(doc)

    return posts


def save_results(posts):
    """Save to output/layer_1_raw/blogs/anthropic/"""
    ensure_output_dirs()

    out_dir = RAW_BLOGS / "anthropic"
    out_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = out_dir / f"{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Anthropic blog posts (HTML scraping)")
    parser.add_argument("--max", type=int, default=10, help="Max posts to fetch (default: 10)")
    parser.add_argument("--no-full", action="store_true", help="Skip full article text fetch")
    args = parser.parse_args()

    include_full_text = not args.no_full
    print(f"Fetching latest {args.max} posts from Anthropic News (full_text={include_full_text})...")
    posts = fetch_posts(max_results=args.max, include_full_text=include_full_text)

    print(f"Collected {len(posts)} posts:\n")
    for i, p in enumerate(posts, 1):
        print(f"  {i}. {p['title'][:75]}")
        print(f"     Published: {p['published_at']}")
        print(f"     Text length: {len(p['raw_text'])} chars")
        print(f"     URL: {p['url'][:80]}")
        print()

    filepath = save_results(posts)
    print(f"Saved to: {filepath}")
