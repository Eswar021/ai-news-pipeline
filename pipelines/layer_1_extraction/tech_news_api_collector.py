"""
Module: tech_news_api_collector
Layer: 1 — Source Extraction
Purpose: Collect AI news articles from multiple news APIs (NewsAPI, Newsdata, Mediastack)
         and output RawExtractedDocument records. Wraps existing fetch_news() functions
         from each API collector — no re-implementation, just schema mapping.

Run standalone:
    python tech_news_api_collector.py
    python tech_news_api_collector.py --query "OpenAI GPT" --max 5
"""

import sys
import hashlib
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_1_extraction.raw_document_writer import write_raw_documents, read_raw_documents
from pipelines.layer_1_extraction.raw_payload_writer import save_payload
from pipelines.layer_1_extraction.extraction_audit_logger import log_event


_COLLECTOR_NAME = "tech_news_api_collector"
_SOURCE_GROUP   = "tech_news_apis"


def _to_raw_document(article: dict, run_id: str, source_id: str, source_name: str) -> dict:
    """Map a news API article dict to RawExtractedDocument schema."""
    content_hash = article.get("content_hash") or hashlib.sha256(
        f"{article.get('url', '')}:{article.get('title', '')}".encode()
    ).hexdigest()[:16]

    raw_text = article.get("raw_text") or article.get("content") or article.get("description", "")
    content_available = "full" if len(raw_text) > 500 else ("partial" if raw_text else "title_only")

    return {
        "raw_document_id": f"rawdoc_{source_id}_{content_hash}",
        "run_id": run_id,
        "source": {
            "source_id": source_id,
            "source_name": source_name,
            "source_group": _SOURCE_GROUP,
            "source_type": "tech_news_api",
            "trust_tier_hint": 2,
        },
        "item": {
            "title": article.get("title", ""),
            "url": article.get("url", ""),
            "published_at": article.get("published_at", ""),
            "author": article.get("author", ""),
            "publisher": article.get("publisher", "") or article.get("source_name", ""),
            "description": article.get("description", ""),
            "language": article.get("language", "en"),
            "query_used": article.get("query_used", ""),
        },
        "content": {
            "raw_text": raw_text,
            "content_available": content_available,
        },
        "collection": {
            "collector_name": _COLLECTOR_NAME,
            "collection_method": article.get("module", "news_api").replace("_collector", "_api"),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "extraction_status": "success",
        },
    }


def _collect_from_source(run_id, fetch_fn, source_id, source_name, query, max_results,
                          output_path, layer1_dir, extra_kwargs=None):
    """Generic helper: call fetch_fn, map results, write docs."""
    try:
        kwargs = {"query": query, "max_results": max_results}
        if extra_kwargs:
            kwargs.update(extra_kwargs)
        articles = fetch_fn(**kwargs)
    except Exception as exc:
        log_event(run_id, source_id, _COLLECTOR_NAME,
                  "api_error", "error", f"{source_id} fetch failed: {exc}")
        return []

    if not articles:
        log_event(run_id, source_id, _COLLECTOR_NAME,
                  "empty_result", "warning", f"No articles from {source_id}")
        return []

    docs = [_to_raw_document(a, run_id, source_id, source_name) for a in articles]
    write_raw_documents(docs, output_path)

    import json
    save_payload(run_id, f"batch_{source_id}", _SOURCE_GROUP, source_id,
                 "json", json.dumps(articles, ensure_ascii=False), layer1_dir)

    log_event(run_id, source_id, _COLLECTOR_NAME,
              "success_note", "info",
              f"Fetched {len(docs)} articles from {source_name}",
              extra={"doc_count": len(docs)})

    return docs


def collect(
    run_id: str,
    query: str = "artificial intelligence OR LLM OR AI agent",
    max_per_source: int = 10,
    sources: list = None,
    output_path: Path = None,
    layer1_dir: Path = None,
) -> list:
    """
    Collect news from all enabled tech news APIs and return RawExtractedDocuments.

    Args:
        run_id:          Pipeline run identifier
        query:           Search query string
        max_per_source:  Max articles per API source
        sources:         List of source IDs to enable (default: all)
        output_path:     raw_documents.jsonl path
        layer1_dir:      Layer 1 directory for payload storage

    Returns:
        List of RawExtractedDocument dicts
    """
    if output_path is None:
        output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"
    if sources is None:
        sources = ["newsapi_ai", "newsdata_ai", "mediastack_ai"]

    all_docs = []

    if "newsapi_ai" in sources:
        from pipelines.layer_1_extraction.newsapi_collector import fetch_news as fetch_newsapi
        docs = _collect_from_source(
            run_id, fetch_newsapi, "newsapi_ai", "NewsAPI.org",
            query, max_per_source, output_path, layer1_dir,
        )
        all_docs.extend(docs)

    if "newsdata_ai" in sources:
        from pipelines.layer_1_extraction.newsdata_collector import fetch_news as fetch_newsdata
        docs = _collect_from_source(
            run_id, fetch_newsdata, "newsdata_ai", "Newsdata.io",
            query, max_per_source, output_path, layer1_dir,
        )
        all_docs.extend(docs)

    if "mediastack_ai" in sources:
        from pipelines.layer_1_extraction.mediastack_collector import fetch_news as fetch_mediastack
        docs = _collect_from_source(
            run_id, fetch_mediastack, "mediastack_ai", "Mediastack",
            query, max_per_source, output_path, layer1_dir,
        )
        all_docs.extend(docs)

    return all_docs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect tech news articles → RawExtractedDocument")
    parser.add_argument("--query", default="artificial intelligence OR LLM",
                        help="Search query")
    parser.add_argument("--max", type=int, default=5,
                        help="Max articles per source (default: 5)")
    parser.add_argument("--sources", nargs="+",
                        default=["newsapi_ai", "newsdata_ai", "mediastack_ai"],
                        help="Which news sources to collect from")
    args = parser.parse_args()

    run_id = "test_run_news"
    output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if output_path.exists():
        output_path.unlink()

    print(f"Collecting news: '{args.query}' from {args.sources}...\n")
    docs = collect(run_id=run_id, query=args.query, max_per_source=args.max, sources=args.sources)

    print(f"\nCollected {len(docs)} total articles:\n")
    for d in docs:
        print(f"  [{d['source']['source_id']}] {d['item']['title'][:70]}")
        print(f"    Content: {d['content']['content_available']}  ({len(d['content']['raw_text'])} chars)")
        print()

    result = read_raw_documents(output_path)
    print(f"Verified: {len(result)} records written to {output_path}")
