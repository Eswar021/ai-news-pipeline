"""
Module: research_paper_collector
Layer: 1 — Source Extraction
Purpose: Collect research papers from arXiv and output RawExtractedDocument records.
         Wraps arxiv_collector.fetch_arxiv_papers() — no re-implementation.
         One RawExtractedDocument per paper, abstract as content.

Run standalone:
    python research_paper_collector.py
    python research_paper_collector.py --categories cs.AI cs.LG --max 5
"""

import sys
import hashlib
import argparse
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_1_extraction.arxiv_collector import fetch_arxiv_papers
from pipelines.layer_1_extraction.raw_document_writer import write_raw_documents, read_raw_documents
from pipelines.layer_1_extraction.raw_payload_writer import save_payload
from pipelines.layer_1_extraction.extraction_audit_logger import log_event
from pipelines.layer_1_extraction.window_filter import filter_raw_documents_by_window


_COLLECTOR_NAME = "research_paper_collector"
_SOURCE_GROUP   = "research_papers"


def _to_raw_document(paper: dict, run_id: str, source_id: str, source_name: str) -> dict:
    """Map an arxiv_collector paper dict to RawExtractedDocument schema."""
    content_hash = paper.get("content_hash") or hashlib.sha256(
        f"{paper.get('url', '')}:{paper.get('title', '')}".encode()
    ).hexdigest()[:16]

    raw_text = paper.get("abstract") or paper.get("raw_text", "")
    content_available = "abstract_only" if raw_text else "title_only"

    return {
        "raw_document_id": f"rawdoc_{source_id}_{content_hash}",
        "run_id": run_id,
        "source": {
            "source_id": source_id,
            "source_name": source_name,
            "source_group": _SOURCE_GROUP,
            "source_type": "research_paper",
            "trust_tier_hint": 1.5,
        },
        "item": {
            "title": paper.get("title", ""),
            "url": paper.get("url", ""),
            "pdf_url": paper.get("pdf_url", ""),
            "published_at": paper.get("published_at", ""),
            "author": ", ".join(paper.get("authors", [])[:5]),
            "authors": paper.get("authors", []),
            "categories": paper.get("categories", []),
            "primary_category": paper.get("primary_category", ""),
            "arxiv_id": paper.get("document_id", "").replace("arxiv_", ""),
            "doi": paper.get("doi", ""),
            "journal_ref": paper.get("journal_ref", ""),
        },
        "content": {
            "raw_text": raw_text,
            "content_available": content_available,
        },
        "collection": {
            "collector_name": _COLLECTOR_NAME,
            "collection_method": "arxiv_api",
            "collected_at": now_project_iso(),
            "extraction_status": "success",
        },
    }


def collect(
    run_id: str,
    categories: list = None,
    max_per_category: int = 10,
    output_path: Path = None,
    layer1_dir: Path = None,
    start_at: str = None,
    end_at: str = None,
) -> list:
    """
    Fetch papers from arXiv for each category and return as RawExtractedDocuments.

    Args:
        run_id:            Pipeline run identifier
        categories:        arXiv categories (default: cs.AI, cs.LG, cs.CL)
        max_per_category:  Max papers to fetch per category
        output_path:       raw_documents.jsonl path (derived from run_id if None)
        layer1_dir:        Layer 1 directory for payload storage

    Returns:
        List of RawExtractedDocument dicts (also written to output_path)
    """
    if categories is None:
        categories = ["cs.AI", "cs.LG", "cs.CL"]
    if output_path is None:
        output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    all_docs = []

    for cat in categories:
        source_id   = f"arxiv_{cat.replace('.', '_').lower()}"
        source_name = f"arXiv {cat}"

        try:
            papers = fetch_arxiv_papers(category=cat, max_results=max_per_category)
        except Exception as exc:
            log_event(run_id, source_id, _COLLECTOR_NAME,
                      "api_error", "error", f"arXiv fetch failed for {cat}: {exc}")
            continue

        if not papers:
            log_event(run_id, source_id, _COLLECTOR_NAME,
                      "empty_result", "warning", f"No papers returned for {cat}")
            continue

        docs = [_to_raw_document(p, run_id, source_id, source_name) for p in papers]
        docs, filter_stats = filter_raw_documents_by_window(
            docs, start_at=start_at, end_at=end_at
        )

        # Save one combined payload per category (the raw API response is reconstructed as JSON)
        import json
        save_payload(run_id, f"batch_{source_id}", _SOURCE_GROUP, source_id,
                     "json", json.dumps(papers, ensure_ascii=False), layer1_dir)

        if filter_stats["outside_window_count"] > 0:
            log_event(
                run_id, source_id, _COLLECTOR_NAME,
                "success_note", "info",
                f"Dropped {filter_stats['outside_window_count']} paper(s) outside the manifest window for {cat}.",
                extra=filter_stats,
            )
        if filter_stats["undated_or_unparseable_count"] > 0:
            log_event(
                run_id, source_id, _COLLECTOR_NAME,
                "date_missing", "warning",
                f"Kept {filter_stats['undated_or_unparseable_count']} paper(s) with missing or unparseable publish dates for {cat}.",
                extra=filter_stats,
            )
        if not docs:
            log_event(
                run_id, source_id, _COLLECTOR_NAME,
                "empty_result", "warning",
                f"All fetched papers for {cat} were outside the manifest window.",
                extra=filter_stats,
            )
            continue

        write_raw_documents(docs, output_path)

        log_event(run_id, source_id, _COLLECTOR_NAME,
                  "success_note", "info",
                  f"Fetched {len(docs)} papers from {cat}",
                  extra={"doc_count": len(docs), "category": cat, **filter_stats})

        all_docs.extend(docs)

    return all_docs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect arXiv research papers → RawExtractedDocument")
    parser.add_argument("--categories", nargs="+", default=["cs.AI", "cs.LG"],
                        help="arXiv categories (default: cs.AI cs.LG)")
    parser.add_argument("--max", type=int, default=5,
                        help="Max papers per category (default: 5)")
    args = parser.parse_args()

    run_id = "test_run_research"
    output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if output_path.exists():
        output_path.unlink()

    print(f"Collecting papers from arXiv: {args.categories} (max {args.max} each)...\n")
    docs = collect(run_id=run_id, categories=args.categories, max_per_category=args.max)

    print(f"\nCollected {len(docs)} total papers:\n")
    for d in docs:
        print(f"  [{d['source']['source_id']}] {d['item']['title'][:70]}")
        print(f"    Authors: {d['item']['author'][:60]}")
        print(f"    Content: {d['content']['content_available']}  ({len(d['content']['raw_text'])} chars)")
        print()

    result = read_raw_documents(output_path)
    print(f"Verified: {len(result)} records written to {output_path}")
