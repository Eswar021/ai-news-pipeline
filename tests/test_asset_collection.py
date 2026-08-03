"""asset_collection: best-effort og:image extraction → source-image manifest."""
from __future__ import annotations

from src.pipeline.content.asset_collection import build_asset_manifest, extract_image_url


class _Resp:
    def __init__(self, *, status: int = 200, ctype: str = "text/html; charset=utf-8", text: str = "") -> None:
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        self.text = text


def _fake_get(pages: dict):
    def get(url: str, **_kwargs):
        item = pages.get(url)
        if isinstance(item, Exception):
            raise item
        if item is None:
            return _Resp(status=404)
        return item

    return get


OG = '<html><head><meta property="og:image" content="https://cdn.example.com/hero.jpg"></head></html>'
OG_CONTENT_FIRST = '<meta content="https://x.example.com/a.png" property="og:image">'
TW_RELATIVE = '<html><head><meta name="twitter:image" content="/img/rel.jpg"></head></html>'
NO_IMAGE = "<html><head><title>no image here</title></head><body>text</body></html>"


def test_extract_handles_both_attribute_orders() -> None:
    assert extract_image_url(OG, "https://example.com/a") == "https://cdn.example.com/hero.jpg"
    assert extract_image_url(OG_CONTENT_FIRST, "https://example.com/a") == "https://x.example.com/a.png"


def test_extract_twitter_fallback_and_relative_is_absolutized() -> None:
    assert extract_image_url(TW_RELATIVE, "https://news.site/story/1") == "https://news.site/img/rel.jpg"


def test_extract_unescapes_html_entities_in_url() -> None:
    html = '<meta property="og:image" content="https://cdn.example.com/i.png?w=1600&amp;h=900">'
    assert extract_image_url(html, "https://example.com") == "https://cdn.example.com/i.png?w=1600&h=900"


def test_extract_returns_none_when_absent() -> None:
    assert extract_image_url(NO_IMAGE, "https://example.com") is None
    assert extract_image_url("", "https://example.com") is None


def test_build_manifest_collects_images_and_omits_the_imageless() -> None:
    stories = [
        {"story_id": "s1", "story_title": "One", "records": [
            {"record_key": "r1", "url": "https://a.com/x"},
            {"record_key": "r2", "url": "https://b.com/y"},  # no image → omitted
        ]},
        {"story_id": "s2", "story_title": "Two", "records": [{"record_key": "r3", "url": "https://c.com/z"}]},  # fetch fails
    ]
    pages = {
        "https://a.com/x": _Resp(text=OG),
        "https://b.com/y": _Resp(text=NO_IMAGE),
        "https://c.com/z": RuntimeError("network down"),
    }
    manifest = build_asset_manifest(stories, http_get=_fake_get(pages))
    assert manifest["schema_version"] == "asset_manifest_v1"
    # s1 keeps its one real image; s2 (fetch error) is dropped entirely, no raise.
    assert [s["story_id"] for s in manifest["stories"]] == ["s1"]
    assert manifest["stories"][0]["images"] == [
        {"record_key": "r1", "source_url": "https://a.com/x", "image_url": "https://cdn.example.com/hero.jpg", "kind": "og_image"}
    ]


def test_build_manifest_caps_images_per_story() -> None:
    records = [{"record_key": f"r{i}", "url": f"https://a.com/{i}"} for i in range(6)]
    pages = {f"https://a.com/{i}": _Resp(text=OG) for i in range(6)}
    manifest = build_asset_manifest(
        [{"story_id": "s", "story_title": "S", "records": records}],
        http_get=_fake_get(pages),
        max_images_per_story=2,
    )
    assert len(manifest["stories"][0]["images"]) == 2


def test_build_manifest_skips_non_html_and_bad_status() -> None:
    stories = [{"story_id": "s", "story_title": "S", "records": [
        {"record_key": "r1", "url": "https://a.com/pdf"},
        {"record_key": "r2", "url": "https://a.com/404"},
    ]}]
    pages = {
        "https://a.com/pdf": _Resp(ctype="application/pdf", text=OG),  # not html → skip
        "https://a.com/404": _Resp(status=404, text=OG),
    }
    manifest = build_asset_manifest(stories, http_get=_fake_get(pages))
    assert manifest["stories"] == []
