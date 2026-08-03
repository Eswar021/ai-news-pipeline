"""Best-effort source-image collection for the visuals stage.

The visuals engine can display real images but was only ever given generic stock
or logos. This collects each selected story's real hero image (the article's
og:image / twitter:image) so the render can show the actual story. It is strictly
best-effort: any fetch or parse failure just omits that image and never raises, so
it can never fail a run.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any, Callable
from urllib.parse import urljoin

try:  # requests is a first-party dependency (news collectors use it)
    import requests
except Exception:  # pragma: no cover - requests is always present in the app env
    requests = None  # type: ignore[assignment]

SCHEMA_VERSION = "asset_manifest_v1"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# og:image / twitter:image, tolerating either attribute order and quote style.
_META_PATTERNS = [
    re.compile(r'<meta[^>]+(?:property|name)=["\']og:image(?::url|:secure_url)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image(?::url|:secure_url)?["\']', re.I),
    re.compile(r'<meta[^>]+(?:property|name)=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']twitter:image(?::src)?["\']', re.I),
]


def extract_image_url(html: str, base_url: str) -> str | None:
    """Return an absolute og:image/twitter:image URL from page HTML, or None.

    Pure and side-effect free so it is unit-testable without the network."""
    if not html:
        return None
    head = html[:200_000]  # these tags live in <head>; cap the scan
    for pattern in _META_PATTERNS:
        match = pattern.search(head)
        if match:
            # og:image content is HTML-escaped in the page source (&amp; → &).
            src = _html.unescape(match.group(1).strip())
            if src:
                return urljoin(base_url, src)
    return None


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _fetch_html(url: str, timeout_seconds: float, http_get: Callable[..., Any]) -> str | None:
    try:
        response = http_get(url, headers=DEFAULT_HEADERS, timeout=timeout_seconds, allow_redirects=True)
    except Exception:
        return None
    if getattr(response, "status_code", 0) != 200:
        return None
    content_type = ""
    headers = getattr(response, "headers", None)
    if headers:
        content_type = str(headers.get("Content-Type") or headers.get("content-type") or "").lower()
    if content_type and "html" not in content_type:
        return None
    return getattr(response, "text", "") or None


def build_asset_manifest(
    stories: list[dict[str, Any]],
    *,
    timeout_seconds: float = 8.0,
    max_images_per_story: int = 4,
    http_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Build an asset manifest of real source images for the selected stories.

    Best-effort: stories/records without a resolvable image are simply omitted.
    ``http_get`` is injectable for tests; defaults to ``requests.get``."""
    if http_get is None:
        if requests is None:
            return {"schema_version": SCHEMA_VERSION, "stories": []}
        http_get = requests.get

    manifest_stories: list[dict[str, Any]] = []
    for story in stories or []:
        images: list[dict[str, str]] = []
        seen: set[str] = set()
        for record in story.get("records") or []:
            if len(images) >= max_images_per_story:
                break
            url = _clean(record.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            html = _fetch_html(url, timeout_seconds, http_get)
            if not html:
                continue
            image_url = extract_image_url(html, url)
            if image_url:
                images.append(
                    {
                        "record_key": _clean(record.get("record_key")),
                        "source_url": url,
                        "image_url": image_url,
                        "kind": "og_image",
                    }
                )
        if images:
            manifest_stories.append(
                {
                    "story_id": _clean(story.get("story_id")),
                    "story_title": _clean(story.get("story_title")),
                    "images": images,
                }
            )
    return {"schema_version": SCHEMA_VERSION, "stories": manifest_stories}
