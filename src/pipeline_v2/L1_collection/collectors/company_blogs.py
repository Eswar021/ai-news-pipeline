from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlparse
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
FULL_ARTICLE_CONTENT_SOURCES = {"article_body", "markdown_article_body"}


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
            if not entry.get("skip_article_fetch"):
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

            entry_content = clean_text(entry.get("content", ""))
            content = article_body or entry_content or clean_text(entry.get("summary", ""))
            content_source = "article_body" if article_body else entry.get("content_source", "entry_summary")
            integrity = _content_integrity(resolved_title, content, content_source)
            source_relationship = _source_relationship(source["id"], entry["url"])
            if entry.get("fetch_note"):
                notes.append(entry["fetch_note"])
            if integrity["status"] != "ok":
                notes.append(
                    f"Content integrity {integrity['status']}: {resolved_title} ({entry['url']})"
                )
            extra_fields = {
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
            }
            if entry.get("article_markdown_url"):
                extra_fields["article_markdown_url"] = entry["article_markdown_url"]
            if entry.get("categories"):
                extra_fields["categories"] = entry["categories"]
            record = build_record(
                source=source["id"],
                source_group=cfg["source_group"],
                source_type=source.get("source_type", "official_company_blog"),
                title=resolved_title,
                url=entry["url"],
                published_at=article_published_at,
                content=content,
                extra_fields=extra_fields,
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
    if content_source not in FULL_ARTICLE_CONTENT_SOURCES:
        return {
            "status": "summary_only",
            "reason": "article_body_missing",
            "title_overlap": 0,
            "title_coverage": 0.0,
        }

    cleaned_content = clean_text(content)
    minimum_body_length = 300 if content_source == "markdown_article_body" else 700
    if len(cleaned_content) < minimum_body_length:
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
    if mode == "spa_bundle_listing":
        html = request_text(source["listing_url"], timeout=timeout)
        base_url = source["base_url"]
        prefixes = source.get("allowed_path_prefixes") or ["/blog/"]
        return _parse_spa_bundle_entries(
            html,
            base_url=base_url,
            allowed_prefixes=prefixes,
            timeout=timeout,
        )
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


def _parse_spa_bundle_entries(html: str, base_url: str, allowed_prefixes: list[str], timeout: int) -> list[dict]:
    bundle_urls = _extract_same_site_script_urls(html, base_url)
    entries: list[dict] = []
    for bundle_url in bundle_urls:
        bundle_text = request_text(bundle_url, timeout=timeout)
        entries.extend(_parse_blog_entries_from_bundle(bundle_text, base_url, allowed_prefixes))

    seen = set()
    unique_entries: list[dict] = []
    for entry in entries:
        if entry["url"] in seen:
            continue
        seen.add(entry["url"])
        unique_entries.append(entry)
    return _hydrate_spa_markdown_entries(unique_entries, base_url, timeout)


def _extract_same_site_script_urls(html: str, base_url: str) -> list[str]:
    base_host = urlparse(base_url).netloc.lower()
    urls: list[str] = []
    for raw_src in re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html, flags=re.IGNORECASE):
        script_url = urljoin(base_url, raw_src)
        if urlparse(script_url).netloc.lower() == base_host:
            urls.append(script_url)
    return list(dict.fromkeys(urls))


