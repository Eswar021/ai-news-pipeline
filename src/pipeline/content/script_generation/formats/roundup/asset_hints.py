from __future__ import annotations

from typing import Any

from .source_truth import StoryTruthIndex
from .utils import clean_text, dedupe, story_id


def build_story_asset_hints(
    story: dict[str, Any],
    truth_index: StoryTruthIndex | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build objective asset references plus LLM-authored semantic visual hints."""

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

    raw_truth = truth_index.model_dump(mode="json") if isinstance(truth_index, StoryTruthIndex) else dict(truth_index or {})
    semantic_items = [dict(item) for item in raw_truth.get("items") or [] if isinstance(item, dict)]
    metric_candidates = [
        {
            "truth_id": clean_text(item.get("truth_id")),
            "record_key": clean_text(item.get("record_key")),
            "source_text": clean_text(item.get("source_text")),
            "value_text": clean_text(item.get("value_text")),
            "meaning": clean_text(item.get("editorial_use")),
            "visual_role": clean_text(item.get("visual_role")),
            "visual_opportunity": clean_text(item.get("visual_opportunity")),
            "chart_eligible": clean_text(item.get("visual_role")) in {"comparison", "trend"},
            "classification_source": "llm_semantic_brief",
        }
        for item in semantic_items
        if clean_text(item.get("truth_type")) == "metric" and clean_text(item.get("value_text"))
    ]
    semantic_visual_roles = dedupe(
        [clean_text(item.get("visual_role")) for item in semantic_items if clean_text(item.get("visual_role")) != "none"]
    )
    return {
        "story_id": story_id(story),
        "source_pages": source_pages,
        "logo_entities": entities,
        "product_surfaces": [
            value
            for value in dedupe([clean_text(identity.get("product_or_project"))])
            if value.lower() not in {"unknown", "none", "n/a"}
        ],
        "metric_candidates": metric_candidates,
        "semantic_visual_roles": semantic_visual_roles,
        "semantic_visual_opportunities": [
            clean_text(item.get("visual_opportunity"))
            for item in semantic_items
            if clean_text(item.get("visual_opportunity"))
        ],
        "available_asset_types": dedupe(
            [
                *("source_page" for _ in source_pages[:1]),
                *("logo" for _ in entities[:1]),
                *("chart" for item in metric_candidates if item["chart_eligible"]),
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
