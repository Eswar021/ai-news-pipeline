from __future__ import annotations

import re
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests

from ..utils import (
    build_record,
    clean_text,
    extract_article_text,
    normalize_content,
    request_text,
    resolve_env,
    strip_html,
)


NON_ARTICLE_HOSTS = {
    "pypi.org",
}
WEAK_RELEVANCE_TOKENS = {
    "launch",
    "launches",
    "news",
    "product",
    "products",
    "release",
    "releases",
    "research",
    "tool",
    "tools",
}
HIGH_SIGNAL_RELEVANCE_TOKENS = {
    "ai",
    "agentic",
    "anthropic",
    "antigravity",
    "chatgpt",
    "claude",
    "codex",
    "gemini",
    "gpt",
    "llm",
    "mcp",
    "openai",
}
STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "your",
}


def collect(cfg: dict) -> dict:
    timeout = int(cfg.get("request_timeout_seconds", 20))
    window = cfg["collection_window"]
    max_items_per_source = int(cfg.get("runtime", {}).get("max_items_per_source", 8))

    records: list[dict] = []
    source_summaries: dict[str, dict] = {}

    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue

        api_key = resolve_env(source["env_keys"]) if source.get("env_keys") else ""
        query = _build_query(cfg.get("query_themes", []), source["provider"])
        status = "ok"
        notes: list[str] = []
        fetched_count = 0
        collected_count = 0
        filtered_out_count = 0
        source_records: list[dict] = []
        try:
            fetch_limit = int(source.get("scan_items", max_items_per_source * 2))
            raw_articles = _fetch_articles(source, api_key, query, fetch_limit, window, timeout)
            fetched_count = len(raw_articles)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            source_summaries[source["id"]] = {
                "status": status,
                "fetched_count": 0,
                "collected_count": 0,
                "filtered_out_count": 0,
                "notes": notes,
            }
            continue

        for article in raw_articles:
            if source.get("relevance_filter") and not _is_relevant_article(article, cfg, source):
                filtered_out_count += 1
                if len(notes) < 10:
                    notes.append(f"Filtered low-relevance feed entry: {article.get('title', '')}")
                continue

            url = article.get("url", "")
            if not _is_article_candidate(url):
                filtered_out_count += 1
                notes.append(f"Filtered non-article URL: {url}")
                continue

            article_body = ""
            if url:
                try:
                    article_html = request_text(url, timeout=timeout)
                    article_body = extract_article_text(article_html)
                except Exception as exc:
                    notes.append(f"Article fetch failed for {url}: {exc}")

            content, content_status = normalize_content(
                article_body or article.get("content", ""),
                fallback=article.get("description", "") or article.get("title", ""),
            )
            source_records.append(
                build_record(
                    source=source["id"],
                    source_group=cfg["source_group"],
                    source_type=source.get("source_type", "tech_news_article"),
                    title=article.get("title", ""),
                    url=url,
                    published_at=article.get("published_at", ""),
                    content=content,
                    extra_fields={
                        "collector": "tech_news",
                        "provider": source["provider"],
                        "source_name": article.get("source_name", ""),
                        "author": article.get("author", ""),
                        "description": clean_text(article.get("description", "")),
                        "trust_tier": source.get("trust_tier"),
                        "content_status": content_status,
                        "source_relationship": source.get("source_relationship", ""),
                    },
                )
            )
            collected_count += 1
            if collected_count >= max_items_per_source:
                break

        records.extend(source_records)
        source_summaries[source["id"]] = {
            "status": status,
            "fetched_count": fetched_count,
            "collected_count": collected_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        }

    return {
        "records": records,
        "summary": {
            "collector": "tech_news",
            "status": "partial" if any(item["status"] != "ok" for item in source_summaries.values()) else "ok",
            "fetched_count": sum(item["fetched_count"] for item in source_summaries.values()),
            "collected_count": len(records),
            "filtered_out_count": sum(item["filtered_out_count"] for item in source_summaries.values()),
            "sources": source_summaries,
        },
    }


def _build_query(themes: list[str], provider: str) -> str:
    if not themes:
        return "AI"
    if provider == "newsapi":
        return " OR ".join(f'"{theme}"' if " " in theme else theme for theme in themes)
    if provider == "newsdata":
        return "artificial intelligence"
    if provider == "mediastack":
        return "AI"
    return "AI"


def _fetch_articles(source: dict, api_key: str, query: str, limit: int, window: dict, timeout: int) -> list[dict]:
    provider = source["provider"]
    if provider == "newsapi":
        return _fetch_newsapi(api_key, query, limit, window, timeout)
    if provider == "newsdata":
        return _fetch_newsdata(api_key, query, limit, timeout)
    if provider == "mediastack":
        return _fetch_mediastack(api_key, query, limit, timeout)
    if provider == "rss_feed":
        return _fetch_rss_feed(source, limit, timeout)
    raise ValueError(f"Unsupported tech-news provider: {provider}")


def _fetch_newsapi(api_key: str, query: str, limit: int, window: dict, timeout: int) -> list[dict]:
    response = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": limit,
            "from": window["start"],
            "to": window["end"],
            "apiKey": api_key,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "published_at": item.get("publishedAt", ""),
            "author": item.get("author", ""),
            "description": item.get("description", ""),
            "content": item.get("content", ""),
            "source_name": (item.get("source") or {}).get("name", ""),
        }
        for item in data.get("articles", [])
    ]


