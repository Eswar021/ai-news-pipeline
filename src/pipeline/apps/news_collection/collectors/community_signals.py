from __future__ import annotations

from datetime import datetime, timezone
import base64
from urllib.parse import urlparse

import requests

from ..utils import (
    build_candidate_decision,
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


def collect(cfg: dict) -> dict:
    timeout = int(cfg.get("request_timeout_seconds", 15))
    runtime = cfg.get("runtime", {})
    max_items = int(runtime.get("max_items", 15))
    scan_depth = int(runtime.get("scan_depth", 60))

    records: list[dict] = []
    candidate_ledger: list[dict] = []
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
        candidate_ledger.extend(result.get("candidate_ledger", []))
        source_summaries[source["id"]] = result["summary"]

    return {
        "records": records,
        "candidate_ledger": candidate_ledger,
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
    candidate_ledger: list[dict] = []
    notes: list[str] = []
    status = "ok"

    try:
        story_ids = _get_json(f"{HN_API_BASE}/{story_type}stories.json", timeout)[:scan_depth]
        fetched_count = len(story_ids)

        for story_id in story_ids:
            item = _get_json(f"{HN_API_BASE}/item/{story_id}.json", timeout)
            if not item or item.get("type") != "story":
                filtered_out_count += 1
                candidate_ledger.append(
                    build_candidate_decision(
                        source_group=cfg["source_group"],
                        source=source["id"],
                        title=clean_text((item or {}).get("title", "")),
                        url=f"https://news.ycombinator.com/item?id={story_id}",
                        published_at=_published_at((item or {}).get("time")),
                        decision="hard_rejected",
                        reason_code="unsupported_hackernews_item",
                        reason="The fetched Hacker News item is not a story.",
                    )
                )
                continue
            published_at = _published_at(item.get("time"))
            external_url = item.get("url") or ""
            article_fetch_supported = bool(
                external_url and _is_content_candidate(external_url)
            )
            if external_url and not article_fetch_supported and len(notes) < 10:
                notes.append(f"Skipped unsupported article-body fetch: {external_url}")
            page_text = ""
            if article_fetch_supported:
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
                        "article_fetch_supported": article_fetch_supported,
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
        "candidate_ledger": candidate_ledger,
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
    window_start = cfg["collection_window"]["start"][:10]
    fetched_count = 0
    collected_count = 0
    filtered_out_count = 0
    records: list[dict] = []
    candidate_ledger: list[dict] = []
    notes: list[str] = []
    status = "ok"

    seen_repos: set[str] = set()
    try:
        for query in _github_search_queries(cfg, source):
            repos = _search_github_repos(api_key, query, timeout, window_start)
            fetched_count += len(repos)
            for repo in repos:
                full_name = repo.get("full_name", "")
                if not full_name or full_name in seen_repos:
                    filtered_out_count += 1
                    candidate_ledger.append(
                        build_candidate_decision(
                            source_group=cfg["source_group"],
                            source=source["id"],
                            title=full_name,
                            url=repo.get("html_url", ""),
                            published_at=_github_activity_time(repo),
                            decision="hard_rejected",
                            reason_code="duplicate_or_missing_repository_name",
                        )
                    )
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
                        published_at=_github_activity_time(repo),
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
        "candidate_ledger": candidate_ledger,
        "summary": {
            "status": status,
            "fetched_count": fetched_count,
            "collected_count": collected_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        },
    }


def _github_search_queries(cfg: dict, source: dict) -> list[str]:
    queries = [
        *source.get("search_queries", []),
        *cfg.get("query_themes", []),
    ]
    seen = set()
    kept = []
    for query in queries:
        cleaned = clean_text(query)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        kept.append(cleaned)
    return kept


def _search_github_repos(api_key: str, theme: str, timeout: int, window_start: str) -> list[dict]:
    query = f'"{theme}" in:name,description,readme pushed:>={window_start}'
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


def _github_activity_time(repo: dict) -> str:
    return clean_text(
        repo.get("pushed_at")
        or repo.get("updated_at")
        or repo.get("created_at")
        or ""
    )


def _is_content_candidate(url: str) -> bool:
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return True
    if host.startswith("www."):
        host = host[4:]
    return host not in NON_ARTICLE_HOSTS