def _parse_blog_entries_from_bundle(bundle_text: str, base_url: str, allowed_prefixes: list[str]) -> list[dict]:
    entries: list[dict] = []
    allowed = tuple(allowed_prefixes)

    latest_pattern = re.compile(
        r'articleSlug:"(?P<slug>[^"]+)",date:"(?P<date>[^"]+)",title:"(?P<title>[^"]+)"'
    )
    for match in latest_pattern.finditer(bundle_text):
        link = f"/blog/{_decode_js_string(match.group('slug'))}"
        if not link.startswith(allowed):
            continue
        title = _decode_js_string(match.group("title"))
        entries.append(
            {
                "title": title,
                "url": urljoin(base_url, link),
                "published_at": _decode_js_string(match.group("date")),
                "summary": _bundle_summary(title, "", match.group("date")),
                "content": _bundle_content(title, "", match.group("date"), bundle_text),
                "content_source": "site_bundle_summary",
                "skip_article_fetch": True,
                "slug": _decode_js_string(match.group("slug")),
            }
        )

    blog_card_pattern = re.compile(
        r'title:"(?P<title>[^"]+)",date:"(?P<date>[^"]+)",tags:\[(?P<tags>[^\]]*)\],'
        r'link_text:"Read blog",link:"(?P<link>/blog/[^"]+)"'
    )
    for match in blog_card_pattern.finditer(bundle_text):
        link = _decode_js_string(match.group("link"))
        if not link.startswith(allowed):
            continue
        title = _decode_js_string(match.group("title"))
        tags = _decode_tag_list(match.group("tags"))
        date = _decode_js_string(match.group("date"))
        entries.append(
            {
                "title": title,
                "url": urljoin(base_url, link),
                "published_at": date,
                "summary": _bundle_summary(title, ", ".join(tags), date),
                "content": _bundle_content(title, ", ".join(tags), date, bundle_text),
                "content_source": "site_bundle_summary",
                "skip_article_fetch": True,
                "slug": link.rstrip("/").rsplit("/", 1)[-1],
            }
        )

    for slug in _extract_blog_slugs_from_bundle(bundle_text):
        link = f"/blog/{slug}"
        if not link.startswith(allowed):
            continue
        entries.append(
            {
                "title": slug.replace("-", " ").title(),
                "url": urljoin(base_url, link),
                "published_at": "",
                "summary": "",
                "content": "",
                "content_source": "site_bundle_summary",
                "skip_article_fetch": True,
                "slug": slug,
            }
        )

    return entries


def _extract_blog_slugs_from_bundle(bundle_text: str) -> list[str]:
    match = re.search(r"BLOG_POST_SLUGS\s*=\s*\[(?P<slugs>[^\]]+)\]", bundle_text)
    if not match:
        return []
    slugs = []
    for raw_slug in re.findall(r'"((?:\\.|[^"\\])*)"', match.group("slugs")):
        slugs.append(_decode_js_string(raw_slug))
    return list(dict.fromkeys(slugs))


def _hydrate_spa_markdown_entries(entries: list[dict], base_url: str, timeout: int) -> list[dict]:
    hydrated = []
    for entry in entries:
        slug = clean_text(entry.get("slug", "")) or _slug_from_blog_url(entry["url"])
        if not slug:
            hydrated.append(entry)
            continue

        markdown_url = urljoin(base_url, f"/assets/blog-posts/{slug}.md")
        try:
            markdown_text = request_text(markdown_url, timeout=timeout)
            article = _parse_markdown_article(markdown_text)
        except Exception as exc:
            fallback = dict(entry)
            fallback["fetch_note"] = f"Markdown article fetch failed for {entry['url']}: {exc}"
            hydrated.append(fallback)
            continue

        title = _first_non_empty(article.get("title"), entry.get("title"))
        published_at = _first_non_empty(
            article.get("date"),
            article.get("published_at"),
            article.get("published"),
            entry.get("published_at"),
        )
        summary = _first_non_empty(
            article.get("description"),
            article.get("summary"),
            article.get("excerpt"),
            entry.get("summary"),
        )
        content = _markdown_article_content(
            title=title,
            summary=summary,
            body=article.get("body", ""),
            published_at=published_at,
        )

        record = dict(entry)
        record.update(
            {
                "title": title,
                "published_at": published_at,
                "summary": summary or entry.get("summary", ""),
                "content": content,
                "content_source": "markdown_article_body",
                "article_markdown_url": markdown_url,
                "skip_article_fetch": True,
            }
        )
        categories = _first_non_empty(article.get("categories"), article.get("tags"))
        if categories:
            record["categories"] = categories if isinstance(categories, list) else [categories]
        hydrated.append(record)
    return hydrated


def _slug_from_blog_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    if "/blog/" not in path:
        return ""
    return clean_text(path.rsplit("/", 1)[-1])


