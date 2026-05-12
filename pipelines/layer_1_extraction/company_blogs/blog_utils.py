"""
Shared utilities for company blog collectors.

Each company blog has its own extractor because every site has different
HTML structure. This module provides common parsing helpers that individual
extractors can reuse.
"""

import hashlib
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser


def fetch_html(url, timeout=20):
    """Fetch raw HTML from a URL. Returns decoded string."""
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; AI-Content-Bot/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    response = urlopen(req, timeout=timeout)
    return response.read().decode("utf-8", errors="replace")


def fetch_rss(url, timeout=15):
    """Fetch raw RSS/Atom XML from a URL. Returns decoded string."""
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; AI-Content-Bot/1.0)",
        "Accept": "application/rss+xml, application/atom+xml, text/xml",
    })
    response = urlopen(req, timeout=timeout)
    return response.read().decode("utf-8", errors="replace")


class TextStripper(HTMLParser):
    """Simple HTML → plain text stripper. Keeps text content, drops tags."""

    SKIP_TAGS = {"script", "style", "noscript", "head", "nav", "footer", "aside", "form"}

    def __init__(self):
        super().__init__()
        self._in_skip = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._in_skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._in_skip > 0:
            self._in_skip -= 1

    def handle_data(self, data):
        if self._in_skip == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self):
        return " ".join(self._parts)


def strip_html(html_string):
    """Strip HTML tags and return clean plain text."""
    parser = TextStripper()
    parser.feed(html_string)
    return parser.get_text()


def fetch_article_text(url: str, timeout: int = 20) -> str:
    """
    Fetch a blog article URL and extract the main article body text.

    Strategy: <article> tag → <main> tag → full-page strip fallback.
    The <article> tag is the most reliable for modern blog platforms (OpenAI, Anthropic)
    because it contains only the content body, not nav/footer/sidebar.

    Returns clean plain text (no HTML).
    """
    import re
    html = fetch_html(url, timeout=timeout)

    # <article> is the most reliable semantic container for blog content
    m = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL | re.IGNORECASE)
    if m:
        text = strip_html(m.group(1))
        if len(text) > 200:
            return text

    # <main> is the next best — skips repeated nav/header/footer
    m = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL | re.IGNORECASE)
    if m:
        text = strip_html(m.group(1))
        if len(text) > 200:
            return text

    # Fallback: strip the whole page (includes nav noise, but better than nothing)
    return strip_html(html)


def make_document(source_id, company, title, url, published_at, raw_text, author="", extra=None):
    """
    Build a standard document dict for a blog post.
    All company blog extractors should call this to ensure consistent output format.
    
    Args:
        source_id:    e.g. "openai_news", "anthropic_news"
        company:      e.g. "OpenAI", "Anthropic"
        title:        Post title
        url:          Post URL
        published_at: ISO date string (or raw date string)
        raw_text:     Full article text (clean, no HTML)
        author:       Author name or org name
        extra:        Dict of any additional fields to merge
    
    Returns:
        Standard document dict.
    """
    content_hash = hashlib.sha256(f"blog:{url}:{title}".encode()).hexdigest()[:16]

    doc = {
        "document_id": f"blog_{content_hash}",
        "source_id": source_id,
        "module": "blog_collector",
        "source_type": "official_company_blog",
        "trust_tier": 1,
        "title": title,
        "url": url,
        "published_at": published_at,
        "author": author or company,
        "company": company,
        "raw_text": raw_text,
        "content_hash": content_hash,
        "collected_at": now_project_iso(),
    }

    if extra:
        doc.update(extra)

    return doc
