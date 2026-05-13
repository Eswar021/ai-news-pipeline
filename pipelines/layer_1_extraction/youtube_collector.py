"""
YouTube Collector — Layer 1 Extraction

Discovers recent videos from configured AI channels via the YouTube Data API
and saves their transcripts as standard pipeline documents.

Two main modes:
  1. Single video URL  →  fetch transcript for one specific video
  2. Channel ID        →  discover recent videos + fetch all transcripts

Transcript blocks are grouped into ~60s chunks for timestamp-based citation
in script writing (e.g. "At 4:30, the speaker said...").

Proxy support: set YOUTUBE_PROXY in .env to route transcript requests through
a proxy if your IP gets rate-limited by YouTube.

Usage:
    python youtube_collector.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
    python youtube_collector.py --channel UCxxxxxx --days 2
    python youtube_collector.py --channel UCxxxxxx --days 2 --max 5
"""

import sys
import json
import os
import re
import time
import hashlib
import argparse
from datetime import datetime, timezone, timedelta
from config.time_utils import now_project
from config.time_utils import now_project_iso
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.parse import urlencode

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
from config.paths import RAW_YOUTUBE, ensure_output_dirs
from dotenv import load_dotenv

from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from youtube_transcript_api._errors import IpBlocked

load_dotenv()


_API_KEY    = os.getenv("YOUTUBE_API_KEY")
_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# Language preference order for transcript fetching
_LANG_PREF = ["en", "te", "hi", "ta", "kn", "ml", "bn", "mr", "gu", "pa"]

# Group auto-generated caption snippets into N-second blocks for timestamp context
_BLOCK_SECONDS = 60

# Optional proxy — set YOUTUBE_PROXY in .env if your IP gets rate-limited.
# Format: http://user:pass@host:port  or  socks5://host:port
_proxy_url = os.getenv("YOUTUBE_PROXY", "").strip()
if _proxy_url:
    from youtube_transcript_api.proxies import GenericProxyConfig
    _transcript_api = YouTubeTranscriptApi(
        proxy_config=GenericProxyConfig(http_url=_proxy_url, https_url=_proxy_url)
    )
    print(f"[youtube_collector] Using proxy: {_proxy_url}")
else:
    _transcript_api = YouTubeTranscriptApi()


# ── Video ID extraction ────────────────────────────────────────────────────────

