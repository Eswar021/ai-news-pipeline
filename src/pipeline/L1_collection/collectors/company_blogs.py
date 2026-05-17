from __future__ import annotations

import xml.etree.ElementTree as ET

from src.pipeline.L1_collection.common import (
    build_record,
    clean_text,
    extract_article_text,
    normalize_content,
    request_text,
    strip_html,
    within_window,
)


def collect(cfg: dict) -> dict:
    window = cfg["collection_window"]
    timeout = int(cfg.get("request_timeout_seconds", 20))
    max_items_per_source = int(cfg.get("runtime", {}).get("max_items_per_source", 4))

    all_records: list[dict] = []
    source_summaries: dict[str, dict] = {}

    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue

        fetched_count = 0
        kept_count = 0
        filtered_out_count = 0
        notes: list[str] = []
        status = "ok"

        try:
            feed_text = request_text(source["feed_url"], timeout=timeout)
            entries = _parse_feed_entries(feed_text)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            source_summaries[source["id"]] = {
                "status": status,
                "fetched_count": 0,
                "kept_count": 0,
                "filtered_out_count": 0,
                "notes": notes,
            }
            continue

        source_records: list[dict] = []
        for entry in entries:
            fetched_count += 1
            published_at = entry.get("published_at", "")
            if not within_window(published_at, window["start"], window["end"]):
                filtered_out_count += 1
                continue

            article_body = ""
            try:
                article_html = request_text(entry["url"], timeout=timeout)
                article_body = extract_article_text(article_html)
            except Exception:
                notes.append(f"Article fetch failed for {entry['url']}")

            content, content_status = normalize_content(article_body, fallback=entry.get("summary", ""))
            record = build_record(
                source=source["id"],
                source_group=cfg["source_group"],
                source_type=source.get("source_type", "official_company_blog"),
                title=entry["title"],
                url=entry["url"],
                published_at=published_at,
                content=content,
                metadata={
                    "collector": "company_blogs",
                    "source_name": source["name"],
                    "trust_tier": source.get("trust_tier"),
                    "content_status": content_status,
                    "summary": clean_text(entry.get("summary", "")),
                },
            )
            source_records.append(record)
            kept_count += 1
            if kept_count >= max_items_per_source:
                break

        all_records.extend(source_records)
        source_summaries[source["id"]] = {
            "status": status,
            "fetched_count": fetched_count,
            "kept_count": kept_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        }

    return {
        "records": all_records,
        "summary": {
            "collector": "company_blogs",
            "status": "partial" if any(item["status"] != "ok" for item in source_summaries.values()) else "ok",
            "fetched_count": sum(item["fetched_count"] for item in source_summaries.values()),
            "kept_count": len(all_records),
            "filtered_out_count": sum(item["filtered_out_count"] for item in source_summaries.values()),
            "sources": source_summaries,
        },
    }


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
