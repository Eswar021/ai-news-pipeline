"""topic_research search client: provider seam + Tavily result parsing."""
from __future__ import annotations

import pytest

from src.pipeline.content.topic_research.search_client import SearchError, search, tavily_search


class _Resp:
    def __init__(self, *, status: int = 200, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


_TAVILY_PAYLOAD = {
    "query": "x",
    "results": [
        {"title": "Primary source", "url": "https://cdn.openai.com/pdf/ten-proofs.pdf", "content": "Astra proved…", "score": 0.9},
        {"title": "Coverage", "url": "https://aiweekly.co/astra", "content": "OpenAI released…", "score": 0.8},
        {"title": "No content", "url": "https://x.com/a", "content": "", "score": 0.5},  # dropped
        {"title": "No url", "url": "", "content": "orphan", "score": 0.4},  # dropped
    ],
}


def _fake_post(pages: dict | None = None):
    def post(url, **_kwargs):
        return _Resp(payload=_TAVILY_PAYLOAD)

    return post


def test_tavily_search_parses_and_drops_empty_results() -> None:
    results = tavily_search("q", api_key="k", http_post=_fake_post())
    assert [r["url"] for r in results] == [
        "https://cdn.openai.com/pdf/ten-proofs.pdf",
        "https://aiweekly.co/astra",
    ]
    assert results[0]["title"] == "Primary source" and results[0]["score"] == 0.9


def test_missing_key_raises() -> None:
    with pytest.raises(SearchError, match="TAVILY_API_KEY"):
        tavily_search("q", api_key="", http_post=_fake_post())


def test_non_200_raises() -> None:
    def post(url, **_kwargs):
        return _Resp(status=429, text="rate limited")

    with pytest.raises(SearchError, match="429"):
        tavily_search("q", api_key="k", http_post=post)


def test_search_dispatch_rejects_unknown_provider() -> None:
    with pytest.raises(SearchError, match="unknown search provider"):
        search("q", provider="nope", api_key="k", http_post=_fake_post())


def test_search_dispatch_routes_to_tavily() -> None:
    results = search("q", provider="tavily", api_key="k", http_post=_fake_post())
    assert len(results) == 2
