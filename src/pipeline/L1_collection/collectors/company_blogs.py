from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from src.pipeline.L1_collection.common import (
    build_record,
    clean_text,
    extract_article_text,
    extract_published_at_from_html,
    request_text,
    strip_html,
)


GENERIC_TITLES = {
    "ai",
    "cloud",
    "featured",
    "news",
    "page 2",
    "page 3",
    "blog",
    "articles",
}
LISTING_PATH_PARTS = (
    "/category/",
    "/categories/",
    "/tag/",
    "/tags/",
    "/page/",
    "/topic/",
)
LISTING_EXACT_PATHS = {
    "/blog",
    "/en/blog",
    "/news",
    "/en/news",
}


def collect(cfg: dict) -> dict:
    timeout = int(cfg.get("request_timeout_seconds", 20))
    max_items_per_source = int(cfg.get("runtime", {}).get("max_items_per_source", 4))

    all_records: list[dict] = []
    source_summaries: dict[str, dict] = {}

    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue

        fetched_count = 0
        collected_count = 0
        filtered_out_count = 0
        notes: list[str] = []
        status = "ok"

        try:
            entries = _fetch_entries(source, timeout)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            source_summaries[source["id"]] = {
                "status": status,
                "fetched_count": 0,
                "collected_count": 0,
                "filtered_out_count": 0,
                "notes": notes,
            }
            continue

        source_records: list[dict] = []
        for entry in entries:
            fetched_count += 1
            if _is_listing_entry(entry):
                filtered_out_count += 1
                notes.append(f"Filtered listing/category entry: {entry['title']} ({entry['url']})")
                continue

            article_body = ""
            article_html = ""
            resolved_title = entry["title"]
            article_published_at = entry.get("published_at", "")
            try:
                article_html = _fetch_article_html(entry["url"], timeout, source["id"])
                resolved_title = _resolve_article_title(entry["title"], article_html, source["id"])
                article_body = _extract_source_article_text(article_html, source["id"])
                article_page_date = extract_published_at_from_html(article_html)
                if source["id"] == "google_deepmind_blog":
                    article_published_at = article_page_date or article_published_at
                elif not article_published_at:
                    article_published_at = article_page_date
            except Exception:
                notes.append(f"Article fetch failed for {entry['url']}")

            content = article_body or clean_text(entry.get("summary", ""))
            content_source = "article_body" if article_body else "entry_summary"
            integrity = _content_integrity(resolved_title, content, content_source)
            source_relationship = _source_relationship(source["id"], entry["url"])
            if integrity["status"] != "ok":
                notes.append(
                    f"Content integrity {integrity['status']}: {resolved_title} ({entry['url']})"
                )
            record = build_record(
                source=source["id"],
                source_group=cfg["source_group"],
                source_type=source.get("source_type", "official_company_blog"),
                title=resolved_title,
                url=entry["url"],
                published_at=article_published_at,
                content=content,
                extra_fields={
                    "collector": "company_blogs",
                    "source_name": source["name"],
                    "trust_tier": source.get("trust_tier"),
                    "summary": clean_text(entry.get("summary", "")),
                    "mode": source.get("mode", "rss"),
                    "content_source": content_source,
                    "content_integrity_status": integrity["status"],
                    "content_integrity_reason": integrity["reason"],
                    "content_title_overlap": integrity["title_overlap"],
                    "content_title_coverage": integrity["title_coverage"],
                    **source_relationship,
                },
            )
            source_records.append(record)
            collected_count += 1
            if collected_count >= max_items_per_source:
                break

        all_records.extend(source_records)
        source_summaries[source["id"]] = {
            "status": status,
            "fetched_count": fetched_count,
            "collected_count": collected_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        }

    return {
        "records": all_records,
        "summary": {
            "collector": "company_blogs",
            "status": "partial" if any(item["status"] != "ok" for item in source_summaries.values()) else "ok",
            "fetched_count": sum(item["fetched_count"] for item in source_summaries.values()),
            "collected_count": len(all_records),
            "filtered_out_count": sum(item["filtered_out_count"] for item in source_summaries.values()),
            "sources": source_summaries,
        },
    }


