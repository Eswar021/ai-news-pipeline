"""
context_ext_layer/phaseA_BMD/yt_transcript.py

Discovers recent videos from configured channels via the YouTube Data API
and saves their transcripts. All timestamps in IST (Asia/Kolkata, UTC+5:30).

Functions:
  save_transcript(url)              → save transcript for one known URL
  save_channel(channel, days=2)     → search + save for one channel
  save_all_channels(days=2)         → search + save for all enabled channels
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

import time

import requests
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from youtube_transcript_api._errors import IpBlocked

sys.path.append(str(__import__("pathlib").Path(__file__).parent.parent.parent))
from config.paths import YOUTUBE_OUTPUT_DIR

load_dotenv()
_IST        = timezone(timedelta(hours=5, minutes=30))
_API_KEY    = os.getenv("YOUTUBE_API_KEY")
_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# Optional proxy — set YOUTUBE_PROXY in .env to route transcript requests through a proxy.
# Format: http://user:pass@host:port  or  socks5://host:port
# Useful when your home IP is temporarily blocked by YouTube rate-limiting.
_proxy_url = os.getenv("YOUTUBE_PROXY", "").strip()
if _proxy_url:
    from youtube_transcript_api.proxies import GenericProxyConfig
    _api = YouTubeTranscriptApi(proxy_config=GenericProxyConfig(http_url=_proxy_url, https_url=_proxy_url))
    print(f"[yt_transcript] Using proxy: {_proxy_url}")
else:
    _api = YouTubeTranscriptApi()


# ── filename helpers ──────────────────────────────────────────────────────────

def _slugify(text: str, max_len: int) -> str:
    """ASCII-safe filename slug. Strips non-ASCII so Telugu/Hindi titles don't produce garbage."""
    text = text.lower().encode("ascii", errors="ignore").decode()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", "_", text).strip("_")
    return text[:max_len].rstrip("_")


def _video_filename(video_id: str, title: str = "", channel_name: str = "") -> str:
    """
    Builds a human-readable filename:  channel_titleslug_videoid.json
    Falls back to video_id.json when both slugs are empty (e.g. non-ASCII title+channel).
    """
    channel_slug = _slugify(channel_name, max_len=20)
    title_slug   = _slugify(title,        max_len=40)
    parts = [p for p in (channel_slug, title_slug, video_id) if p]
    return "_".join(parts) + ".json"


# ── transcript helpers ────────────────────────────────────────────────────────

