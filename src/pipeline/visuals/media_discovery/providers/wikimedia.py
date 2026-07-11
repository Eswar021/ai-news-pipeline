from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlencode

from ..config import BROLL_VIDEO_RENDER_KIND
from .http import get_json


TAG_RE = re.compile(r"<[^>]+>")


def search(
    *,
    query: str,
    render_kind: str,
    endpoint: str,
    limit: int,
    timeout_seconds: int,
    user_agent: str,
) -> list[dict[str, Any]]:
    wants_video = render_kind == BROLL_VIDEO_RENDER_KIND
    search_query = f"{query} filetype:{'video' if wants_video else 'bitmap'}"
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": search_query,
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo|videoinfo",
        "iiprop": "url|size|mime|mediatype|extmetadata",
        "viprop": "url|size|mime|derivatives",
        "iiurlwidth": "1920",
        "format": "json",
        "formatversion": "2",
    }
    payload = get_json(
        f"{endpoint}?{urlencode(params)}",
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
    )
    pages = payload.get("query", {}).get("pages", [])
    candidates: list[dict[str, Any]] = []
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        image_infos = page.get("imageinfo")
        image_info = image_infos[0] if isinstance(image_infos, list) and image_infos and isinstance(image_infos[0], dict) else {}
        video_infos = page.get("videoinfo")
        video_info = video_infos[0] if isinstance(video_infos, list) and video_infos and isinstance(video_infos[0], dict) else {}
        info = video_info if wants_video and video_info else image_info
        mime = str(info.get("mime", "")).lower()
        media_type = "video" if mime.startswith("video/") else "image" if mime.startswith("image/") else ""
        if media_type != ("video" if wants_video else "image"):
            continue
        download_url = _download_url(info, media_type)
        if not download_url:
            continue
        metadata = image_info.get("extmetadata") if isinstance(image_info.get("extmetadata"), dict) else {}
        title = str(page.get("title", "")).removeprefix("File:")
        candidates.append(
            {
                "candidate_id": f"wikimedia_{page.get('pageid', len(candidates) + 1)}",
                "provider": "wikimedia",
                "media_type": media_type,
                "title": _metadata_text(metadata, "ObjectName") or title,
                "description": _metadata_text(metadata, "ImageDescription"),
                "tags": [],
                "creator": _metadata_text(metadata, "Artist"),
                "attribution": _metadata_text(metadata, "Credit"),
                "license": _metadata_text(metadata, "LicenseShortName") or _metadata_text(metadata, "UsageTerms"),
                "license_url": _metadata_text(metadata, "LicenseUrl"),
                "source_url": str(info.get("descriptionurl") or info.get("descriptionshorturl") or ""),
                "download_url": download_url,
                "preview_url": str(info.get("thumburl") or download_url),
                "mime_type": mime,
                "width": _safe_int(info.get("thumbwidth") or info.get("width")),
                "height": _safe_int(info.get("thumbheight") or info.get("height")),
                "duration_seconds": _safe_float(info.get("duration")),
            }
        )
    return candidates


def _download_url(info: dict[str, Any], media_type: str) -> str:
    if media_type == "image":
        return str(info.get("thumburl") or info.get("url") or "")
    derivatives = info.get("derivatives") if isinstance(info.get("derivatives"), list) else []
    usable = [
        item
        for item in derivatives
        if isinstance(item, dict)
        and str(item.get("src", "")).startswith(("http://", "https://"))
        and str(item.get("type", "")).startswith("video/")
    ]
    if usable:
        practical = [item for item in usable if 640 <= _safe_int(item.get("width")) <= 1280]
        choices = practical or usable
        choices.sort(key=lambda item: abs(_safe_int(item.get("width")) - 1280))
        return str(choices[0].get("src", ""))
    return str(info.get("url") or "")


def _metadata_text(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key, {})
    raw = value.get("value", "") if isinstance(value, dict) else value
    return html.unescape(TAG_RE.sub(" ", str(raw or ""))).strip()


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
