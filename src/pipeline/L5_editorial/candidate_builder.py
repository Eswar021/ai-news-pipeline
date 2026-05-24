from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

from src.pipeline.L1_collection.common import clean_text


VALUABLE_FACT_TYPES = {
    "benchmark_claim",
    "business_claim",
    "limitation_claim",
    "model_capability",
    "partnership_claim",
    "prediction_claim",
    "pricing_claim",
    "product_fact",
    "research_claim",
    "risk_claim",
    "statistic_claim",
}


def build_candidates(fact_packets: list[dict], layer5_cfg: dict) -> list[dict]:
    limit = int(layer5_cfg["candidate_limit"])
    ranked_packets = sorted(fact_packets, key=lambda packet: int(packet.get("rank", 999999)))

    candidates: list[dict] = []
    for packet in ranked_packets[:limit]:
        candidates.append(_build_candidate(packet))
    return candidates


def compact_candidate_evaluation(candidate: dict) -> dict:
    keys = [
        "story_id",
        "story_title",
        "rank",
        "readiness",
        "story_type_hint",
        "editorial_value",
        "source_groups",
        "source_relationship_counts",
        "evidence_counts",
        "viewer_value",
        "score_components",
        "opportunity_score",
        "deep_dive_eligible",
        "roundup_eligible",
        "segment_role",
        "target_seconds",
        "role_reason",
        "selected",
        "rejection_reasons",
    ]
    return {key: candidate.get(key) for key in keys}


def _build_candidate(packet: dict) -> dict:
    identity = packet.get("story_identity") or {}
    evidence_summary = packet.get("evidence_summary") or {}
    source_group_counts = _source_group_counts(packet)
    fact_type_counts = Counter(
        fact.get("fact_type", "unknown")
        for fact in packet.get("safe_facts", []) + packet.get("cautious_facts", [])
    )

    safe_count = len(packet.get("safe_facts", []))
    cautious_count = len(packet.get("cautious_facts", []))
    selected_records = packet.get("selected_supporting_records", [])
    source_relationship_counts = Counter(_source_relationship(record) for record in selected_records)
    community_only = bool(selected_records) and all(
        record.get("source_group") == "community_signals" for record in selected_records
    )

    return {
        "story_id": packet["story_id"],
        "story_title": packet["story_title"],
        "rank": int(packet.get("rank", 999999)),
        "readiness": packet.get("readiness", "insufficient"),
        "story_type_hint": packet.get("story_type_hint", "mixed_story"),
        "story_identity": identity,
        "editorial_value": identity.get("editorial_value", "unknown"),
        "is_noise": bool(identity.get("is_noise")),
        "is_tutorial": bool(identity.get("is_tutorial")),
        "is_event_update": bool(identity.get("is_event_update")),
        "source_groups": list(packet.get("source_groups", [])),
        "source_group_counts": source_group_counts,
        "source_relationship_counts": dict(source_relationship_counts),
        "hosted_vendor_record_count": source_relationship_counts.get("hosted_vendor_post", 0),
        "community_only": community_only,
        "safe_fact_count": safe_count,
        "cautious_fact_count": cautious_count,
        "usable_fact_count": safe_count + cautious_count,
        "valuable_fact_count": sum(count for fact_type, count in fact_type_counts.items() if fact_type in VALUABLE_FACT_TYPES),
        "evidence_counts": {
            "selected_record_count": evidence_summary.get("selected_record_count", len(selected_records)),
            "safe_fact_count": safe_count,
            "cautious_fact_count": cautious_count,
            "discarded_fact_count": len(packet.get("discarded_facts", [])),
            "official_record_count": evidence_summary.get("official_record_count", source_group_counts.get("ai_company_blogs", 0)),
            "news_record_count": evidence_summary.get("news_record_count", source_group_counts.get("tech_news_apis", 0)),
            "research_record_count": evidence_summary.get("research_record_count", source_group_counts.get("research_papers", 0)),
            "youtube_record_count": evidence_summary.get("youtube_record_count", source_group_counts.get("youtube_podcast_transcripts", 0)),
            "community_record_count": evidence_summary.get("community_record_count", source_group_counts.get("community_signals", 0)),
            "valuable_fact_count": sum(count for fact_type, count in fact_type_counts.items() if fact_type in VALUABLE_FACT_TYPES),
            "hosted_vendor_record_count": source_relationship_counts.get("hosted_vendor_post", 0),
            "first_party_record_count": source_relationship_counts.get("first_party", 0),
        },
        "viewer_value": {},
        "score_components": {},
        "opportunity_score": 0.0,
        "deep_dive_eligible": False,
        "roundup_eligible": False,
        "segment_role": "",
        "target_seconds": 0,
        "role_reason": "",
        "selected": False,
        "rejection_reasons": [],
        "fact_packet": packet,
    }


def _source_group_counts(packet: dict) -> dict[str, int]:
    records = packet.get("selected_supporting_records", [])
    if records:
        return dict(Counter(record.get("source_group", "unknown") for record in records))
    return dict(Counter(packet.get("source_groups", [])))


def _source_relationship(record: dict) -> str:
    existing = clean_text(record.get("source_relationship", ""))
    if existing:
        return existing

    url = clean_text(record.get("url", ""))
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    if host == "huggingface.co" and len(path_parts) >= 3 and path_parts[0] == "blog":
        return "hosted_vendor_post"
    return "first_party"