def extract_video_id(url: str) -> str:
    """
    Parse a YouTube URL and return the video ID.
    Supports: youtube.com/watch?v=, youtu.be/, /embed/
    """
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    if parsed.hostname in ("www.youtube.com", "youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query)["v"][0]
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/embed/")[1]
    raise ValueError(f"Could not extract video ID from URL: {url}")


# ── Filename helpers ───────────────────────────────────────────────────────────

def _slugify(text: str, max_len: int) -> str:
    """ASCII-safe slug — strips non-ASCII so non-English titles don't produce garbage filenames."""
    text = text.lower().encode("ascii", errors="ignore").decode()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", "_", text).strip("_")
    return text[:max_len].rstrip("_")


def _video_filename(video_id: str, title: str = "", channel_name: str = "") -> str:
    """Build a human-readable filename: channel_titleslug_videoid.json"""
    channel_slug = _slugify(channel_name, max_len=20)
    title_slug   = _slugify(title, max_len=40)
    parts = [p for p in (channel_slug, title_slug, video_id) if p]
    return "_".join(parts) + ".json"


# ── Transcript fetching ────────────────────────────────────────────────────────

def fetch_transcript(video_url: str) -> tuple[str, list[dict]]:
    """
    Fetch transcript for a video. Returns (flat_text, blocks).

    flat_text: full transcript as one string — passed to LLM for summarization
    blocks:    [{start_time: "M:SS", text: "..."}] — ~60s chunks for timestamp citation

    Empty blocks list means no timing data was available (transcript had no timestamps).
    """
    video_id = extract_video_id(video_url)

    # First try with language preference; if not found, take whatever's available
    fetched = _transcript_api.fetch(video_id, languages=_LANG_PREF)

    snippets  = list(fetched)
    flat_text = " ".join(s.text for s in snippets)
    has_timing = any(s.start > 0 for s in snippets)

    if not has_timing:
        return flat_text, []

    # Group snippets into ~60s blocks
    blocks: list[dict] = []
    current_start = 0.0
    current_texts: list[str] = []

    for s in snippets:
        if s.start >= current_start + _BLOCK_SECONDS and current_texts:
            mins, secs = divmod(int(current_start), 60)
            blocks.append({"start_time": f"{mins}:{secs:02d}", "text": " ".join(current_texts)})
            current_start = s.start
            current_texts = [s.text]
        else:
            current_texts.append(s.text)

    if current_texts:
        mins, secs = divmod(int(current_start), 60)
        blocks.append({"start_time": f"{mins}:{secs:02d}", "text": " ".join(current_texts)})

    return flat_text, blocks


# ── Document builder ───────────────────────────────────────────────────────────

def build_document(video_id: str, video_url: str, title: str, channel_name: str,
                   channel_id: str, published_at: str, flat_text: str,
                   transcript_blocks: list[dict]) -> dict:
    """
    Build a standard pipeline document for a YouTube video with transcript.
    Follows the same schema as all other Layer 1 collectors.
    """
    content_hash = hashlib.sha256(f"youtube:{video_id}".encode()).hexdigest()[:16]

    doc = {
        "document_id": f"yt_{video_id}",
        "source_id": "youtube_ai_channels",
        "module": "youtube_collector",
        "source_type": "video_or_podcast",
        "trust_tier": 2,
        "title": title,
        "url": video_url,
        "video_id": video_id,
        "channel_name": channel_name,
        "channel_id": channel_id,
        "published_at": published_at,
        "author": channel_name,
        "raw_text": flat_text,              # full flat transcript — used by LLM agents
        "transcript_blocks": transcript_blocks,  # timestamped blocks for citation
        "content_hash": content_hash,
        "collected_at": now_project_iso(),
    }

    return doc


# ── Single video ───────────────────────────────────────────────────────────────

def collect_single_video(video_url: str, title: str = "", channel_name: str = "",
                         channel_id: str = "", published_at: str = "") -> dict:
    """
    Fetch transcript for a single known video URL and return the document.
    Use this when you already have a specific video URL.
    """
    video_id = extract_video_id(video_url)
    flat_text, blocks = fetch_transcript(video_url)

    return build_document(
        video_id=video_id,
        video_url=video_url,
        title=title,
        channel_name=channel_name,
        channel_id=channel_id,
        published_at=published_at,
        flat_text=flat_text,
        transcript_blocks=blocks,
    )


# ── Channel discovery ──────────────────────────────────────────────────────────

def search_channel_videos(channel_id: str, max_results: int = 5,
                           days_back: int = 2, duration: str = "medium",
                           search_query: str = None) -> list[dict]:
    """
    Search a YouTube channel for recent videos using YouTube Data API.

    Args:
        channel_id:   YouTube channel ID (UCxxxxxxxx)
        max_results:  Max videos to return
        days_back:    Only videos published in last N days
        duration:     "short" (<4min), "medium" (4–20min), "long" (>20min)
        search_query: Optional keyword filter within the channel

    Returns:
        List of video metadata dicts (not full documents yet — no transcript).
    """
    published_after = (
        now_project() - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "part": "snippet",
        "channelId": channel_id,
        "maxResults": max_results,
        "order": "date",
        "type": "video",
        "videoDuration": duration,
        "publishedAfter": published_after,
        "key": _API_KEY,
    }
    if search_query:
        params["q"] = search_query

    url = f"{_SEARCH_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "AI-Content-Creation/1.0"})
    response = urlopen(req, timeout=15)
    data = json.loads(response.read().decode("utf-8"))

    videos = []
    for item in data.get("items", []):
        vid_id = item["id"].get("videoId")
        if vid_id:
            videos.append({
                "video_id":     vid_id,
                "title":        item["snippet"].get("title", ""),
                "published_at": item["snippet"].get("publishedAt", ""),
                "channel_name": item["snippet"].get("channelTitle", ""),
                "channel_id":   channel_id,
                "duration":     duration,
            })

    return videos


def collect_channel(channel_id: str, channel_name: str = "", days_back: int = 2,
                    max_per_duration: int = 3, search_query: str = None) -> list[dict]:
    """
    Discover recent videos from a channel and collect transcripts for each.

    Fetches medium (4–20 min) and long (20+ min) videos. Short videos skipped
    by default — too little content for AI news analysis.

    Args:
        channel_id:        YouTube channel ID
        channel_name:      Human-readable name (for filenames and documents)
        days_back:         Look back this many days
        max_per_duration:  Max videos to fetch per duration bucket
        search_query:      Optional keyword filter (e.g. "AI agent LLM")

    Returns:
        List of full pipeline documents with transcripts.
    """
    all_videos = []
    for duration in ("medium", "long"):
        found = search_channel_videos(
            channel_id=channel_id,
            max_results=max_per_duration,
            days_back=days_back,
            duration=duration,
            search_query=search_query,
        )
        all_videos.extend(found)

    if not all_videos:
        print(f"  [{channel_name or channel_id}] No videos found in last {days_back} day(s)")
        return []

    documents = []
    for v in all_videos:
        video_url = f"https://www.youtube.com/watch?v={v['video_id']}"
        print(f"  [{v['duration']:6}] {v['video_id']}  {v['title'][:60]}")
        doc = collect_single_video(
            video_url=video_url,
            title=v["title"],
            channel_name=channel_name or v["channel_name"],
            channel_id=channel_id,
            published_at=v["published_at"],
        )
        documents.append(doc)
        time.sleep(1.5)   # polite delay between transcript requests

    return documents


# ── Save ───────────────────────────────────────────────────────────────────────

def save_document(doc: dict) -> str:
    """Save a single video document to output/layer_1_raw/youtube/"""
    ensure_output_dirs()

    filename = _video_filename(
        video_id=doc["video_id"],
        title=doc.get("title", ""),
        channel_name=doc.get("channel_name", ""),
    )
    filepath = RAW_YOUTUBE / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    return str(filepath)


def save_documents(docs: list[dict]) -> list[str]:
    """Save a list of video documents."""
    return [save_document(doc) for doc in docs]


# ── Test run ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube transcript collector")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--url",          help="Single YouTube video URL")
    mode.add_argument("--channel",      help="YouTube channel ID (UCxxxxxxxx)")
    mode.add_argument("--all-channels", action="store_true",
                      help="Run all enabled channels from config/registries/channels.yaml")

    parser.add_argument("--name",  default="", help="Channel display name (used with --channel)")
    parser.add_argument("--days",  type=int, default=2,  help="Days back to search (default: 2)")
    parser.add_argument("--max",   type=int, default=3,  help="Max videos per duration bucket (default: 3)")
    parser.add_argument("--query", default=None,         help="Optional keyword filter within channel")

    args = parser.parse_args()

    ensure_output_dirs()

    if args.url:
        # ── Mode 1: single video ──
        print(f"Fetching transcript for: {args.url}")
        doc = collect_single_video(video_url=args.url)
        filepath = save_document(doc)
        print(f"\nTitle:      {doc['title'] or '(not provided)'}")
        print(f"Video ID:   {doc['video_id']}")
        print(f"Transcript: {len(doc.get('raw_text', ''))} chars")
        print(f"Blocks:     {len(doc.get('transcript_blocks', []))} × ~{_BLOCK_SECONDS}s chunks")
        print(f"Saved to:   {filepath}")

    elif args.channel:
        # ── Mode 2: single channel ──
        print(f"Fetching videos from channel [{args.name or args.channel}] (last {args.days} days)...")
        docs = collect_channel(
            channel_id=args.channel,
            channel_name=args.name,
            days_back=args.days,
            max_per_duration=args.max,
            search_query=args.query,
        )
        if docs:
            paths = save_documents(docs)
            print(f"\nCollected {len(docs)} video(s):")
            for doc, path in zip(docs, paths):
                print(f"  [{len(doc['raw_text'])} chars] {doc['title'][:60]}")
                print(f"    → {path}")
        else:
            print("No transcripts collected.")

    else:
        # ── Mode 3: all channels from config/registries/channels.yaml ──
        import yaml
        from config.paths import CHANNELS_YAML

        cfg       = yaml.safe_load(CHANNELS_YAML.read_text())
        yt_cfg    = cfg["youtube"]
        channels  = yt_cfg["channels"]
        days_back = args.days or 2
        max_per   = args.max  or 3

        print(f"Running all enabled channels (last {days_back} days, max {max_per}/bucket)...\n")
        all_docs = []
        for ch in channels:
            if not ch.get("enabled", True):
                continue
            print(f"\n[{ch['name']}]")
            docs = collect_channel(
                channel_id=ch["channel_id"],
                channel_name=ch["name"],
                days_back=days_back,
                max_per_duration=max_per,
                search_query=ch.get("search_query"),
            )
            all_docs.extend(docs)

        if all_docs:
            paths = save_documents(all_docs)
            print(f"\n\nTotal: {len(all_docs)} transcript(s) saved.")
        else:
            print("\nNo transcripts collected across all channels.")
