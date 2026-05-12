"""
Owner-channel YouTube API client for publish-state and analytics workflows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from config.time_utils import now_project

from pipelines.layer_10_memory_learning.youtube_publishing_auth import authorized_session


YOUTUBE_DATA_API_ROOT = "https://www.googleapis.com/youtube/v3"
YOUTUBE_ANALYTICS_API_ROOT = "https://youtubeanalytics.googleapis.com/v2"


def _api_get(session, url: str, params: dict) -> dict:
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def youtube_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def get_authenticated_channel(interactive: bool = False) -> dict:
    session = authorized_session(interactive=interactive)
    payload = _api_get(
        session,
        f"{YOUTUBE_DATA_API_ROOT}/channels",
        {
            "part": "id,snippet,statistics,contentDetails",
            "mine": "true",
        },
    )
    items = payload.get("items", [])
    if not items:
        raise RuntimeError("Authenticated YouTube account has no accessible channel.")

    item = items[0]
    snippet = item.get("snippet", {})
    content_details = item.get("contentDetails", {})
    uploads_playlist_id = (
        content_details.get("relatedPlaylists", {}).get("uploads")
    )
    return {
        "channel_id": item.get("id", ""),
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "custom_url": snippet.get("customUrl", ""),
        "published_at": snippet.get("publishedAt", ""),
        "thumbnails": snippet.get("thumbnails", {}),
        "statistics": item.get("statistics", {}),
        "uploads_playlist_id": uploads_playlist_id,
    }


def get_video_details(video_ids: list[str], interactive: bool = False) -> dict[str, dict]:
    if not video_ids:
        return {}

    session = authorized_session(interactive=interactive)
    details: dict[str, dict] = {}

    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start:start + 50]
        payload = _api_get(
            session,
            f"{YOUTUBE_DATA_API_ROOT}/videos",
            {
                "part": "snippet,statistics,contentDetails,status",
                "id": ",".join(chunk),
            },
        )
        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            thumbnails = snippet.get("thumbnails", {})
            best_thumb = (
                thumbnails.get("maxres")
                or thumbnails.get("standard")
                or thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )
            details[item.get("id", "")] = {
                "youtube_video_id": item.get("id", ""),
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", ""),
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "thumbnail_url": best_thumb.get("url", ""),
                "statistics": item.get("statistics", {}),
                "status": item.get("status", {}),
                "content_details": item.get("contentDetails", {}),
                "url": youtube_video_url(item.get("id", "")),
            }
    return details


def get_video_detail(video_id: str, interactive: bool = False) -> dict:
    details = get_video_details([video_id], interactive=interactive)
    if video_id not in details:
        raise RuntimeError(f"Could not load YouTube video details for {video_id}.")
    return details[video_id]


def list_uploaded_videos(
    interactive: bool = False,
    max_videos: int | None = None,
) -> tuple[dict, list[dict]]:
    channel = get_authenticated_channel(interactive=interactive)
    playlist_id = channel.get("uploads_playlist_id")
    if not playlist_id:
        raise RuntimeError("Authenticated channel is missing an uploads playlist ID.")

    session = authorized_session(interactive=interactive)
    playlist_items: list[dict] = []
    next_page_token = None

    while True:
        payload = _api_get(
            session,
            f"{YOUTUBE_DATA_API_ROOT}/playlistItems",
            {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": 50,
                **({"pageToken": next_page_token} if next_page_token else {}),
            },
        )
        items = payload.get("items", [])
        playlist_items.extend(items)
        next_page_token = payload.get("nextPageToken")
        if max_videos and len(playlist_items) >= max_videos:
            playlist_items = playlist_items[:max_videos]
            break
        if not next_page_token:
            break

    video_ids = [
        item.get("contentDetails", {}).get("videoId", "")
        for item in playlist_items
        if item.get("contentDetails", {}).get("videoId")
    ]
    detail_map = get_video_details(video_ids, interactive=interactive)

    videos = []
    for item in playlist_items:
        video_id = item.get("contentDetails", {}).get("videoId", "")
        if not video_id:
            continue
        detail = detail_map.get(video_id, {})
        snippet = item.get("snippet", {})
        videos.append(
            {
                "youtube_video_id": video_id,
                "title": detail.get("title") or snippet.get("title", ""),
                "published_at": (
                    detail.get("published_at")
                    or snippet.get("publishedAt", "")
                ),
                "description": detail.get("description", ""),
                "channel_id": detail.get("channel_id") or channel.get("channel_id", ""),
                "channel_title": detail.get("channel_title") or channel.get("title", ""),
                "thumbnail_url": detail.get("thumbnail_url", ""),
                "statistics": detail.get("statistics", {}),
                "status": detail.get("status", {}),
                "content_details": detail.get("content_details", {}),
                "url": detail.get("url") or youtube_video_url(video_id),
            }
        )

    return channel, videos


def get_video_performance(
    youtube_video_id: str,
    published_at: str,
    interactive: bool = False,
    window_hours: int = 48,
) -> dict:
    detail = get_video_detail(youtube_video_id, interactive=interactive)
    published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    now = now_project()
    window_end = min(now, published_dt + timedelta(hours=window_hours))
    window_complete = now >= published_dt + timedelta(hours=window_hours)

    start_date = published_dt.date().isoformat()
    end_date = window_end.date().isoformat()

    session = authorized_session(interactive=interactive)
    analytics = _api_get(
        session,
        f"{YOUTUBE_ANALYTICS_API_ROOT}/reports",
        {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": "views,likes,comments,subscribersGained,averageViewDuration,impressionsCtr",
            "filters": f"video=={youtube_video_id}",
        },
    )

    headers = analytics.get("columnHeaders", [])
    rows = analytics.get("rows", [])
    metric_map = {
        header.get("name"): rows[0][idx]
        for idx, header in enumerate(headers)
    } if rows else {}

    statistics = detail.get("statistics", {})
    like_count = _int_or_none(metric_map.get("likes")) or _int_or_none(statistics.get("likeCount"))
    comment_count = _int_or_none(metric_map.get("comments")) or _int_or_none(statistics.get("commentCount"))

    return {
        "youtube_video_id": youtube_video_id,
        "published_at": published_at,
        "collected_at": now.isoformat(),
        "window_hours": window_hours,
        "window_complete": window_complete,
        "analytics_status": "available" if rows else "pending_or_unavailable",
        "performance": {
            "views_48h": _int_or_none(metric_map.get("views")),
            "ctr": _float_percent_or_none(metric_map.get("impressionsCtr")),
            "average_view_duration_seconds": _float_or_none(metric_map.get("averageViewDuration")),
            "like_count": like_count,
            "comment_count": comment_count,
            "subscribers_gained": _int_or_none(metric_map.get("subscribersGained")),
        },
        "video_detail": detail,
    }


def _int_or_none(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_percent_or_none(value):
    f = _float_or_none(value)
    if f is None:
        return None
    return f / 100.0 if f > 1 else f
