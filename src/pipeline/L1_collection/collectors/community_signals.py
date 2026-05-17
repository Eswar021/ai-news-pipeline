from __future__ import annotations

import requests

from src.pipeline.L1_collection.common import build_record, clean_text, within_window

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
AI_KEYWORDS = {
    "ai",
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "llm",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "meta ai",
    "llama",
    "copilot",
    "agent",
    "rag",
    "robotics",
    "hugging face",
    "nvidia",
}


def collect(cfg: dict) -> dict:
    timeout = int(cfg.get("request_timeout_seconds", 15))
    runtime = cfg.get("runtime", {})
    window = cfg["collection_window"]
    max_items = int(runtime.get("max_items", 15))
    scan_depth = int(runtime.get("scan_depth", 60))
    source = next(item for item in cfg["sources"] if item.get("enabled", True))
    story_type = source.get("story_type", "top")

    fetched_count = 0
    kept_count = 0
    filtered_out_count = 0
    records: list[dict] = []
    notes: list[str] = []
    status = "ok"

    try:
        story_ids = _get_json(f"{HN_API_BASE}/{story_type}stories.json", timeout)[:scan_depth]
        fetched_count = len(story_ids)
        theme_terms = {term.lower() for term in cfg.get("query_themes", [])}

        for story_id in story_ids:
            item = _get_json(f"{HN_API_BASE}/item/{story_id}.json", timeout)
            if not item or item.get("type") != "story":
                filtered_out_count += 1
                continue
            if not _is_relevant(item, theme_terms):
                filtered_out_count += 1
                continue

            published_at = _published_at(item.get("time"))
            if not within_window(published_at, window["start"], window["end"]):
                filtered_out_count += 1
                continue

            text = clean_text(item.get("text", ""))
            content = text or clean_text(item.get("title", ""))
            content_status = "full" if text else "title_only"
            records.append(
                build_record(
                    source=source["id"],
                    source_group=cfg["source_group"],
                    source_type=source.get("source_type", "community_signal"),
                    title=item.get("title", ""),
                    url=item.get("url") or f"https://news.ycombinator.com/item?id={item['id']}",
                    published_at=published_at,
                    content=content,
                    metadata={
                        "collector": "community_signals",
                        "provider": "hackernews",
                        "hn_discussion_url": f"https://news.ycombinator.com/item?id={item['id']}",
                        "score": item.get("score", 0),
                        "comment_count": item.get("descendants", 0),
                        "author": item.get("by", ""),
                        "trust_tier": source.get("trust_tier"),
                        "content_status": content_status,
                    },
                )
            )
            kept_count += 1
            if kept_count >= max_items:
                break
    except Exception as exc:
        status = "failed"
        notes.append(str(exc))

    return {
        "records": records,
        "summary": {
            "collector": "community_signals",
            "status": status,
            "fetched_count": fetched_count,
            "kept_count": kept_count,
            "filtered_out_count": filtered_out_count,
            "sources": {
                source["id"]: {
                    "status": status,
                    "fetched_count": fetched_count,
                    "kept_count": kept_count,
                    "filtered_out_count": filtered_out_count,
                    "notes": notes,
                }
            },
        },
    }


def _get_json(url: str, timeout: int):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _published_at(timestamp: int | None) -> str:
    from datetime import datetime, timezone

    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _is_relevant(item: dict, theme_terms: set[str]) -> bool:
    haystack = " ".join(
        [
            clean_text(item.get("title", "")).lower(),
            clean_text(item.get("text", "")).lower(),
            clean_text(item.get("url", "")).lower(),
        ]
    )
    if any(keyword in haystack for keyword in AI_KEYWORDS):
        return True
    return any(term in haystack for term in theme_terms if term)