def _fetch_newsdata(api_key: str, query: str, limit: int, timeout: int) -> list[dict]:
    response = requests.get(
        "https://newsdata.io/api/1/news",
        params={
            "apikey": api_key,
            "q": query,
            "language": "en",
            "size": limit,
            "category": "technology",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "published_at": item.get("pubDate", ""),
            "author": ", ".join(item.get("creator") or []),
            "description": item.get("description", ""),
            "content": item.get("content", ""),
            "source_name": item.get("source_id", ""),
        }
        for item in data.get("results", [])
    ]


def _fetch_mediastack(api_key: str, query: str, limit: int, timeout: int) -> list[dict]:
    response = requests.get(
        "http://api.mediastack.com/v1/news",
        params={
            "access_key": api_key,
            "keywords": query,
            "languages": "en",
            "sort": "published_desc",
            "limit": limit,
            "categories": "technology",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "published_at": item.get("published_at", ""),
            "author": item.get("author", ""),
            "description": item.get("description", ""),
            "content": item.get("description", ""),
            "source_name": item.get("source", ""),
        }
        for item in data.get("data", [])
    ]


def _fetch_rss_feed(source: dict, limit: int, timeout: int) -> list[dict]:
    feed_text = request_text(source["feed_url"], timeout=timeout)
    return _parse_feed_entries(feed_text, source["name"])[:limit]


def _parse_feed_entries(feed_text: str, source_name: str) -> list[dict]:
    root = ET.fromstring(feed_text)
    entries: list[dict] = []

    for item in root.findall(".//item"):
        entries.append(
            {
                "title": _first_text(item, "title"),
                "url": _first_text(item, "link") or _first_text(item, "guid"),
                "published_at": _first_text(item, "pubDate") or _first_text(item, "published"),
                "author": _first_text(item, "creator") or _first_text(item, "author"),
                "description": strip_html(_first_text(item, "description")),
                "content": strip_html(_first_text(item, "encoded") or _first_text(item, "content")),
                "source_name": source_name,
            }
        )

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns):
        link = ""
        for link_el in entry.findall("atom:link", ns):
            if link_el.attrib.get("rel", "alternate") == "alternate" and link_el.attrib.get("href"):
                link = link_el.attrib["href"]
                break
        entries.append(
            {
                "title": _first_text(entry, "title"),
                "url": link,
                "published_at": _first_text(entry, "published") or _first_text(entry, "updated"),
                "author": _first_text(entry, "author"),
                "description": strip_html(_first_text(entry, "summary")),
                "content": strip_html(_first_text(entry, "content")),
                "source_name": source_name,
            }
        )

    return [entry for entry in entries if entry["title"] and entry["url"]]


def _first_text(element, tag_name: str) -> str:
    for child in element.iter():
        if child.tag.endswith(tag_name):
            return clean_text(child.text or "")
    return ""


def _is_article_candidate(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in NON_ARTICLE_HOSTS:
        return False
    return parsed.scheme in {"http", "https"} and bool(host)


def _is_relevant_article(article: dict, cfg: dict, source: dict) -> bool:
    terms = [
        *cfg.get("query_themes", []),
        *cfg.get("allowed_topics", []),
        *source.get("search_terms", []),
    ]
    profile = _build_relevance_profile(terms)
    haystack = " ".join(
        [
            clean_text(article.get("title", "")),
            clean_text(article.get("description", "")),
            clean_text(article.get("content", "")),
            clean_text(article.get("source_name", "")),
            clean_text(article.get("url", "")),
        ]
    ).lower()
    phrase_hits = sum(1 for phrase in profile["phrases"] if _contains_term(haystack, phrase))
    strong_hits = {
        token
        for token in profile["strong_tokens"]
        if _contains_term(haystack, token)
    }
    weak_hits = {
        token
        for token in profile["weak_tokens"]
        if _contains_term(haystack, token)
    }
    high_signal_hits = strong_hits & HIGH_SIGNAL_RELEVANCE_TOKENS
    return phrase_hits >= 1 or bool(high_signal_hits) or len(strong_hits) >= 2 or bool(strong_hits and weak_hits)


def _build_relevance_profile(terms: list[str]) -> dict[str, set[str]]:
    phrases = {
        clean_text(value).lower()
        for value in terms
        if clean_text(value) and (" " in clean_text(value) or clean_text(value).lower() in HIGH_SIGNAL_RELEVANCE_TOKENS)
    }
    strong_tokens: set[str] = set()
    weak_tokens: set[str] = set()

    for phrase in phrases:
        for token in re.findall(r"[a-z0-9\+\-\.]+", phrase):
            if token in STOPWORDS:
                continue
            if len(token) < 3 and token != "ai":
                continue
            if token in WEAK_RELEVANCE_TOKENS:
                weak_tokens.add(token)
            else:
                strong_tokens.add(token)

    return {
        "phrases": phrases,
        "strong_tokens": strong_tokens,
        "weak_tokens": weak_tokens,
    }


def _contains_term(haystack: str, term: str) -> bool:
    term = clean_text(term).lower()
    if not term:
        return False
    if " " in term:
        return term in haystack
    pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
    return re.search(pattern, haystack) is not None
