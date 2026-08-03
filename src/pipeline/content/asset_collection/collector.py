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
import time
from typing import Any, Callable
from urllib.parse import urljoin

try:  # requests is a first-party dependency (news collectors use it)
    import requests
except Exception:  # pragma: no cover - requests is always present in the app env
    requests = None  # type: ignore[assignment]

SCHEMA_VERSION = "asset_manifest_v1"

# Browser-like headers reduce intermittent bot-challenge responses (the page
# returns 200 but without the og:image meta) from sites like openai.com.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# og:image / twitter:image / link rel=image_src / itemprop, tolerating either
# attribute order and quote style.
_META_PATTERNS = [
    re.compile(r'<meta[^>]+(?:property|name)=["\']og:image(?::url|:secure_url)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image(?::url|:secure_url)?["\']', re.I),
    re.compile(r'<meta[^>]+(?:property|name)=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']twitter:image(?::src)?["\']', re.I),
    re.compile(r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+itemprop=["\']image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
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


def _resolve_record_image(
    url: str, *, timeout_seconds: float, http_get: Callable[..., Any], max_attempts: int
) -> str | None:
    """Fetch a URL and extract its share image, retrying a few times. Sites like
    openai.com intermittently return a 200 bot-challenge page WITHOUT the og:image
    meta; a retry usually lands a good response, so this is the core reliability
    fix for real source imagery."""
    for attempt in range(max(1, max_attempts)):
        html = _fetch_html(url, timeout_seconds, http_get)
        if html:
            image_url = extract_image_url(html, url)
            if image_url:
                return image_url
        if attempt + 1 < max_attempts:
            time.sleep(0.6 * (attempt + 1))
    return None


def build_asset_manifest(
    stories: list[dict[str, Any]],
    *,
    timeout_seconds: float = 8.0,
    max_images_per_story: int = 4,
    max_attempts: int = 3,
    http_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Build an asset manifest of real source images for the selected stories.

    Best-effort: stories/records without a resolvable image are simply omitted.
    Each record fetch is retried (``max_attempts``) to ride out intermittent
    bot-challenge responses. ``http_get`` is injectable for tests."""
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
            image_url = _resolve_record_image(
                url, timeout_seconds=timeout_seconds, http_get=http_get, max_attempts=max_attempts
            )
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
