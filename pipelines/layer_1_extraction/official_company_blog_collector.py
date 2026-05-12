"""
Module: official_company_blog_collector
Layer: 1 — Source Extraction
Purpose: Collect posts from official AI company blogs (OpenAI, Anthropic, etc.) and
         output RawExtractedDocument records. These are tier-1 primary evidence sources.
         Wraps company_blogs/openai_blog.py and company_blogs/anthropic_blog.py.

Run standalone:
    python official_company_blog_collector.py
    python official_company_blog_collector.py --sources openai anthropic --max 5
"""

import sys
import hashlib
import argparse
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_1_extraction.raw_document_writer import write_raw_documents, read_raw_documents
from pipelines.layer_1_extraction.raw_payload_writer import save_payload
from pipelines.layer_1_extraction.extraction_audit_logger import log_event
from pipelines.layer_1_extraction.window_filter import filter_raw_documents_by_window


_COLLECTOR_NAME = "official_company_blog_collector"
_SOURCE_GROUP   = "ai_company_blogs"

# Map of source slug → (source_id, source_name, fetch_function_import_path)
_SOURCES = {
    "openai": {
        "source_id": "openai_news",
        "source_name": "OpenAI News",
        "module": "pipelines.layer_1_extraction.company_blogs.openai_blog",
        "fetch_fn": "fetch_posts",
    },
    "anthropic": {
        "source_id": "anthropic_news",
        "source_name": "Anthropic News",
        "module": "pipelines.layer_1_extraction.company_blogs.anthropic_blog",
        "fetch_fn": "fetch_posts",
    },
}


def _to_raw_document(post: dict, run_id: str, source_id: str, source_name: str) -> dict:
    """Map a blog_utils make_document dict to RawExtractedDocument schema."""
    content_hash = post.get("content_hash") or hashlib.sha256(
        f"blog:{post.get('url', '')}:{post.get('title', '')}".encode()
    ).hexdigest()[:16]

    raw_text = post.get("raw_text", "")
    content_available = "full" if len(raw_text) > 200 else ("partial" if raw_text else "title_only")

    return {
        "raw_document_id": f"rawdoc_{source_id}_{content_hash}",
        "run_id": run_id,
        "source": {
            "source_id": source_id,
            "source_name": source_name,
            "source_group": _SOURCE_GROUP,
            "source_type": "official_company_blog",
            "trust_tier_hint": 1,
        },
        "item": {
            "title": post.get("title", ""),
            "url": post.get("url", ""),
            "published_at": post.get("published_at", ""),
            "author": post.get("author", ""),
            "company": post.get("company", ""),
        },
        "content": {
            "raw_text": raw_text,
            "content_available": content_available,
        },
        "collection": {
            "collector_name": _COLLECTOR_NAME,
            "collection_method": "rss_or_html",
            "collected_at": now_project_iso(),
            "extraction_status": "success",
        },
    }


def collect(
    run_id: str,
    sources: list = None,
    max_per_source: int = 10,
    output_path: Path = None,
    layer1_dir: Path = None,
    start_at: str = None,
    end_at: str = None,
) -> list:
    """
    Collect blog posts from AI company official blogs.

    Args:
        run_id:          Pipeline run identifier
        sources:         List of source slugs (default: all — openai, anthropic)
        max_per_source:  Max posts per source
        output_path:     raw_documents.jsonl path
        layer1_dir:      Layer 1 directory for payload storage

    Returns:
        List of RawExtractedDocument dicts
    """
    if sources is None:
        sources = list(_SOURCES.keys())
    if output_path is None:
        output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    all_docs = []

    for slug in sources:
        cfg = _SOURCES.get(slug)
        if not cfg:
            continue

        source_id   = cfg["source_id"]
        source_name = cfg["source_name"]

        try:
            import importlib
            mod = importlib.import_module(cfg["module"])
            fetch_fn = getattr(mod, cfg["fetch_fn"])
            posts = fetch_fn(max_results=max_per_source)
        except Exception as exc:
            log_event(run_id, source_id, _COLLECTOR_NAME,
                      "fetch_blocked", "error", f"{source_name} fetch failed: {exc}")
            continue

        if not posts:
            log_event(run_id, source_id, _COLLECTOR_NAME,
                      "empty_result", "warning", f"No posts from {source_name}")
            continue

        docs = [_to_raw_document(p, run_id, source_id, source_name) for p in posts]
        docs, filter_stats = filter_raw_documents_by_window(
            docs, start_at=start_at, end_at=end_at
        )

        import json
        save_payload(run_id, f"batch_{source_id}", _SOURCE_GROUP, source_id,
                     "json", json.dumps(posts, ensure_ascii=False), layer1_dir)

        if filter_stats["outside_window_count"] > 0:
            log_event(
                run_id, source_id, _COLLECTOR_NAME,
                "success_note", "info",
                f"Dropped {filter_stats['outside_window_count']} {source_name} post(s) outside the manifest window.",
                extra=filter_stats,
            )
        if filter_stats["undated_or_unparseable_count"] > 0:
            log_event(
                run_id, source_id, _COLLECTOR_NAME,
                "date_missing", "warning",
                f"Kept {filter_stats['undated_or_unparseable_count']} {source_name} post(s) with missing or unparseable publish dates during window enforcement.",
                extra=filter_stats,
            )
        if not docs:
            log_event(
                run_id, source_id, _COLLECTOR_NAME,
                "empty_result", "warning",
                f"All fetched {source_name} posts were outside the manifest window.",
                extra=filter_stats,
            )
            continue

        write_raw_documents(docs, output_path)

        log_event(run_id, source_id, _COLLECTOR_NAME,
                  "success_note", "info",
                  f"Fetched {len(docs)} posts from {source_name}",
                  extra={"doc_count": len(docs), **filter_stats})

        all_docs.extend(docs)

    return all_docs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect company blog posts → RawExtractedDocument")
    parser.add_argument("--sources", nargs="+", default=["openai", "anthropic"],
                        help="Blog sources to collect (default: openai anthropic)")
    parser.add_argument("--max", type=int, default=5,
                        help="Max posts per source (default: 5)")
    args = parser.parse_args()

    run_id = "test_run_blogs"
    output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if output_path.exists():
        output_path.unlink()

    print(f"Collecting blog posts from: {args.sources}...\n")
    docs = collect(run_id=run_id, sources=args.sources, max_per_source=args.max)

    print(f"\nCollected {len(docs)} blog posts:\n")
    for d in docs:
        print(f"  [{d['source']['source_id']}] {d['item']['title'][:70]}")
        print(f"    Published: {d['item']['published_at'][:25]}")
        print(f"    Content: {d['content']['content_available']}  ({len(d['content']['raw_text'])} chars)")
        print()

    result = read_raw_documents(output_path)
    print(f"Verified: {len(result)} records written to {output_path}")
