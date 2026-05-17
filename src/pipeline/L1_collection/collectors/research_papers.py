from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlencode

from src.pipeline.L1_collection.common import build_record, request_text, within_window

ARXIV_API_URL = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}


def collect(cfg: dict) -> dict:
    window = cfg["collection_window"]
    timeout = int(cfg.get("request_timeout_seconds", 30))
    max_items_per_category = int(cfg.get("runtime", {}).get("max_items_per_category", 6))

    records: list[dict] = []
    category_summaries: dict[str, dict] = {}

    for category in cfg.get("categories", []):
        if not category.get("enabled", True):
            continue
        status = "ok"
        notes: list[str] = []

        params = {
            "search_query": f"cat:{category['category']}",
            "start": 0,
            "max_results": max_items_per_category * 3,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        fetched_count = 0
        kept_count = 0
        filtered_out_count = 0
        try:
            xml_text = request_text(ARXIV_API_URL, timeout=timeout, params=params)
            root = ET.fromstring(xml_text)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            category_summaries[category["id"]] = {
                "status": status,
                "fetched_count": 0,
                "kept_count": 0,
                "filtered_out_count": 0,
                "notes": notes,
            }
            continue

        for entry in root.findall("atom:entry", NS):
            fetched_count += 1
            published_at = entry.findtext("atom:published", "", NS).strip()
            if not within_window(published_at, window["start"], window["end"]):
                filtered_out_count += 1
                continue

            title = entry.findtext("atom:title", "", NS).strip().replace("\n", " ")
            abstract = entry.findtext("atom:summary", "", NS).strip().replace("\n", " ")
            authors = [
                author.findtext("atom:name", "", NS).strip()
                for author in entry.findall("atom:author", NS)
                if author.findtext("atom:name", "", NS).strip()
            ]
            url = entry.findtext("atom:id", "", NS).strip()

            records.append(
                build_record(
                    source=category["id"],
                    source_group=cfg["source_group"],
                    source_type="research_paper",
                    title=title,
                    url=url,
                    published_at=published_at,
                    content=abstract,
                    metadata={
                        "collector": "research_papers",
                        "category": category["category"],
                        "authors": authors,
                        "trust_tier": 1.5,
                        "content_status": "partial",
                    },
                )
            )
            kept_count += 1
            if kept_count >= max_items_per_category:
                break

        category_summaries[category["id"]] = {
            "status": status,
            "fetched_count": fetched_count,
            "kept_count": kept_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        }

    return {
        "records": records,
        "summary": {
            "collector": "research_papers",
            "status": "partial" if any(item["status"] != "ok" for item in category_summaries.values()) else "ok",
            "fetched_count": sum(item["fetched_count"] for item in category_summaries.values()),
            "kept_count": len(records),
            "filtered_out_count": sum(item["filtered_out_count"] for item in category_summaries.values()),
            "sources": category_summaries,
        },
    }
