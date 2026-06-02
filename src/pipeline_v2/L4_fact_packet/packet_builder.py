from __future__ import annotations

from collections import Counter


def build_fact_packet(story_verified: dict, *, max_facts_per_story: int) -> dict:
    classified = sorted(story_verified["merged_facts"], key=_fact_sort_key)
    kept = classified[:max_facts_per_story]

    safe_facts = [_serialize_fact(fact) for fact in kept if fact["status"] == "safe"]
    cautious_facts = [_serialize_fact(fact) for fact in kept if fact["status"] == "cautious"]
    discarded_facts = [_serialize_fact(fact) for fact in classified if fact["status"] == "discarded"]

    selected_records = story_verified["selected_supporting_records"]
    source_group_counts = Counter(record.get("source_group", "unknown") for record in selected_records)

    return {
        "story_id": story_verified["story_id"],
        "story_title": story_verified["story_title"],
        "story_type_hint": story_verified["story_type_hint"],
        "story_identity": story_verified.get("story_identity", {}),
        "rank": story_verified["rank"],
        "priority_bucket": story_verified["priority_bucket"],
        "source_groups": story_verified["source_groups"],
        "story_signals": story_verified["story_signals"],
        "selected_supporting_records": selected_records,
        "safe_facts": safe_facts,
        "cautious_facts": cautious_facts,
        "discarded_facts": discarded_facts,
        "evidence_summary": {
            "selected_record_count": len(selected_records),
            "official_record_count": source_group_counts.get("ai_company_blogs", 0),
            "news_record_count": source_group_counts.get("tech_news_apis", 0),
            "research_record_count": source_group_counts.get("research_papers", 0),
            "youtube_record_count": source_group_counts.get("youtube_podcast_transcripts", 0),
            "community_record_count": source_group_counts.get("community_signals", 0),
            "extracted_fact_count": story_verified["raw_fact_count"],
            "safe_fact_count": len(safe_facts),
            "cautious_fact_count": len(cautious_facts),
            "discarded_fact_count": len(discarded_facts),
            "filter_discard_counts": story_verified.get("filter_discard_counts", {}),
        },
        "readiness": _readiness(story_verified, safe_facts, cautious_facts),
    }


def _serialize_fact(fact: dict) -> dict:
    payload = {
        "fact_id": fact["fact_id"],
        "fact_text": fact["fact_text"],
        "fact_type": fact["fact_type"],
        "status": fact["status"],
        "confidence": fact["confidence"],
        "support_records": fact["support_records"],
    }
    if "usefulness_score" in fact:
        payload["usefulness_score"] = fact["usefulness_score"]
    if fact["status"] == "discarded":
        payload["discard_reason"] = fact.get("discard_reason", "discarded")
    return payload


def _readiness(story_verified: dict, safe_facts: list[dict], cautious_facts: list[dict]) -> str:
    official_count = sum(
        1 for record in story_verified["selected_supporting_records"]
        if record.get("source_group") == "ai_company_blogs"
    )
    if len(safe_facts) >= 3:
        return "ready"
    if len(safe_facts) >= 2 and official_count >= 1:
        return "ready"
    if len(safe_facts) + len(cautious_facts) >= 3:
        return "caution"
    return "insufficient"


def _fact_sort_key(fact: dict) -> tuple:
    status_rank = {
        "safe": 0,
        "cautious": 1,
        "discarded": 2,
    }.get(fact["status"], 9)
    confidence_rank = {
        "high": 0,
        "medium": 1,
        "low": 2,
        "none": 3,
    }.get(fact["confidence"], 9)
    return (
        status_rank,
        confidence_rank,
        -fact.get("usefulness_score", 0),
        -len(fact.get("support_records", [])),
        len(fact.get("fact_text", "")),
    )
