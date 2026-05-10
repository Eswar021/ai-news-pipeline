"""
Module: community_signal_collector
Layer: 1 — Source Extraction
Purpose: Collect community signals from Hacker News (and optionally Reddit) and output
         RawExtractedDocument records. role = trend_signal_only — these are NOT used
         as primary evidence in script writing, only to detect what's getting attention.
         Wraps hackernews_collector.fetch_ai_stories() — no re-implementation.

Run standalone:
    python community_signal_collector.py
    python community_signal_collector.py --max 10 --type top
"""

import sys
import hashlib
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_1_extraction.hackernews_collector import fetch_ai_stories
from pipelines.layer_1_extraction.raw_document_writer import write_raw_documents, read_raw_documents
from pipelines.layer_1_extraction.raw_payload_writer import save_payload
from pipelines.layer_1_extraction.extraction_audit_logger import log_event


_COLLECTOR_NAME = "community_signal_collector"
_SOURCE_GROUP   = "community_signals"


def _to_raw_document(story: dict, run_id: str) -> dict:
    """Map a hackernews_collector story dict to RawExtractedDocument schema."""
    content_hash = story.get("content_hash") or hashlib.sha256(
        f"hn:{story.get('document_id', '')}".encode()
    ).hexdigest()[:16]

    raw_text = story.get("raw_text", "")  # only populated for Ask HN / Show HN posts
    content_available = "full" if raw_text else "title_only"

    return {
        "raw_document_id": f"rawdoc_hackernews_ai_{content_hash}",
        "run_id": run_id,
        "source": {
            "source_id": "hackernews_ai",
            "source_name": "Hacker News AI",
            "source_group": _SOURCE_GROUP,
            "source_type": "community_signal",
            "trust_tier_hint": 3,
            "role": "trend_signal_only",
        },
        "item": {
            "title": story.get("title", ""),
            "url": story.get("url", ""),
            "hn_discussion_url": story.get("hn_discussion_url", ""),
            "published_at": story.get("published_at", ""),
            "author": story.get("author", ""),
            "score": story.get("score", 0),
            "comment_count": story.get("comment_count", 0),
            "signal_type": story.get("signal_type", "developer_discussion"),
        },
        "content": {
            "raw_text": raw_text,
            "content_available": content_available,
        },
        "collection": {
            "collector_name": _COLLECTOR_NAME,
            "collection_method": "hackernews_firebase_api",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "extraction_status": "success",
        },
    }


def collect(
    run_id: str,
    story_type: str = "top",
    max_stories: int = 20,
    scan_depth: int = 100,
    output_path: Path = None,
    layer1_dir: Path = None,
) -> list:
    """
    Fetch AI-related HN stories and return as RawExtractedDocuments.

    Args:
        run_id:       Pipeline run identifier
        story_type:   "top", "new", or "best"
        max_stories:  Max AI stories to collect
        scan_depth:   How many HN top stories to scan
        output_path:  raw_documents.jsonl path
        layer1_dir:   Layer 1 directory for payload storage

    Returns:
        List of RawExtractedDocument dicts
    """
    if output_path is None:
        output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    source_id = "hackernews_ai"

    try:
        stories = fetch_ai_stories(story_type=story_type, max_stories=max_stories, scan_depth=scan_depth)
    except Exception as exc:
        log_event(run_id, source_id, _COLLECTOR_NAME,
                  "api_error", "error", f"HN fetch failed: {exc}")
        return []

    if not stories:
        log_event(run_id, source_id, _COLLECTOR_NAME,
                  "empty_result", "warning", "No AI stories found on HN")
        return []

    docs = [_to_raw_document(s, run_id) for s in stories]
    write_raw_documents(docs, output_path)

    import json
    save_payload(run_id, f"batch_{source_id}_{story_type}", _SOURCE_GROUP, source_id,
                 "json", json.dumps(stories, ensure_ascii=False), layer1_dir)

    log_event(run_id, source_id, _COLLECTOR_NAME,
              "success_note", "info",
              f"Collected {len(docs)} HN {story_type} stories",
              extra={"doc_count": len(docs), "story_type": story_type})

    return docs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect HN community signals → RawExtractedDocument")
    parser.add_argument("--type", default="top", choices=["top", "new", "best"])
    parser.add_argument("--max", type=int, default=10, help="Max AI stories (default: 10)")
    parser.add_argument("--scan", type=int, default=80, help="Stories to scan (default: 80)")
    args = parser.parse_args()

    run_id = "test_run_community"
    output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if output_path.exists():
        output_path.unlink()

    print(f"Scanning HN {args.type} stories for AI content (max {args.max})...\n")
    docs = collect(run_id=run_id, story_type=args.type, max_stories=args.max, scan_depth=args.scan)

    print(f"\nCollected {len(docs)} community signals:\n")
    for d in docs:
        score = d["item"]["score"]
        comments = d["item"]["comment_count"]
        print(f"  [{score}⬆ {comments}💬] {d['item']['title'][:70]}")

    result = read_raw_documents(output_path)
    print(f"\nVerified: {len(result)} records written to {output_path}")
