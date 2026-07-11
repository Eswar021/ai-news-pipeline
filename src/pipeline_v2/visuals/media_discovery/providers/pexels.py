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
        "query": query,
        "orientation": "landscape",
        "per_page": str(limit),
    }
    payload = get_json(
        f"{endpoint}?{urlencode(params)}",
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        headers={"Authorization": api_key},
    )
    return _video_candidates(payload) if wants_video else _photo_candidates(payload)


def _photo_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in payload.get("photos", []) if isinstance(payload.get("photos"), list) else []:
        if not isinstance(item, dict):
            continue
        sources = item.get("src") if isinstance(item.get("src"), dict) else {}
        download_url = str(sources.get("large2x") or sources.get("large") or sources.get("original") or "")
        if not download_url:
            continue
        candidates.append(
            {
                "candidate_id": f"pexels_photo_{item.get('id', len(candidates) + 1)}",
                "provider": "pexels",
                "media_type": "image",
                "title": str(item.get("alt", "")),
                "description": str(item.get("alt", "")),
                "tags": [],
                "creator": str(item.get("photographer", "")),
                "attribution": f"Photo by {item.get('photographer', 'Pexels contributor')} on Pexels",
                "license": "Pexels License",
                "license_url": "https://www.pexels.com/license/",
                "source_url": str(item.get("url", "")),
                "download_url": download_url,
                "preview_url": str(sources.get("medium") or download_url),
                "mime_type": "image/jpeg",
                "width": _safe_int(item.get("width")),
                "height": _safe_int(item.get("height")),
                "duration_seconds": 0.0,
            }
        )
    return candidates


def _video_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in payload.get("videos", []) if isinstance(payload.get("videos"), list) else []:
        if not isinstance(item, dict):
            continue
        files = [entry for entry in item.get("video_files", []) if isinstance(entry, dict)]
        files = [entry for entry in files if str(entry.get("link", "")).startswith(("http://", "https://"))]
        if not files:
            continue
        files.sort(key=lambda entry: abs(_safe_int(entry.get("width")) - 1920))
        selected = files[0]
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        candidates.append(
            {
                "candidate_id": f"pexels_video_{item.get('id', len(candidates) + 1)}",
                "provider": "pexels",
                "media_type": "video",
                "title": "",
                "description": "",
                "tags": [],
                "creator": str(user.get("name", "")),
                "attribution": f"Video by {user.get('name', 'Pexels contributor')} on Pexels",
                "license": "Pexels License",
                "license_url": "https://www.pexels.com/license/",
                "source_url": str(item.get("url", "")),
                "download_url": str(selected.get("link", "")),
                "preview_url": _video_preview(item),
                "mime_type": str(selected.get("file_type", "video/mp4")),
                "width": _safe_int(selected.get("width")),
                "height": _safe_int(selected.get("height")),
                "duration_seconds": _safe_float(item.get("duration")),
            }
        )
    return candidates


def _video_preview(item: dict[str, Any]) -> str:
    pictures = item.get("video_pictures") if isinstance(item.get("video_pictures"), list) else []
    for picture in pictures:
        if isinstance(picture, dict) and picture.get("picture"):
            return str(picture["picture"])
    return ""


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