def _parse_markdown_article(markdown_text: str) -> dict:
    metadata: dict[str, str | list[str]] = {}
    body = markdown_text
    match = re.match(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?(?P<body>.*)\Z", markdown_text, re.DOTALL)
    if match:
        metadata = _parse_frontmatter(match.group("meta"))
        body = match.group("body")

    parsed = dict(metadata)
    parsed["body"] = _markdown_to_text(body)
    return parsed


def _parse_frontmatter(frontmatter: str) -> dict:
    values: dict[str, str | list[str]] = {}
    active_list_key = ""
    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if active_list_key and stripped.startswith("- "):
            item = _clean_frontmatter_value(stripped[2:])
            if item:
                values.setdefault(active_list_key, [])
                if isinstance(values[active_list_key], list):
                    values[active_list_key].append(item)
            continue

        if ":" not in stripped:
            active_list_key = ""
            continue

        key, raw_value = stripped.split(":", 1)
        key = _normalize_frontmatter_key(key)
        value = raw_value.strip()
        if not value:
            values[key] = []
            active_list_key = key
            continue

        parsed_value = _parse_frontmatter_value(value)
        values[key] = parsed_value
        active_list_key = key if isinstance(parsed_value, list) else ""
    return values


def _parse_frontmatter_value(value: str) -> str | list[str]:
    cleaned = value.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        try:
            parsed = json.loads(cleaned.replace("'", '"'))
            if isinstance(parsed, list):
                return [clean_text(str(item)) for item in parsed if clean_text(str(item))]
        except Exception:
            return [
                _clean_frontmatter_value(item)
                for item in cleaned.strip("[]").split(",")
                if _clean_frontmatter_value(item)
            ]
    return _clean_frontmatter_value(cleaned)


def _clean_frontmatter_value(value: str) -> str:
    return clean_text(value.strip().strip('"').strip("'"))


def _normalize_frontmatter_key(key: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    aliases = {
        "publishedat": "published_at",
        "published_date": "published_at",
        "publish_date": "published_at",
        "description": "description",
    }
    return aliases.get(normalized, normalized)


def _markdown_to_text(markdown_text: str) -> str:
    text = re.sub(r"```.*?```", " ", markdown_text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[\^[^\]]+]", "", text)

    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("|"):
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        line = re.sub(r"^>\s*", "", line)
        lines.append(line)
    return clean_text(strip_html(" ".join(lines)))


def _markdown_article_content(title: str, summary: str, body: str, published_at: str) -> str:
    cleaned_title = clean_text(title)
    cleaned_body = clean_text(body)
    cleaned_summary = clean_text(summary)

    if cleaned_title and cleaned_body.lower().startswith(cleaned_title.lower()):
        article_text = cleaned_body
    else:
        article_text = clean_text(". ".join(part for part in (cleaned_title, cleaned_body) if part))

    if len(article_text) < 700 and cleaned_summary and cleaned_summary.lower() not in article_text.lower():
        article_text = clean_text(". ".join(part for part in (cleaned_title, cleaned_summary, cleaned_body) if part))

    if published_at:
        article_text = clean_text(f"{article_text} Published: {published_at}")
    return article_text


def _first_non_empty(*values):
    for value in values:
        if isinstance(value, list):
            cleaned_items = [clean_text(str(item)) for item in value if clean_text(str(item))]
            if cleaned_items:
                return cleaned_items
            continue
        cleaned = clean_text(str(value)) if value is not None else ""
        if cleaned:
            return cleaned
    return ""


def _bundle_summary(title: str, tags: str, published_at: str) -> str:
    parts = [
        title,
        f"Tags: {tags}" if tags else "",
        f"Published: {published_at}" if published_at else "",
    ]
    return clean_text(". ".join(part for part in parts if part))


def _bundle_content(title: str, tags: str, published_at: str, bundle_text: str) -> str:
    description = _bundle_description_for_title(title, bundle_text)
    parts = [
        title,
        description,
        f"Tags: {tags}" if tags else "",
        f"Published: {published_at}" if published_at else "",
    ]
    return clean_text(". ".join(part for part in parts if part))


def _bundle_description_for_title(title: str, bundle_text: str) -> str:
    variants = _description_title_variants(title)
    for variant in variants:
        pattern = re.compile(
            rf'title:"{re.escape(variant)}",description:"(?P<description>(?:\\.|[^"\\])*)"',
        )
        match = pattern.search(bundle_text)
        if match:
            return clean_text(_decode_js_string(match.group("description")))
    return ""


def _description_title_variants(title: str) -> list[str]:
    variants = [title]
    for prefix in ("Introducing Google ", "Google "):
        if title.startswith(prefix):
            variants.append(title[len(prefix):])
    if title == "Google Antigravity CLI":
        variants.append("Antigravity CLI")
    if title == "Google Antigravity SDK":
        variants.append("Antigravity SDK")
    if title.startswith("Introducing Google Antigravity 2.0"):
        variants.append("Antigravity 2.0")
    return list(dict.fromkeys(variants))


def _decode_tag_list(raw_tags: str) -> list[str]:
    tags = []
    for raw in re.findall(r'"((?:\\.|[^"\\])*)"', raw_tags):
        tags.append(_decode_js_string(raw))
    return tags


def _decode_js_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value.replace('\\"', '"')


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
