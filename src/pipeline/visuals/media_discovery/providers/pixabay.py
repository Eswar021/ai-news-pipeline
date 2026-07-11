from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..config import BROLL_VIDEO_RENDER_KIND
from .http import get_json


def search(
    *,
    query: str,
    render_kind: str,
    api_key: str,
    photo_endpoint: str,
    video_endpoint: str,
    limit: int,
    timeout_seconds: int,
    user_agent: str,
) -> list[dict[str, Any]]:
    wants_video = render_kind == BROLL_VIDEO_RENDER_KIND
    endpoint = video_endpoint if wants_video else photo_endpoint
    params = {
        "key": api_key,
        "q": query,
        "safesearch": "true",
        "per_page": str(max(3, limit)),
    }
    if wants_video:
        params["video_type"] = "film"
    else:
        params.update({"orientation": "horizontal", "image_type": "photo", "min_width": "1280"})
    payload = get_json(
        f"{endpoint}?{urlencode(params)}",
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
    )
    return _video_candidates(payload) if wants_video else _photo_candidates(payload)


def _photo_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in payload.get("hits", []) if isinstance(payload.get("hits"), list) else []:
        if not isinstance(item, dict):
            continue
        download_url = str(item.get("largeImageURL") or item.get("webformatURL") or "")
        if not download_url:
            continue
        candidates.append(
            {
                "candidate_id": f"pixabay_photo_{item.get('id', len(candidates) + 1)}",
                "provider": "pixabay",
                "media_type": "image",
                "title": str(item.get("tags", "")),
                "description": str(item.get("tags", "")),
                "tags": [tag.strip() for tag in str(item.get("tags", "")).split(",") if tag.strip()],
                "creator": str(item.get("user", "")),
                "attribution": f"Image by {item.get('user', 'Pixabay contributor')} on Pixabay",
                "license": "Pixabay Content License",
                "license_url": "https://pixabay.com/service/license-summary/",
                "source_url": str(item.get("pageURL", "")),
                "download_url": download_url,
                "preview_url": str(item.get("previewURL") or item.get("webformatURL") or download_url),
                "mime_type": "image/jpeg",
                "width": _safe_int(item.get("imageWidth") or item.get("webformatWidth")),
                "height": _safe_int(item.get("imageHeight") or item.get("webformatHeight")),
                "duration_seconds": 0.0,
            }
        )
    return candidates


def _video_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in payload.get("hits", []) if isinstance(payload.get("hits"), list) else []:
        if not isinstance(item, dict):
            continue
        videos = item.get("videos") if isinstance(item.get("videos"), dict) else {}
        options = [entry for entry in videos.values() if isinstance(entry, dict) and entry.get("url")]
        if not options:
            continue
        options.sort(key=lambda entry: abs(_safe_int(entry.get("width")) - 1920))
        selected = options[0]
        candidates.append(
            {
                "candidate_id": f"pixabay_video_{item.get('id', len(candidates) + 1)}",
                "provider": "pixabay",
                "media_type": "video",
                "title": str(item.get("tags", "")),
                "description": str(item.get("tags", "")),
                "tags": [tag.strip() for tag in str(item.get("tags", "")).split(",") if tag.strip()],
                "creator": str(item.get("user", "")),
                "attribution": f"Video by {item.get('user', 'Pixabay contributor')} on Pixabay",
                "license": "Pixabay Content License",
                "license_url": "https://pixabay.com/service/license-summary/",
                "source_url": str(item.get("pageURL", "")),
                "download_url": str(selected.get("url", "")),
                "preview_url": str(item.get("picture_id", "")),
                "mime_type": "video/mp4",
                "width": _safe_int(selected.get("width")),
                "height": _safe_int(selected.get("height")),
                "duration_seconds": _safe_float(item.get("duration")),
            }
        )
    return candidates


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
