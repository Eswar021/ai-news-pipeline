"""
Module: github_open_source_collector
Layer: 1 — Source Extraction
Purpose: Collect trending AI GitHub repositories (with READMEs) and output
         RawExtractedDocument records. GitHub repos show what tools the dev
         community is actually building and using — important for open-source AI stories.
         Wraps github_collector.fetch_trending_repos() — no re-implementation.

Run standalone:
    python github_open_source_collector.py
    python github_open_source_collector.py --query "LLM agent" --max 5
"""

import sys
import hashlib
import argparse
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_1_extraction.github_collector import fetch_trending_repos
from pipelines.layer_1_extraction.raw_document_writer import write_raw_documents, read_raw_documents
from pipelines.layer_1_extraction.raw_payload_writer import save_payload
from pipelines.layer_1_extraction.extraction_audit_logger import log_event
from pipelines.layer_1_extraction.window_filter import filter_raw_documents_by_window


_COLLECTOR_NAME = "github_open_source_collector"
_SOURCE_GROUP   = "github_open_source_signals"


def _to_raw_document(repo: dict, run_id: str) -> dict:
    """Map a github_collector repo dict to RawExtractedDocument schema."""
    content_hash = repo.get("content_hash") or hashlib.sha256(
        f"github:{repo.get('title', '')}".encode()
    ).hexdigest()[:16]

    raw_text = repo.get("readme_text") or repo.get("raw_text") or repo.get("description", "")
    content_available = "full" if repo.get("readme_text") else ("partial" if raw_text else "title_only")

    return {
        "raw_document_id": f"rawdoc_github_trending_ai_{content_hash}",
        "run_id": run_id,
        "source": {
            "source_id": "github_trending_ai",
            "source_name": "GitHub Trending AI",
            "source_group": _SOURCE_GROUP,
            "source_type": "open_source_project",
            "trust_tier_hint": 3,
        },
        "item": {
            "title": repo.get("title", ""),        # full_name e.g. "org/repo"
            "url": repo.get("url", ""),
            "published_at": repo.get("published_at", ""),   # pushed_at
            "created_at": repo.get("created_at", ""),
            "author": repo.get("author", ""),               # owner
            "description": repo.get("description", ""),
            "language": repo.get("language", ""),
            "stars": repo.get("stars", 0),
            "forks": repo.get("forks", 0),
            "topics": repo.get("topics", []),
            "license": repo.get("license", ""),
            "query_used": repo.get("query_used", ""),
            "signal_type": "open_source_project",
        },
        "content": {
            "raw_text": raw_text,
            "content_available": content_available,
        },
        "collection": {
            "collector_name": _COLLECTOR_NAME,
            "collection_method": "github_api",
            "collected_at": now_project_iso(),
            "extraction_status": "success",
        },
    }


def collect(
    run_id: str,
    queries: list = None,
    max_per_query: int = 5,
    days_back: int = 7,
    include_readme: bool = True,
    output_path: Path = None,
    layer1_dir: Path = None,
    start_at: str = None,
    end_at: str = None,
) -> list:
    """
    Fetch trending AI GitHub repos for each query and return RawExtractedDocuments.

    Args:
        run_id:          Pipeline run identifier
        queries:         Search queries (default: broad AI + agent topics)
        max_per_query:   Max repos per query
        days_back:       Only repos active in last N days
        include_readme:  Fetch each repo's README (more content, slower)
        output_path:     raw_documents.jsonl path
        layer1_dir:      Layer 1 directory for payload storage

    Returns:
        List of RawExtractedDocument dicts
    """
    if queries is None:
        queries = ["artificial intelligence LLM", "AI agent autonomous"]
    if output_path is None:
        output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    all_docs = []
    seen_urls = set()

    for query in queries:
        source_id = f"github_{query.replace(' ', '_')[:20].lower()}"

        try:
            repos = fetch_trending_repos(
                query=query,
                max_results=max_per_query,
                days_back=days_back,
                include_readme=include_readme,
            )
        except Exception as exc:
            log_event(run_id, "github_trending_ai", _COLLECTOR_NAME,
                      "api_error", "error", f"GitHub fetch failed for '{query}': {exc}")
            continue

        if not repos:
            log_event(run_id, "github_trending_ai", _COLLECTOR_NAME,
                      "empty_result", "warning", f"No repos found for '{query}'")
            continue

        # Deduplicate across queries
        new_repos = [r for r in repos if r.get("url") not in seen_urls]
        for r in new_repos:
            seen_urls.add(r.get("url"))

        docs = [_to_raw_document(r, run_id) for r in new_repos]
        docs, filter_stats = filter_raw_documents_by_window(
            docs, start_at=start_at, end_at=end_at
        )

        import json
        save_payload(run_id, f"batch_github_{query[:20].replace(' ', '_')}", _SOURCE_GROUP,
                     "github_trending_ai", "json", json.dumps(new_repos, ensure_ascii=False), layer1_dir)

        if filter_stats["outside_window_count"] > 0:
            log_event(
                run_id, "github_trending_ai", _COLLECTOR_NAME,
                "success_note", "info",
                f"Dropped {filter_stats['outside_window_count']} GitHub repo(s) outside the manifest window for '{query}'.",
                extra=filter_stats,
            )
        if filter_stats["undated_or_unparseable_count"] > 0:
            log_event(
                run_id, "github_trending_ai", _COLLECTOR_NAME,
                "date_missing", "warning",
                f"Kept {filter_stats['undated_or_unparseable_count']} GitHub repo(s) with missing or unparseable publish dates for '{query}'.",
                extra=filter_stats,
            )
        if not docs:
            log_event(
                run_id, "github_trending_ai", _COLLECTOR_NAME,
                "empty_result", "warning",
                f"All fetched GitHub repos were outside the manifest window for '{query}'.",
                extra=filter_stats,
            )
            continue

        write_raw_documents(docs, output_path)

        log_event(run_id, "github_trending_ai", _COLLECTOR_NAME,
                  "success_note", "info",
                  f"Fetched {len(docs)} repos for '{query}'",
                  extra={"doc_count": len(docs), "query": query, **filter_stats})

        all_docs.extend(docs)

    return all_docs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect GitHub repos → RawExtractedDocument")
    parser.add_argument("--query", default="artificial intelligence LLM",
                        help="Search query (default: 'artificial intelligence LLM')")
    parser.add_argument("--max", type=int, default=5, help="Max repos (default: 5)")
    parser.add_argument("--days", type=int, default=7, help="Days back (default: 7)")
    parser.add_argument("--no-readme", action="store_true", help="Skip README fetching")
    args = parser.parse_args()

    run_id = "test_run_github"
    output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if output_path.exists():
        output_path.unlink()

    print(f"Collecting GitHub repos for '{args.query}' (last {args.days} days)...\n")
    docs = collect(
        run_id=run_id,
        queries=[args.query],
        max_per_query=args.max,
        days_back=args.days,
        include_readme=not args.no_readme,
    )

    print(f"\nCollected {len(docs)} repos:\n")
    for d in docs:
        stars = d["item"]["stars"]
        lang  = d["item"]["language"]
        print(f"  [{stars}⭐ {lang}] {d['item']['title']}")
        print(f"    Content: {d['content']['content_available']}  ({len(d['content']['raw_text'])} chars)")
        print()

    result = read_raw_documents(output_path)
    print(f"Verified: {len(result)} records written to {output_path}")
