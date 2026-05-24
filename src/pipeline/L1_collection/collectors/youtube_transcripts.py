from __future__ import annotations

from datetime import datetime

import requests
from youtube_transcript_api import YouTubeTranscriptApi

from src.pipeline.L1_collection.common import build_record, clean_text, resolve_env

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
LANG_PREF = ["en", "te", "hi", "ta", "kn", "ml", "bn", "mr", "gu", "pa"]
TRANSCRIPT_API = YouTubeTranscriptApi()


def collect(cfg: dict) -> dict:
    timeout = int(cfg.get("request_timeout_seconds", 20))
    api_key = resolve_env(cfg["env_keys"])
    window = cfg["collection_window"]
    max_videos_per_channel = int(cfg.get("runtime", {}).get("max_videos_per_channel", 1))
    days_back = max(1, int(cfg["collection_window"]["lookback_hours"] / 24))

    records: list[dict] = []
    channel_summaries: dict[str, dict] = {}

    for channel in cfg.get("channels", []):
        if not channel.get("enabled", True):
            continue

        status = "ok"
        fetched_count = 0
        collected_count = 0
        filtered_out_count = 0
        notes: list[str] = []
        try:
            videos = _search_channel_videos(channel, api_key, days_back, max_videos_per_channel, timeout)
            fetched_count = len(videos)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            channel_summaries[channel["id"]] = {
                "status": status,
                "fetched_count": 0,
                "collected_count": 0,
                "filtered_out_count": 0,
                "notes": notes,
            }
            continue

        for video in videos:
            try:
                transcript_text = _fetch_transcript(video["video_id"])
            except Exception as exc:
                notes.append(f"Transcript unavailable for {video['video_id']}: {exc}")
                filtered_out_count += 1
                continue

            records.append(
                build_record(
                    source=channel["id"],
                    source_group=cfg["source_group"],
                    source_type="video_or_podcast",
                    title=video["title"],
                    url=f"https://www.youtube.com/watch?v={video['video_id']}",
                    published_at=video["published_at"],
                    content=transcript_text,
                    extra_fields={
                        "collector": "youtube_transcripts",
                        "channel_name": channel["name"],
                        "channel_id": channel["channel_id"],
                        "video_id": video["video_id"],
                        "trust_tier": 2,
                    },
                )
            )
            collected_count += 1

        channel_summaries[channel["id"]] = {
            "status": status,
            "fetched_count": fetched_count,
            "collected_count": collected_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        }

    return {
        "records": records,
        "summary": {
            "collector": "youtube_transcripts",
            "status": "partial" if any(item["status"] != "ok" for item in channel_summaries.values()) else "ok",
            "fetched_count": sum(item["fetched_count"] for item in channel_summaries.values()),
            "collected_count": len(records),
            "filtered_out_count": sum(item["filtered_out_count"] for item in channel_summaries.values()),
            "sources": channel_summaries,
        },
    }


def _search_channel_videos(channel: dict, api_key: str, days_back: int, max_results: int, timeout: int) -> list[dict]:
    from datetime import timedelta, timezone

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "part": "snippet",
        "channelId": channel["channel_id"],
        "maxResults": max_results,
        "order": "date",
        "type": "video",
        "publishedAfter": published_after,
        "key": api_key,
    }
    if channel.get("query"):
        params["q"] = channel["query"]

    response = requests.get(SEARCH_URL, params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()

    videos = []
    for item in data.get("items", []):
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        if not video_id:
            continue
        videos.append(
            {
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
            }
        )
    return videos


def _fetch_transcript(video_id: str) -> str:
    fetched = TRANSCRIPT_API.fetch(video_id, languages=LANG_PREF)
    text = clean_text(" ".join(snippet.text for snippet in fetched))
    if not text:
        raise RuntimeError("Empty transcript")
    return text