def _fetch_article_html(url: str, timeout: int, source_id: str) -> str:
    try:
        return request_text(url, timeout=timeout)
    except Exception as first_error:
        if not url.endswith("/"):
            try:
                return request_text(f"{url}/", timeout=timeout)
            except Exception:
                pass
        if source_id == "openai_news":
            retry_url = f"{url.rstrip('/')}/?utm_source=rss"
            return request_text(retry_url, timeout=timeout)
        raise first_error


def _source_relationship(source_id: str, url: str) -> dict:
    if source_id != "huggingface_blog":
        return {"source_relationship": "first_party"}

    path_parts = [part for part in urlparse(clean_text(url)).path.strip("/").split("/") if part]
    if len(path_parts) >= 3 and path_parts[0] == "blog":
        return {
            "source_relationship": "hosted_vendor_post",
            "hosted_author_or_org": path_parts[1],
        }
    return {"source_relationship": "first_party"}


def _extract_source_article_text(html: str, source_id: str) -> str:
    text = extract_article_text(html)
    if source_id == "openai_news":
        return _trim_openai_article_text(text)
    return text


def _trim_openai_article_text(text: str) -> str:
    cleaned = clean_text(text)
    for marker in (
        "Keep reading",
        "Our Research",
        "Latest Advancements",
        "OpenAI ©",
    ):
        index = cleaned.find(marker)
        if index > 500:
            cleaned = cleaned[:index]
            break
    return cleaned


def _content_integrity(title: str, content: str, content_source: str) -> dict:
    if content_source != "article_body":
        return {
            "status": "summary_only",
            "reason": "article_body_missing",
            "title_overlap": 0,
            "title_coverage": 0.0,
        }

    cleaned_content = clean_text(content)
    if len(cleaned_content) < 700:
        status = "wrong_article" if _lead_title_mismatch(title, cleaned_content) else "too_short"
        return {
            "status": status,
            "reason": status,
            **_title_overlap_stats(title, cleaned_content),
        }

    if _lead_title_mismatch(title, cleaned_content):
        return {
            "status": "title_mismatch",
            "reason": "article_lead_title_mismatch",
            **_title_overlap_stats(title, cleaned_content),
        }

    return {
        "status": "ok",
        "reason": "",
        **_title_overlap_stats(title, cleaned_content),
    }


def _lead_title_mismatch(title: str, content: str) -> bool:
    title_tokens = _important_title_tokens(title)
    if len(title_tokens) < 3:
        return False

    lead = clean_text(content)[:120]
    if clean_text(title).lower() in clean_text(content).lower()[:500]:
        return False

    lead_tokens = _important_title_tokens(lead)
    overlap = title_tokens & lead_tokens
    coverage = len(overlap) / len(title_tokens)
    return len(overlap) <= 1 or coverage < 0.22


def _title_overlap_stats(title: str, content: str) -> dict:
    title_tokens = _important_title_tokens(title)
    lead_tokens = _important_title_tokens(clean_text(content)[:220])
    overlap = title_tokens & lead_tokens
    coverage = len(overlap) / len(title_tokens) if title_tokens else 0.0
    return {
        "title_overlap": len(overlap),
        "title_coverage": round(coverage, 3),
    }


def _important_title_tokens(text: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "with",
        "your",
    }
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", clean_text(text).lower()):
        if len(token) < 3 and token != "ai":
            continue
        if token in stopwords:
            continue
        tokens.add(token)
    return tokens


def _is_listing_entry(entry: dict) -> bool:
    title = clean_text(entry.get("title", "")).lower()
    url = clean_text(entry.get("url", ""))
    path = urlparse(url).path.lower()
    if path.rstrip("/") in LISTING_EXACT_PATHS:
        return True
    if title in GENERIC_TITLES:
        return True
    if title.startswith("page ") and len(title.split()) <= 2:
        return True
    return any(part in path for part in LISTING_PATH_PARTS)


def _resolve_article_title(entry_title: str, article_html: str, source_id: str) -> str:
    if source_id != "google_deepmind_blog":
        return clean_text(entry_title)

    html_title = _extract_article_title_from_html(article_html)
    if html_title and not _is_generic_article_title(html_title):
        return html_title
    return clean_text(entry_title)


