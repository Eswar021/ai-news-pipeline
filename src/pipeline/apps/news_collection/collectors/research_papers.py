from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

from ..utils import build_record, request_text

ARXIV_API_URL = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}


def collect(cfg: dict) -> dict:
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
            "max_results": max_items_per_category,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        fetched_count = 0
        collected_count = 0
        filtered_out_count = 0
        try:
            root = _fetch_root(params, timeout)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            category_summaries[category["id"]] = {
                "status": status,
                "fetched_count": 0,
                "collected_count": 0,
                "filtered_out_count": 0,
                "notes": notes,
            }
            continue

        for entry in root.findall("atom:entry", NS):
            fetched_count += 1
            published_at = entry.findtext("atom:published", "", NS).strip()
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
                    extra_fields={
                        "collector": "research_papers",
                        "category": category["category"],
                        "authors": authors,
                        "trust_tier": 1.5,
                    },
                )
            )
            collected_count += 1
            if collected_count >= max_items_per_category:
                break

        time.sleep(1.0)

        category_summaries[category["id"]] = {
            "status": status,
            "fetched_count": fetched_count,
            "collected_count": collected_count,
            "filtered_out_count": filtered_out_count,
            "notes": notes,
        }

    return {
        "records": records,
        "summary": {
            "collector": "research_papers",
            "status": "partial" if any(item["status"] != "ok" for item in category_summaries.values()) else "ok",
            "fetched_count": sum(item["fetched_count"] for item in category_summaries.values()),
            "collected_count": len(records),
            "filtered_out_count": sum(item["filtered_out_count"] for item in category_summaries.values()),
            "sources": category_summaries,
        },
    }


def _fetch_root(params: dict, timeout: int):
    last_exc = None
    for attempt in range(3):
        try:
            xml_text = request_text(ARXIV_API_URL, timeout=timeout, params=params)
            return ET.fromstring(xml_text)
        except Exception as exc:
            last_exc = exc
            if attempt == 2:
                break
            time.sleep(2.0 * (attempt + 1))
    raise last_exc
