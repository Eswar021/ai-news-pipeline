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
SOURCE_GROUP_TARGETS = {
    "ai_company_blogs": 7,
    "tech_news_apis": 2,
    "research_papers": 2,
    "youtube_podcast_transcripts": 1,
    "community_signals": 1,
}


def select_story_inputs(stories: list[dict], layer4_cfg: dict) -> list[dict]:
    top_story_limit = int(layer4_cfg["top_story_limit"])
    max_records_per_story = int(layer4_cfg["max_records_per_story"])

    ranked = sorted(stories, key=lambda story: int(story.get("rank", 999999)))
    usable: list[dict] = []
    for story in ranked:
        story_input = build_story_input(story, max_records_per_story)
        if not _is_story_usable(story_input):
            continue
        usable.append(story_input)
    return _select_balanced_story_pool(usable, top_story_limit)


def build_story_input(story: dict, max_records_per_story: int) -> dict:
    selected_records = _select_supporting_records(story.get("records", []), max_records_per_story)
    return {
        "story_id": story["story_id"],
        "story_title": story["story_title"],
        "story_type_hint": story.get("story_type_hint", "mixed_story"),
        "story_identity": dict(story.get("story_identity", {})),
        "rank": int(story.get("rank", 0)),
        "rank_score": int(story.get("rank_score", 0)),
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


def _select_balanced_story_pool(usable: list[dict], limit: int) -> list[dict]:
    selected: list[dict] = []
    selected_ids: set[str] = set()

    for group, target in SOURCE_GROUP_TARGETS.items():
        group_candidates = sorted(
            [story for story in usable if _primary_source_group(story) == group],
            key=_story_pool_sort_key,
        )
        for story in group_candidates[:target]:
            if len(selected) >= limit:
                break
            selected.append(story)
            selected_ids.add(story["story_id"])

    for story in usable:
        if len(selected) >= limit:
            break
        if story["story_id"] in selected_ids:
            continue
        selected.append(story)
        selected_ids.add(story["story_id"])

    return sorted(selected[:limit], key=lambda story: int(story.get("rank", 999999)))


def _primary_source_group(story_input: dict) -> str:
    counts = story_input.get("selection_summary", {}).get("selected_source_group_counts", {})
    if not counts:
        groups = story_input.get("source_groups", [])
        return groups[0] if groups else "unknown"
    return sorted(counts.items(), key=lambda item: (-item[1], SOURCE_PRIORITY.get(item[0], 99)))[0][0]


def _story_pool_sort_key(story_input: dict) -> tuple:
    return (
        _relationship_penalty(story_input),
        -int(story_input.get("rank_score", 0)),
        int(story_input.get("rank", 999999)),
    )


def _relationship_penalty(story_input: dict) -> int:
    relationships = {
        _record_source_relationship(record)
        for record in story_input.get("selected_supporting_records", [])
    }
    if "first_party" in relationships:
        return 0
    if "third_party" in relationships or "research" in relationships:
        return 1
    if "channel_or_creator" in relationships:
        return 2
    if "hosted_vendor_post" in relationships:
        return 3
    if "community" in relationships:
        return 4
    return 5


def _record_source_relationship(record: dict) -> str:
    existing = clean_text(record.get("source_relationship", ""))
    if existing:
        return existing
    source_group = clean_text(record.get("source_group", ""))
    if source_group == "tech_news_apis":
        return "third_party"
    if source_group == "research_papers":
        return "research"
    if source_group == "youtube_podcast_transcripts":
        return "channel_or_creator"
    if source_group == "community_signals":
        return "community"
    if source_group == "ai_company_blogs":
        return "first_party"
    return "unknown"