def _extract_article_title_from_html(html: str) -> str:
    for pattern in (
        r'<meta[^>]+(?:property|name)=["\'](?:og:title|twitter:title)["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:title|twitter:title)["\']',
        r"<h1[^>]*>(.*?)</h1>",
        r"<title[^>]*>(.*?)</title>",
    ):
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        title = _clean_article_title(strip_html(match.group(1)))
        if title:
            return title
    return ""


def _clean_article_title(title: str) -> str:
    cleaned = clean_text(title)
    cleaned = re.sub(r"\s*[-|]\s*(Google DeepMind|DeepMind|Google)\s*$", "", cleaned, flags=re.IGNORECASE)
    return clean_text(cleaned)


def _is_generic_article_title(title: str) -> bool:
    cleaned = clean_text(title).lower()
    if not cleaned:
        return True
    if cleaned in GENERIC_TITLES or cleaned in {"google deepmind", "deepmind"}:
        return True
    return cleaned.startswith(("discover our latest", "our mission is to build ai responsibly"))


def _fetch_entries(source: dict, timeout: int) -> list[dict]:
    mode = source.get("mode", "rss")
    if mode == "rss":
        feed_text = request_text(source["feed_url"], timeout=timeout)
        return _parse_feed_entries(feed_text)
    if mode == "anthropic_listing":
        html = request_text(source["listing_url"], timeout=timeout)
        base_url = source["base_url"]
        prefixes = source.get("allowed_path_prefixes") or ["/news/", "/research/", "/index/"]
        return _parse_anthropic_entries(html, base_url=base_url, allowed_prefixes=prefixes)
    if mode == "generic_listing":
        html = request_text(source["listing_url"], timeout=timeout)
        base_url = source["base_url"]
        prefixes = source.get("allowed_path_prefixes") or ["/blog/"]
        return _parse_generic_listing_entries(html, base_url=base_url, allowed_prefixes=prefixes)
    raise ValueError(f"Unsupported company blog mode: {mode}")


def _parse_feed_entries(feed_text: str) -> list[dict]:
    root = ET.fromstring(feed_text)
    entries: list[dict] = []

    for item in root.findall(".//item"):
        entries.append({
            "title": _first_text(item, "title"),
            "url": _first_text(item, "link"),
            "published_at": _first_text(item, "pubDate"),
            "summary": strip_html(_first_text(item, "description")),
        })

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns):
        link = ""
        link_el = entry.find("atom:link", ns)
        if link_el is not None:
            link = link_el.attrib.get("href", "")
        entries.append({
            "title": _first_text(entry, "title"),
            "url": link,
            "published_at": _first_text(entry, "published") or _first_text(entry, "updated"),
            "summary": strip_html(_first_text(entry, "summary")),
        })

    return [entry for entry in entries if entry["title"] and entry["url"]]


def _first_text(element, tag_name: str) -> str:
    for child in element.iter():
        if child.tag.endswith(tag_name):
            return clean_text(child.text or "")
    return ""


