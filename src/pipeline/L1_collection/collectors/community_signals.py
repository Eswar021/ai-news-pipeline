from __future__ import annotations

from datetime import datetime, timezone
import base64
import re
from urllib.parse import urlparse

import requests

from src.pipeline.L1_collection.common import (
    build_record,
    clean_text,
    extract_article_text,
    request_text,
    resolve_env,
)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
GITHUB_API_BASE = "https://api.github.com"
NON_ARTICLE_HOSTS = {
    "crates.io",
}
WEAK_RELEVANCE_TOKENS = {
    "news",
    "new",
    "tool",
    "tools",
    "product",
    "products",
    "launch",
    "launches",
    "release",
    "releases",
    "research",
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
    timeout = int(cfg.get("request_timeout_seconds", 15))
    runtime = cfg.get("runtime", {})
    max_items = int(runtime.get("max_items", 15))
    scan_depth = int(runtime.get("scan_depth", 60))

    records: list[dict] = []
    source_summaries: dict[str, dict] = {}

    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue

        provider = source.get("provider")
        if provider == "hackernews":
            result = _collect_hackernews(cfg, source, timeout, max_items, scan_depth)
        elif provider == "github":
            result = _collect_github(cfg, source, timeout)
        else:
            raise ValueError(f"Unsupported community provider: {provider}")

        records.extend(result["records"])
        source_summaries[source["id"]] = result["summary"]

    return {
        "records": records,
        "summary": {
            "collector": "community_signals",
            "status": "partial" if any(item["status"] != "ok" for item in source_summaries.values()) else "ok",
            "fetched_count": sum(item["fetched_count"] for item in source_summaries.values()),
            "collected_count": len(records),
            "filtered_out_count": sum(item["filtered_out_count"] for item in source_summaries.values()),
            "sources": source_summaries,
        },
    }


def _collect_hackernews(cfg: dict, source: dict, timeout: int, max_items: int, scan_depth: int) -> dict:
    story_type = source.get("story_type", "top")
    fetched_count = 0
    collected_count = 0
    filtered_out_count = 0
    records: list[dict] = []
    notes: list[str] = []
    status = "ok"

    try:
        story_ids = _get_json(f"{HN_API_BASE}/{story_type}stories.json", timeout)[:scan_depth]
        fetched_count = len(story_ids)
        relevance = _build_relevance_profile(
            list(cfg.get("query_themes", [])),
            list(cfg.get("allowed_topics", [])),
        )

        for story_id in story_ids:
            item = _get_json(f"{HN_API_BASE}/item/{story_id}.json", timeout)
            if not item or item.get("type") != "story":
                filtered_out_count += 1
                continue
            if not _is_relevant(item, relevance):
                filtered_out_count += 1
                continue

            published_at = _published_at(item.get("time"))
            external_url = item.get("url") or ""
            if external_url and not _is_content_candidate(external_url):
                filtered_out_count += 1
                continue
            page_text = ""
            if external_url:
                try:
                    article_html = request_text(external_url, timeout=timeout)
                    page_text = extract_article_text(article_html)
                except Exception as exc:
                    notes.append(f"Article fetch failed for {external_url}: {exc}")

            text = clean_text(item.get("text", ""))
            content = page_text or text or clean_text(item.get("title", ""))

            records.append(
                build_record(
                    source=source["id"],
                    source_group=cfg["source_group"],
                    source_type=source.get("source_type", "community_signal"),
                    title=item.get("title", ""),
                    url=external_url or f"https://news.ycombinator.com/item?id={item['id']}",
                    published_at=published_at,
                    content=content,
                    extra_fields={
                        "collector": "community_signals",
                        "provider": "hackernews",
                        "hn_discussion_url": f"https://news.ycombinator.com/item?id={item['id']}",
                        "score": item.get("score", 0),
                        "comment_count": item.get("descendants", 0),
                        "author": item.get("by", ""),
                        "trust_tier": source.get("trust_tier"),
                    },
                )
            )
            collected_count += 1
            if collected_count >= max_items:
                break
    except Exception as exc:
        status = "failed"
        notes.append(str(exc))

    return {
        "records": records,
        "summary": {
            "status": status,
            "fetched_count": fetched_count,
            "collected_count": collected_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        },
    }


def _collect_github(cfg: dict, source: dict, timeout: int) -> dict:
    api_key = resolve_env(source["env_keys"])
    max_items = int(source.get("max_items", 10))
    min_stars = int(source.get("min_stars", 50))
    window_start = cfg["collection_window"]["start"][:10]
    fetched_count = 0
    collected_count = 0
    filtered_out_count = 0
    records: list[dict] = []
    notes: list[str] = []
    status = "ok"

    seen_repos: set[str] = set()
    try:
        for theme in cfg.get("query_themes", []):
            repos = _search_github_repos(api_key, theme, timeout, min_stars, window_start)
            fetched_count += len(repos)
            for repo in repos:
                full_name = repo.get("full_name", "")
                if not full_name or full_name in seen_repos:
                    filtered_out_count += 1
                    continue
                seen_repos.add(full_name)

                readme_text = ""
                try:
                    readme_text = _fetch_github_readme(api_key, full_name, timeout)
                except Exception as exc:
                    notes.append(f"README fetch failed for {full_name}: {exc}")

                description = clean_text(repo.get("description", ""))
                topics = repo.get("topics") or []
                topic_text = ", ".join(topic for topic in topics if topic)
                content = "\n\n".join(part for part in [description, topic_text, readme_text] if part)
                if not content:
                    content = clean_text(repo.get("name", ""))

                records.append(
                    build_record(
                        source=source["id"],
                        source_group=cfg["source_group"],
                        source_type=source.get("source_type", "community_signal"),
                        title=repo.get("full_name", ""),
                        url=repo.get("html_url", ""),
                        published_at=cfg["collection_window"]["end"],
                        content=content,
                        extra_fields={
                            "collector": "community_signals",
                            "provider": "github",
                            "source_name": repo.get("full_name", ""),
                            "trust_tier": source.get("trust_tier"),
                            "author": (repo.get("owner") or {}).get("login", ""),
                            "description": description,
                            "language": repo.get("language", ""),
                            "stars": repo.get("stargazers_count", 0),
                            "forks": repo.get("forks_count", 0),
                            "topics": topics,
                            "repo_pushed_at": repo.get("pushed_at", ""),
                            "repo_updated_at": repo.get("updated_at", ""),
                            "repo_created_at": repo.get("created_at", ""),
                        },
                    )
                )
                collected_count += 1
                if collected_count >= max_items:
                    break
            if collected_count >= max_items:
                break
    except Exception as exc:
        status = "failed"
        notes.append(str(exc))

    return {
        "records": records,
        "summary": {
            "status": status,
            "fetched_count": fetched_count,
            "collected_count": collected_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        },
    }


def _search_github_repos(api_key: str, theme: str, timeout: int, min_stars: int, window_start: str) -> list[dict]:
    query = f'"{theme}" in:name,description,readme stars:>={min_stars} pushed:>={window_start}'
    response = requests.get(
        f"{GITHUB_API_BASE}/search/repositories",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/vnd.github+json",
        },
        params={
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": 10,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("items", [])


def _fetch_github_readme(api_key: str, full_name: str, timeout: int) -> str:
    response = requests.get(
        f"{GITHUB_API_BASE}/repos/{full_name}/readme",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/vnd.github+json",
        },
        timeout=timeout,
    )
    if response.status_code == 404:
        return ""
    response.raise_for_status()
    data = response.json()
    content = data.get("content", "")
    if not content:
        return ""
    decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
    return clean_text(decoded)


def _get_json(url: str, timeout: int):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _published_at(timestamp: int | None) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _is_relevant(item: dict, relevance: dict[str, set[str]]) -> bool:
    haystack = " ".join(
        [
            clean_text(item.get("title", "")).lower(),
            clean_text(item.get("text", "")).lower(),
            clean_text(item.get("url", "")).lower(),
        ]
    )
    phrase_hits = sum(1 for phrase in relevance["phrases"] if _contains_term(haystack, phrase))
    token_hits = {
        token
        for token in relevance["strong_tokens"]
        if _contains_term(haystack, token)
    }
    weak_token_hits = {
        token
        for token in relevance["weak_tokens"]
        if _contains_term(haystack, token)
    }

    if phrase_hits >= 1:
        return True
    if len(token_hits) >= 2:
        return True
    if token_hits and weak_token_hits:
        return True
    return False


def _contains_term(haystack: str, term: str) -> bool:
    term = clean_text(term).lower()
    if not term:
        return False
    if " " in term:
        return term in haystack
    pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def _is_content_candidate(url: str) -> bool:
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return True
    if host.startswith("www."):
        host = host[4:]
    return host not in NON_ARTICLE_HOSTS


def _build_relevance_profile(query_themes: list[str], allowed_topics: list[str]) -> dict[str, set[str]]:
    phrases = {
        clean_text(value).lower()
        for value in [*query_themes, *allowed_topics]
        if clean_text(value)
    }
    strong_tokens: set[str] = set()
    weak_tokens: set[str] = set()

    for phrase in phrases:
        for token in re.findall(r"[a-z0-9\+\-\.]+", phrase):
            if token in STOPWORDS:
                continue
            if len(token) < 3 and token not in {"ai"}:
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
