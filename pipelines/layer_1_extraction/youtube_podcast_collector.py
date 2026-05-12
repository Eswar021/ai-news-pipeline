"""
Module: youtube_podcast_collector
Layer: 1 — Source Extraction
Purpose: Collect YouTube video transcripts from configured AI channels and output
         RawExtractedDocument records. Transcripts are treated as primary content —
         timestamp-chunked blocks enable source span citation in script writing.
         Wraps youtube_collector functions — no re-implementation.

Run standalone:
    python youtube_podcast_collector.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
    python youtube_podcast_collector.py --channel UCxxxxx --name "Channel Name" --days 2
"""

import sys
import os
import hashlib
import argparse
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR, CHANNELS_YAML
from pipelines.runtime_manifest import get_youtube_registry_snapshot

from pipelines.layer_1_extraction.youtube_collector import collect_single_video, collect_channel
from pipelines.layer_1_extraction.raw_document_writer import write_raw_documents, read_raw_documents
from pipelines.layer_1_extraction.raw_payload_writer import save_payload
from pipelines.layer_1_extraction.extraction_audit_logger import log_event
from pipelines.layer_1_extraction.window_filter import filter_raw_documents_by_window


_COLLECTOR_NAME = "youtube_podcast_collector"
_SOURCE_GROUP   = "youtube_podcast_transcripts"


def _to_raw_document(video: dict, run_id: str, source_id: str = "youtube_ai_channels",
                     source_name: str = "YouTube AI Channels") -> dict:
    """Map a youtube_collector video dict to RawExtractedDocument schema."""
    content_hash = video.get("content_hash") or hashlib.sha256(
        f"youtube:{video.get('video_id', '')}".encode()
    ).hexdigest()[:16]

    raw_text = video.get("raw_text", "")
    transcript_blocks = video.get("transcript_blocks", [])
    has_transcript = bool(raw_text)

    if has_transcript and transcript_blocks:
        content_available = "full"
    elif has_transcript:
        content_available = "partial"
    else:
        content_available = "title_only"

    return {
        "raw_document_id": f"rawdoc_{source_id}_{content_hash}",
        "run_id": run_id,
        "source": {
            "source_id": source_id,
            "source_name": source_name,
            "source_group": _SOURCE_GROUP,
            "source_type": "video_transcript",
            "trust_tier_hint": 2,
        },
        "item": {
            "title": video.get("title", ""),
            "url": video.get("url", ""),
            "published_at": video.get("published_at", ""),
            "author": video.get("author", "") or video.get("channel_name", ""),
            "video_id": video.get("video_id", ""),
            "channel_name": video.get("channel_name", ""),
            "channel_id": video.get("channel_id", ""),
        },
        "content": {
            "raw_text": raw_text,
            "transcript_blocks": transcript_blocks,      # [{start_time, text}] for timestamp citations
            "content_available": content_available,
            "transcript_block_count": len(transcript_blocks),
            "transcript_char_count": len(raw_text),
        },
        "collection": {
            "collector_name": _COLLECTOR_NAME,
            "collection_method": "youtube_transcript_api",
            "collected_at": now_project_iso(),
            "extraction_status": "success" if has_transcript else "partial",
        },
    }


def collect_from_url(run_id: str, video_url: str,
                     output_path: Path = None, layer1_dir: Path = None) -> dict:
    """Collect transcript for a single video URL."""
    if output_path is None:
        output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    try:
        video = collect_single_video(video_url=video_url)
    except Exception as exc:
        log_event(run_id, "youtube_ai_channels", _COLLECTOR_NAME,
                  "fetch_blocked", "error", f"Transcript fetch failed for {video_url}: {exc}")
        return {}

    doc = _to_raw_document(video, run_id)
    write_raw_documents([doc], output_path)

    import json
    save_payload(run_id, doc["raw_document_id"], _SOURCE_GROUP, "youtube_ai_channels",
                 "json", json.dumps(video, ensure_ascii=False), layer1_dir)

    log_event(run_id, "youtube_ai_channels", _COLLECTOR_NAME,
              "success_note", "info",
              f"Collected transcript for {video.get('video_id', '?')} ({len(video.get('raw_text', ''))} chars)",
              extra={"video_id": video.get("video_id"), "block_count": len(video.get("transcript_blocks", []))})

    return doc


def collect_from_channel(
    run_id: str,
    channel_id: str,
    channel_name: str = "",
    days_back: int = 2,
    max_per_duration: int = 3,
    output_path: Path = None,
    layer1_dir: Path = None,
    search_query: str = None,
    start_at: str = None,
    end_at: str = None,
) -> list:
    """Collect recent video transcripts from a YouTube channel."""
    if output_path is None:
        output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    source_id = f"youtube_{channel_id[:12].lower()}"
    source_name = channel_name or channel_id

    try:
        videos = collect_channel(
            channel_id=channel_id,
            channel_name=channel_name,
            days_back=days_back,
            max_per_duration=max_per_duration,
            search_query=search_query,
        )
    except Exception as exc:
        log_event(run_id, source_id, _COLLECTOR_NAME,
                  "api_error", "error", f"Channel collection failed for {channel_name}: {exc}")
        return []

    if not videos:
        log_event(run_id, source_id, _COLLECTOR_NAME,
                  "empty_result", "warning", f"No videos found for channel {channel_name}")
        return []

    docs = [_to_raw_document(v, run_id, source_id, source_name) for v in videos]
    docs, filter_stats = filter_raw_documents_by_window(
        docs, start_at=start_at, end_at=end_at
    )

    import json
    save_payload(run_id, f"batch_{source_id}", _SOURCE_GROUP, source_id,
                 "json", json.dumps(videos, ensure_ascii=False), layer1_dir)

    if filter_stats["outside_window_count"] > 0:
        log_event(
            run_id, source_id, _COLLECTOR_NAME,
            "success_note", "info",
            f"Dropped {filter_stats['outside_window_count']} video(s) outside the manifest window from {source_name}.",
            extra=filter_stats,
        )
    if filter_stats["undated_or_unparseable_count"] > 0:
        log_event(
            run_id, source_id, _COLLECTOR_NAME,
            "date_missing", "warning",
            f"Kept {filter_stats['undated_or_unparseable_count']} video(s) with missing or unparseable publish dates from {source_name}.",
            extra=filter_stats,
        )
    if not docs:
        log_event(
            run_id, source_id, _COLLECTOR_NAME,
            "empty_result", "warning", f"All fetched videos were outside the manifest window for channel {source_name}",
            extra=filter_stats,
        )
        return []

    write_raw_documents(docs, output_path)

    log_event(run_id, source_id, _COLLECTOR_NAME,
              "success_note", "info",
              f"Collected {len(docs)} video transcripts from {source_name}",
              extra={"doc_count": len(docs), "channel_id": channel_id, **filter_stats})

    return docs


