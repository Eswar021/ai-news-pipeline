from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

from src.pipeline.L1_collection.common import clean_text


SOURCE_PRIORITY = {
    "ai_company_blogs": 0,
    "tech_news_apis": 1,
    "research_papers": 2,
    "youtube_podcast_transcripts": 3,
    "community_signals": 4,
}
CONTENT_PRIORITY = {
    "full": 0,
    "partial": 1,
    "title_only": 2,
}
GENERIC_TITLES = {
    "ai",
    "cloud",
    "featured",
    "news",
    "blog",
    "articles",
    "page 2",
    "page 3",
}
LISTING_PATH_PARTS = (
    "/category/",
    "/categories/",
    "/tag/",
    "/tags/",
    "/page/",
    "/topic/",
)
LOW_SCRIPT_VALUE_TUTORIAL_PREFIXES = (
    "build custom ",
    "building ",
    "integrating ",
    "prompting ",
)


def select_story_inputs(stories: list[dict], layer4_cfg: dict) -> list[dict]:
    top_story_limit = int(layer4_cfg["top_story_limit"])
    max_records_per_story = int(layer4_cfg["max_records_per_story"])

    ranked = sorted(stories, key=lambda story: int(story.get("rank", 999999)))
    selected: list[dict] = []
    for story in ranked:
        story_input = build_story_input(story, max_records_per_story)
        if not _is_story_usable(story_input):
            continue
        selected.append(story_input)
        if len(selected) >= top_story_limit:
            break
    return selected


def build_story_input(story: dict, max_records_per_story: int) -> dict:
    selected_records = _select_supporting_records(story.get("records", []), max_records_per_story)
    return {
        "story_id": story["story_id"],
        "story_title": story["story_title"],
        "story_type_hint": story.get("story_type_hint", "mixed_story"),
        "story_identity": dict(story.get("story_identity", {})),
        "rank": int(story.get("rank", 0)),
        "priority_bucket": story.get("priority_bucket", "low"),
        "source_groups": list(story.get("source_groups", [])),
        "story_signals": dict(story.get("story_signals", {})),
        "match_reasons": list(story.get("match_reasons", [])),
        "selected_supporting_records": selected_records,
        "selection_summary": {
            "selected_record_count": len(selected_records),
            "selected_source_group_counts": dict(
                Counter(record.get("source_group", "unknown") for record in selected_records)
            ),
        },
    }


def _select_supporting_records(records: list[dict], limit: int) -> list[dict]:
    if not records:
        return []

    extractable = [record for record in records if _is_extractable(record)]
    candidates = extractable if extractable else list(records)
    ordered = sorted(candidates, key=_record_sort_key)
    return ordered[:limit]


def _is_extractable(record: dict) -> bool:
    content = clean_text(record.get("content", ""))
    if _is_listing_record(record):
        return False
    if _is_short_official_summary(record):
        return False
    if len(content) >= 120:
        return True
    return record.get("source_group") in {"ai_company_blogs", "research_papers"}


def _record_sort_key(record: dict) -> tuple:
    content = clean_text(record.get("content", ""))
    return (
        SOURCE_PRIORITY.get(record.get("source_group", ""), 99),
        CONTENT_PRIORITY.get(record.get("content_status", ""), 99),
        float(record.get("trust_tier", 9) or 9),
        -len(content),
        record.get("published_at", ""),
        record.get("record_key", ""),
    )


def _is_story_usable(story_input: dict) -> bool:
    if _is_generic_title(story_input.get("story_title", "")):
        return False
    if _is_low_value_tutorial_story(story_input):
        return False
    identity = story_input.get("story_identity") or {}
    if identity.get("is_noise"):
        return False
    if identity.get("editorial_value") == "low" and (identity.get("is_tutorial") or identity.get("is_event_update")):
        return False
    return bool(story_input["selected_supporting_records"])


def _is_listing_record(record: dict) -> bool:
    title = clean_text(record.get("title", ""))
    if _is_generic_title(title):
        return True
    path = urlparse(clean_text(record.get("url", ""))).path.lower()
    return any(part in path for part in LISTING_PATH_PARTS)


def _is_generic_title(title: str) -> bool:
    cleaned = clean_text(title).lower()
    if cleaned in GENERIC_TITLES:
        return True
    return cleaned.startswith("page ") and len(cleaned.split()) <= 2


def _is_short_official_summary(record: dict) -> bool:
    if record.get("source_group") != "ai_company_blogs":
        return False
    if record.get("content_source") != "entry_summary":
        return False
    return len(clean_text(record.get("content", ""))) < 700


def _is_low_value_tutorial_story(story_input: dict) -> bool:
    records = story_input.get("selected_supporting_records", [])
    if len(records) != 1:
        return False
    if records[0].get("source_group") != "ai_company_blogs":
        return False
    title = clean_text(story_input.get("story_title", "")).lower()
    return title.startswith(LOW_SCRIPT_VALUE_TUTORIAL_PREFIXES)
