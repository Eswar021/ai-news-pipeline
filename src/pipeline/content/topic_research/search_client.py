"""Web search for topic_research.

A thin provider seam so the module doesn't hardcode Tavily — a future "build our
own search/parser" path (noted as a likely upgrade) plugs in here without touching
the app. Tavily returns clean, extracted, LLM-ready content per result, so no
separate fetch/scrape step is needed today.
"""
from __future__ import annotations

import os
from typing import Any, Callable

try:  # requests is a first-party dependency
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

TAVILY_URL = "https://api.tavily.com/search"


class SearchError(RuntimeError):
    """A hard search failure (missing key, transport, non-200)."""


def tavily_search(
    query: str,
    *,
    max_results: int = 5,
    search_depth: str = "advanced",
    include_answer: bool = False,
    timeout: float = 30.0,
    api_key: str | None = None,
    http_post: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """One Tavily search → cleaned results ``[{title, url, content, score}]``.

    Raises ``SearchError`` on a hard failure; the caller decides how to degrade.
    ``http_post`` is injectable for tests."""
    api_key = (api_key or os.getenv("TAVILY_API_KEY") or "").strip()
    if not api_key:
        raise SearchError("TAVILY_API_KEY is not set")
    post = http_post or (requests.post if requests is not None else None)
    if post is None:
        raise SearchError("requests is unavailable")
    try:
        response = post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "query": query,
                "max_results": max_results,
                "search_depth": search_depth,
                "include_answer": include_answer,
            },
            timeout=timeout,
        )
    except Exception as exc:  # transport
        raise SearchError(f"tavily transport error: {type(exc).__name__}: {exc}") from exc
    status = getattr(response, "status_code", 0)
    if status != 200:
        raise SearchError(f"tavily returned {status}: {getattr(response, 'text', '')[:200]}")
    data = response.json()
    results: list[dict[str, Any]] = []
    for item in data.get("results") or []:
        url = str(item.get("url") or "").strip()
        content = str(item.get("content") or "").strip()
        if url and content:
            results.append(
                {
                    "title": str(item.get("title") or "").strip(),
                    "url": url,
                    "content": content,
                    "score": item.get("score"),
                }
            )
    return results


_PROVIDERS: dict[str, Callable[..., list[dict[str, Any]]]] = {"tavily": tavily_search}


def search(query: str, *, provider: str = "tavily", **kwargs: Any) -> list[dict[str, Any]]:
    """Dispatch one search to the configured provider."""
    fn = _PROVIDERS.get(provider)
    if fn is None:
        raise SearchError(f"unknown search provider: {provider!r}; known: {sorted(_PROVIDERS)}")
    return fn(query, **kwargs)