def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    if parsed.hostname in ("www.youtube.com", "youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query)["v"][0]
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/embed/")[1]
    raise ValueError(f"Could not extract video ID from URL: {url}")


_LANG_PREF = ["en", "te", "hi", "ta", "kn", "ml", "bn", "mr", "gu", "pa"]

_BLOCK_SECONDS = 60  # group auto-generated snippets into ~60s blocks for timestamp context

def extract_transcript(video_url: str) -> tuple[str, list[dict]]:
    """
    Returns (flat_transcript_string, transcript_blocks).
    transcript_blocks: [{"start_time": "M:SS", "text": "..."}] — snippets grouped into
    ~60s blocks. Empty list if the transcript has no timing data.
    Flat string is used by the LLM; blocks are stored for timestamp-based citation.
    Speaker labels are not available in auto-generated captions.
    """
    video_id = extract_video_id(video_url)
    try:
        fetched = _api.fetch(video_id, languages=_LANG_PREF)
    except NoTranscriptFound:
        transcript_list = _api.list(video_id)
        fetched = next(iter(transcript_list)).fetch()

    snippets   = list(fetched)
    flat_text  = " ".join(s.text for s in snippets)
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


def save_transcript(video_url: str, title: str = "", channel_name: str = "",
                    published_at: str = "") -> str:
    """Download and save transcript for a single known video URL."""
    video_id                   = extract_video_id(video_url)
    transcript, transcript_blocks = extract_transcript(video_url)

    YOUTUBE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = YOUTUBE_OUTPUT_DIR / _video_filename(video_id, title, channel_name)
    data: dict = {
        "video_url":    video_url,
        "video_id":     video_id,
        "title":        title,
        "channel_name": channel_name,
        "published_at": published_at,
        "extracted_at": datetime.now(_IST).isoformat(),
        "transcript":   transcript,
    }
    if transcript_blocks:
        data["transcript_blocks"] = transcript_blocks
    output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return str(output_file)


# ── channel discovery ─────────────────────────────────────────────────────────

def _search_channel(channel_id: str, max_results: int, duration: str,
                    published_after: str = None, search_query: str = None) -> list[dict]:
    """
    duration: 'medium' (4–20 min) or 'long' (20+ min).
    search_query: optional keyword filter (e.g. 'Nifty OR earnings OR stock market').
                  Set on news channels that post non-market content. Leave None for
                  dedicated market channels where all content is relevant.
    """
    params = {
        "part":          "snippet",
        "channelId":     channel_id,
        "maxResults":    max_results,
        "order":         "date",
        "type":          "video",
        "videoDuration": duration,
        "key":           _API_KEY,
    }
    if published_after:
        params["publishedAfter"] = published_after
    if search_query:
        params["q"] = search_query

    resp = requests.get(_SEARCH_URL, params=params, timeout=15)
    resp.raise_for_status()
    videos = []
    for item in resp.json().get("items", []):
        vid_id = item["id"].get("videoId")
        if vid_id:
            videos.append({
                "video_id":        vid_id,
                "title":           item["snippet"].get("title", ""),
                "published_at":    item["snippet"].get("publishedAt", ""),
                "duration_bucket": duration,
            })
    return videos


def save_channel(channel: dict, days: int = 2) -> list[str]:
    """Search a channel for recent videos and save transcripts."""
    name         = channel["name"]
    cid          = channel["channel_id"]
    max_short    = channel.get("max_short", 0)
    max_medium   = channel.get("max_medium", 3)
    max_long     = channel.get("max_long", 3)
    search_query = channel.get("search_query")   # None = fetch all (dedicated market channels)

    published_after = (
        datetime.now(_IST) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    videos = []
    if max_short  > 0:
        videos += _search_channel(cid, max_short,  "short",  published_after, search_query)
    if max_medium > 0:
        videos += _search_channel(cid, max_medium, "medium", published_after, search_query)
    if max_long   > 0:
        videos += _search_channel(cid, max_long,   "long",   published_after, search_query)

    if not videos:
        print(f"  [{name}] no videos found in last {days} day(s)")
        return []

    saved_files = []
    for v in videos:
        url = f"https://www.youtube.com/watch?v={v['video_id']}"
        try:
            path = save_transcript(url, title=v["title"], channel_name=name,
                                   published_at=v["published_at"])
            saved_files.append(path)
            print(f"  [new/{v['duration_bucket']:6}] {v['video_id']}  {v['title'][:60]}")
            time.sleep(1.5)
        except IpBlocked:
            print(f"  [ip-blocked]  YouTube is rate-limiting transcript requests — wait a few hours and retry")
            break
        except Exception:
            print(f"  [skip/no-cc]    {v['video_id']}  {v['title'][:50]}")
            time.sleep(1.5)

    if not saved_files:
        print(f"  [{name}] videos found but no transcripts available")

    return saved_files


def save_all_channels(channels: list, days: int = 2) -> list[str]:
    """Search all enabled channels and save transcripts."""
    files = []
    for ch in channels:
        if not ch.get("enabled", True):
            continue
        print(f"\n[{ch['name']}]")
        files.extend(save_channel(ch, days=days))
    return files


if __name__ == "__main__":
    import yaml
    from pathlib import Path
    cfg      = yaml.safe_load((Path(__file__).parent.parent.parent / "config" / "phase_a.yaml").read_text())
    yt_cfg   = cfg["youtube"]
    channels = yt_cfg["channels"]
    days     = yt_cfg.get("days_back", 2)

    print(f"Fetching transcripts for enabled channels (last {days} days)...\n")
    paths = save_all_channels(channels, days=days)
    print(f"\nSaved {len(paths)} transcript(s).")
