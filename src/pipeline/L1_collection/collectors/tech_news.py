from __future__ import annotations

import requests

from src.pipeline.L1_collection.common import build_record, clean_text, normalize_content, resolve_env, within_window


def collect(cfg: dict) -> dict:
    timeout = int(cfg.get("request_timeout_seconds", 20))
    query = _build_query(cfg.get("query_themes", []))
    window = cfg["collection_window"]
    max_items_per_source = int(cfg.get("runtime", {}).get("max_items_per_source", 8))

    records: list[dict] = []
    source_summaries: dict[str, dict] = {}

    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue

        api_key = resolve_env(source["env_keys"])
        status = "ok"
        notes: list[str] = []
        fetched_count = 0
        kept_count = 0
        filtered_out_count = 0
        source_records: list[dict] = []
        try:
            raw_articles = _fetch_articles(source["provider"], api_key, query, max_items_per_source * 2, window, timeout)
            fetched_count = len(raw_articles)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            source_summaries[source["id"]] = {
                "status": status,
                "fetched_count": 0,
                "kept_count": 0,
                "filtered_out_count": 0,
                "notes": notes,
            }
            continue

        for article in raw_articles:
            published_at = article.get("published_at", "")
            if not within_window(published_at, window["start"], window["end"]):
                filtered_out_count += 1
                continue

            content, content_status = normalize_content(
                article.get("content", ""),
                fallback=article.get("description", "") or article.get("title", ""),
            )
            source_records.append(
                build_record(
                    source=source["id"],
                    source_group=cfg["source_group"],
                    source_type=source.get("source_type", "tech_news_article"),
                    title=article.get("title", ""),
                    url=article.get("url", ""),
                    published_at=published_at,
                    content=content,
                    metadata={
                        "collector": "tech_news",
                        "provider": source["provider"],
                        "source_name": article.get("source_name", ""),
                        "author": article.get("author", ""),
                        "description": clean_text(article.get("description", "")),
                        "trust_tier": source.get("trust_tier"),
                        "content_status": content_status,
                    },
                )
            )
            kept_count += 1
            if kept_count >= max_items_per_source:
                break

        records.extend(source_records)
        source_summaries[source["id"]] = {
            "status": status,
            "fetched_count": fetched_count,
            "kept_count": kept_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        }

    return {
        "records": records,
        "summary": {
            "collector": "tech_news",
            "status": "partial" if any(item["status"] != "ok" for item in source_summaries.values()) else "ok",
            "fetched_count": sum(item["fetched_count"] for item in source_summaries.values()),
            "kept_count": len(records),
            "filtered_out_count": sum(item["filtered_out_count"] for item in source_summaries.values()),
            "sources": source_summaries,
        },
    }


def _build_query(themes: list[str]) -> str:
    if not themes:
        return "AI"
    return " OR ".join(f'"{theme}"' if " " in theme else theme for theme in themes)


def _fetch_articles(provider: str, api_key: str, query: str, limit: int, window: dict, timeout: int) -> list[dict]:
    if provider == "newsapi":
        return _fetch_newsapi(api_key, query, limit, window, timeout)
    if provider == "newsdata":
        return _fetch_newsdata(api_key, query, limit, timeout)
    if provider == "mediastack":
        return _fetch_mediastack(api_key, query, limit, timeout)
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
