from __future__ import annotations

import hashlib


def build_source_index(segment_plan: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}

    for segment in segment_plan:
        story_id = segment["story_id"]
        for fact in segment.get("safe_facts", []) + segment.get("cautious_facts", []):
            fact_id = fact["fact_id"]
            for support in fact.get("support_records", []):
                key = _source_key(support)
                if key not in by_key:
                    by_key[key] = _new_source_entry(support)
                entry = by_key[key]
                entry["supported_fact_ids"].add(fact_id)
                entry["used_story_ids"].add(story_id)

    sources = []
    for entry in by_key.values():
        supported_fact_ids = sorted(entry.pop("supported_fact_ids"))
        used_story_ids = sorted(entry.pop("used_story_ids"))
        source = {
            **entry,
            "supported_fact_ids": supported_fact_ids,
            "used_story_ids": used_story_ids,
            "recommended_for_description": _recommended_for_description(entry, supported_fact_ids),
        }
        sources.append(source)

    sources.sort(key=lambda item: (item["trust_tier"], item["source_group"], item["source_name"], item["source_url"]))
    return sources


def _new_source_entry(support: dict) -> dict:
    return {
        "source_ref_id": _source_ref_id(support),
        "record_key": support.get("record_key", ""),
        "source_url": support.get("source_url", ""),
        "source_name": support.get("source_name", ""),
        "source_group": support.get("source_group", ""),
        "source_relationship": support.get("source_relationship", ""),
        "published_at": support.get("published_at", ""),
        "trust_tier": int(support.get("trust_tier", 999) or 999),
        "supported_fact_ids": set(),
        "used_story_ids": set(),
    }


def _recommended_for_description(entry: dict, supported_fact_ids: list[str]) -> bool:
    relationship = entry.get("source_relationship", "")
    source_group = entry.get("source_group", "")
    if relationship == "first_party":
        return True
    if relationship == "research" or source_group == "research_papers":
        return True
    if relationship == "third_party" or source_group == "tech_news_apis":
        return len(supported_fact_ids) >= 2
    return False


def _source_ref_id(support: dict) -> str:
    digest = hashlib.sha1(_source_key(support).encode("utf-8")).hexdigest()[:10]
    return f"source_{digest}"


def _source_key(support: dict) -> str:
    return "|".join(
        [
            str(support.get("record_key", "")),
            str(support.get("source_url", "")),
            str(support.get("source_name", "")),
        ]
    )
