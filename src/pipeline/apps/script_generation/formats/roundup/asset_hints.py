from __future__ import annotations

import re
from typing import Any

from .utils import clean_text, dedupe, story_id


METRIC_RE = re.compile(
    r"(?:\$?\d[\d,.]*\s?(?:%|x|billion|million|thousand|hours?|days?|tokens?|parameters?|GB|TB|bits?)?)",
    re.IGNORECASE,
)


def build_story_asset_hints(story: dict[str, Any]) -> dict[str, Any]:
    identity = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
    records = [record for record in story.get("records", []) if isinstance(record, dict)]
    entities = dedupe(
        [
            clean_text(identity.get("primary_entity")),
            clean_text(identity.get("owning_org")),
            clean_text(identity.get("product_or_project")),
        ]
    )
    source_pages = []
    metric_candidates: list[str] = []
    for record in records:
        url = _first_url(record)
        record_key = clean_text(record.get("record_key"))
        if url and record_key:
            source_pages.append(
                {
                    "record_key": record_key,
                    "url": url,
                    "title": clean_text(record.get("title")),
                    "source": clean_text(record.get("source_name") or record.get("source")),
                }
            )
        text = " ".join(
            clean_text(record.get(key))
            for key in ("title", "summary", "description")
            if clean_text(record.get(key))
        )
        metric_candidates.extend(match.group(0) for match in METRIC_RE.finditer(text))
    return {
        "story_id": story_id(story),
        "source_pages": source_pages,
        "logo_entities": entities,
        "product_surfaces": [
            value
            for value in dedupe([clean_text(identity.get("product_or_project"))])
            if value.lower() not in {"unknown", "none", "n/a"}
        ],
        "metric_candidates": dedupe(metric_candidates)[:12],
        "available_asset_types": dedupe(
            [
                *("source_page" for _ in source_pages[:1]),
                *("logo" for _ in entities[:1]),
                *("chart" for _ in metric_candidates[:1]),
                "diagram",
                "photo",
                "video",
                "kinetic_text",
            ]
        ),
    }


def _first_url(record: dict[str, Any]) -> str:
    for key in ("url", "source_url", "canonical_url", "resolved_url"):
        value = clean_text(record.get(key))
        if value.startswith(("http://", "https://")):
            return value
    return ""