def load_enabled_channels(channels_path: Path = CHANNELS_YAML) -> tuple[list[dict], dict]:
    """
    Load the enabled channel registry from config/channels.yaml.

    Returns:
        (enabled_channels, youtube_defaults)
    """
    if not channels_path.exists():
        return [], {}

    import yaml
    cfg = yaml.safe_load(channels_path.read_text()) or {}
    yt_cfg = cfg.get("youtube", {})
    channels = yt_cfg.get("channels", []) or []
    enabled_channels = [ch for ch in channels if ch.get("enabled", True)]
    defaults = {
        "days_back": yt_cfg.get("days_back", 7),
        "max_per_duration": yt_cfg.get("max_per_duration", 3),
    }
    return enabled_channels, defaults


def load_enabled_channels_from_manifest(manifest: dict) -> tuple[list[dict], dict]:
    snapshot = get_youtube_registry_snapshot(manifest)
    return snapshot.get("enabled_channels", []), snapshot.get("defaults", {})


def collect_from_config(
    run_id: str,
    manifest: dict | None = None,
    days_back: int = None,
    max_per_duration: int = None,
    output_path: Path = None,
    layer1_dir: Path = None,
    start_at: str = None,
    end_at: str = None,
    default_search_query: str = None,
) -> list:
    """
    Collect recent transcripts from manifest-selected YouTube channels.
    """
    if output_path is None:
        output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    if not os.getenv("YOUTUBE_API_KEY"):
        log_event(
            run_id, "youtube_ai_channels", _COLLECTOR_NAME,
            "auth_error", "warning",
            "YOUTUBE_API_KEY not set; skipping YouTube orchestration in Layer 1.",
            retryable=True,
        )
        return []

    channels, defaults = load_enabled_channels_from_manifest(manifest or {})
    if not channels:
        log_event(
            run_id, "youtube_ai_channels", _COLLECTOR_NAME,
            "config_error", "warning",
            "No enabled YouTube channels found in run_manifest.json resolved_config.youtube_channels.",
        )
        return []

    effective_days_back = days_back or defaults.get("days_back", 7)
    effective_max_per = max_per_duration or defaults.get("max_per_duration", 3)

    all_docs = []
    for ch in channels:
        docs = collect_from_channel(
            run_id=run_id,
            channel_id=ch["channel_id"],
            channel_name=ch.get("name", ""),
            days_back=effective_days_back,
            max_per_duration=ch.get("max_per_duration", effective_max_per),
            output_path=output_path,
            layer1_dir=layer1_dir,
            search_query=ch.get("search_query") or default_search_query,
            start_at=start_at,
            end_at=end_at,
        )
        all_docs.extend(docs)

    return all_docs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect YouTube transcripts → RawExtractedDocument")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--url", help="Single YouTube video URL")
    mode.add_argument("--channel", help="YouTube channel ID (UCxxxxxxxx)")
    parser.add_argument("--name", default="", help="Channel display name (with --channel)")
    parser.add_argument("--days", type=int, default=2, help="Days back (default: 2)")
    parser.add_argument("--max", type=int, default=2, help="Max per duration bucket (default: 2)")
    args = parser.parse_args()

    run_id = "test_run_youtube"
    output_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    if output_path.exists():
        output_path.unlink()

    if args.url:
        print(f"Collecting transcript for: {args.url}\n")
        doc = collect_from_url(run_id=run_id, video_url=args.url)
        if doc:
            print(f"  Title: {doc['item']['title'][:70]}")
            print(f"  Content: {doc['content']['content_available']}")
            print(f"  Transcript: {doc['content']['transcript_char_count']} chars, "
                  f"{doc['content']['transcript_block_count']} blocks")
    else:
        print(f"Collecting from channel [{args.name or args.channel}] (last {args.days} days)...\n")
        docs = collect_from_channel(
            run_id=run_id,
            channel_id=args.channel,
            channel_name=args.name,
            days_back=args.days,
            max_per_duration=args.max,
        )
        print(f"\nCollected {len(docs)} videos:")
        for d in docs:
            print(f"  {d['item']['title'][:70]}")
            print(f"    Transcript: {d['content']['transcript_char_count']} chars, "
                  f"{d['content']['transcript_block_count']} blocks")

    result = read_raw_documents(output_path)
    print(f"\nVerified: {len(result)} records written to {output_path}")