class _AnthropicListingParser(HTMLParser):
    def __init__(self, allowed_prefixes: list[str]):
        super().__init__()
        self.allowed_prefixes = tuple(allowed_prefixes)
        self.posts: list[dict] = []
        self._current_link: str | None = None
        self._current_title: str | None = None
        self._current_date: str | None = None
        self._heading_text: list[str] = []
        self._in_heading = False
        self._depth = 0
        self._anchor_depth = 0
        self._in_anchor = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._depth += 1

        if tag == "a" and "href" in attrs:
            href = attrs["href"]
            if href.startswith("/") and href.startswith(self.allowed_prefixes):
                self._in_anchor = True
                self._anchor_depth = self._depth
                self._current_link = href
                self._current_title = None
                self._current_date = None

        if self._in_anchor and tag in {"h2", "h3", "h4"}:
            self._in_heading = True
            self._heading_text = []

    def handle_endtag(self, tag):
        if self._in_heading and tag in {"h2", "h3", "h4"}:
            self._in_heading = False
            text = " ".join(self._heading_text).strip()
            if text and not self._current_title:
                self._current_title = text

        if self._in_anchor and self._depth == self._anchor_depth and tag == "a":
            if self._current_link and self._current_title:
                self.posts.append(
                    {
                        "url": self._current_link,
                        "title": self._current_title,
                        "published_at": self._current_date or "",
                        "summary": "",
                    }
                )
            self._in_anchor = False
            self._current_link = None
            self._current_title = None
            self._current_date = None

        self._depth -= 1

    def handle_data(self, data):
        value = data.strip()
        if not value:
            return

        if self._in_heading:
            self._heading_text.append(value)

        if self._in_anchor and not self._current_date:
            if re.match(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\s+\d{4}", value):
                self._current_date = value


def _parse_anthropic_entries(html: str, base_url: str, allowed_prefixes: list[str]) -> list[dict]:
    parser = _AnthropicListingParser(allowed_prefixes)
    parser.feed(html)

    seen = set()
    entries: list[dict] = []
    for post in parser.posts:
        link = post["url"]
        if link in seen:
            continue
        seen.add(link)
        entries.append(
            {
                "title": post["title"],
                "url": f"{base_url}{link}",
                "published_at": post["published_at"],
                "summary": "",
            }
        )
    return entries


class _GenericListingParser(HTMLParser):
    GENERIC_ANCHOR_TEXT = {"learn more", "read more", "more", "view all"}

    def __init__(self, allowed_prefixes: list[str], base_url: str):
        super().__init__()
        self.allowed_prefixes = tuple(allowed_prefixes)
        self.base_url = base_url.rstrip("/")
        self.base_host = urlparse(self.base_url).netloc.lower()
        self.entries: list[dict] = []
        self._current_href: str | None = None
        self._current_title_parts: list[str] = []
        self._current_anchor_text_parts: list[str] = []
        self._current_date: str | None = None
        self._depth = 0
        self._anchor_depth = 0
        self._in_anchor = False
        self._in_heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._depth += 1

        if tag == "a" and "href" in attrs:
            href = self._normalize_href(attrs["href"])
            if href and href.startswith(self.allowed_prefixes):
                self._in_anchor = True
                self._anchor_depth = self._depth
                self._current_href = href
                self._current_title_parts = []
                self._current_anchor_text_parts = []
                self._current_date = None

        if self._in_anchor and tag in {"h1", "h2", "h3", "h4"}:
            self._in_heading = True

    def handle_endtag(self, tag):
        if self._in_heading and tag in {"h1", "h2", "h3", "h4"}:
            self._in_heading = False

        if self._in_anchor and self._depth == self._anchor_depth and tag == "a":
            title = clean_text(" ".join(self._current_title_parts))
            if not title:
                fallback = clean_text(" ".join(self._current_anchor_text_parts))
                if fallback.lower() not in self.GENERIC_ANCHOR_TEXT:
                    title = fallback
            if self._current_href and title:
                self.entries.append(
                    {
                        "url": self._current_href,
                        "title": title,
                        "published_at": self._current_date or "",
                        "summary": "",
                    }
                )
            self._in_anchor = False
            self._current_href = None
            self._current_title_parts = []
            self._current_anchor_text_parts = []
            self._current_date = None

        self._depth -= 1

    def handle_data(self, data):
        value = clean_text(data)
        if not value or not self._in_anchor:
            return
        self._current_anchor_text_parts.append(value)
        if self._in_heading:
            self._current_title_parts.append(value)
        if self._current_date is None:
            if re.match(r"(Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|September|Oct|October|Nov|November|Dec|December)\s+\d{1,2},\s+\d{4}", value):
                self._current_date = value
            elif re.match(r"(Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|September|Oct|October|Nov|November|Dec|December)\s+\d{4}", value):
                self._current_date = value

    def _normalize_href(self, href: str) -> str:
        raw = clean_text(href)
        if not raw:
            return ""
        if raw.startswith(self.allowed_prefixes):
            return raw
        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            host = parsed.netloc.lower()
            if host == self.base_host and parsed.path.startswith(self.allowed_prefixes):
                return parsed.path
        return ""


def _parse_generic_listing_entries(html: str, base_url: str, allowed_prefixes: list[str]) -> list[dict]:
    parser = _GenericListingParser(allowed_prefixes, base_url)
    parser.feed(html)

    entries: list[dict] = []
    seen = set()
    for entry in parser.entries:
        href = entry["url"]
        if href in seen:
            continue
        seen.add(href)
        entries.append(
            {
                "title": entry["title"],
                "url": f"{base_url}{href}",
                "published_at": entry["published_at"],
                "summary": "",
            }
        )
    return entries
