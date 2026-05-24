from __future__ import annotations

import hashlib
import re


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}
MERGE_THRESHOLD = 0.72


def verify_story_facts(story_with_provenance: dict) -> dict:
    merged_facts = _merge_story_facts(story_with_provenance["record_fact_sets"])
    classified = [_classify_fact(fact) for fact in merged_facts]
    return {
        **story_with_provenance,
        "merged_facts": classified,
    }


def _merge_story_facts(record_fact_sets: list[dict]) -> list[dict]:
    merged: list[dict] = []
    token_sets: list[frozenset[str]] = []

    for record_set in record_fact_sets:
        for fact in record_set["facts"]:
            fact_tokens = _tokens(fact["fact_text"])
            merged_into_existing = False
            for index, existing in enumerate(merged):
                if existing["fact_type"] != fact["fact_type"]:
                    continue
                if _jaccard(token_sets[index], fact_tokens) < MERGE_THRESHOLD:
                    continue

                existing["support_records"].extend(fact["support_records"])
                existing["support_levels"].append(fact["support_level"])
                existing["record_keys"].add(fact["record_key"])
                if fact.get("force_discard_reason"):
                    existing["discard_reasons"].add(fact["force_discard_reason"])
                else:
                    existing["kept_candidate_count"] += 1
                existing["usefulness_score"] = max(
                    existing.get("usefulness_score", 0),
                    fact.get("usefulness_score", 0),
                )
                if len(fact["fact_text"]) > len(existing["fact_text"]):
                    existing["fact_text"] = fact["fact_text"]
                if _support_rank(fact["support_level"]) > _support_rank(existing["primary_support_level"]):
                    existing["primary_support_level"] = fact["support_level"]
                merged_into_existing = True
                break

            if not merged_into_existing:
                merged.append(
                    {
                        "fact_text": fact["fact_text"],
                        "fact_type": fact["fact_type"],
                        "primary_support_level": fact["support_level"],
                        "support_levels": [fact["support_level"]],
                        "support_records": list(fact["support_records"]),
                        "record_keys": {fact["record_key"]},
                        "discard_reasons": (
                            {fact["force_discard_reason"]} if fact.get("force_discard_reason") else set()
                        ),
                        "kept_candidate_count": 0 if fact.get("force_discard_reason") else 1,
                        "usefulness_score": fact.get("usefulness_score", 0),
                    }
                )
                token_sets.append(fact_tokens)

    for fact in merged:
        fact["support_records"] = _deduplicate_support_records(fact["support_records"])
        fact["record_keys"] = sorted(fact["record_keys"])
        fact["support_count"] = len(fact["support_records"])
        if fact["kept_candidate_count"] == 0 and fact["discard_reasons"]:
            fact["force_discard_reason"] = sorted(fact["discard_reasons"])[0]
        fact["discard_reasons"] = sorted(fact["discard_reasons"])
    return merged


def _classify_fact(fact: dict) -> dict:
    support_records = fact["support_records"]
    fact_id = _fact_id(fact["fact_text"], fact["fact_type"])

    forced_discard = fact.get("force_discard_reason")
    if forced_discard:
        return {
            **fact,
            "fact_id": fact_id,
            "status": "discarded",
            "confidence": "none",
            "discard_reason": forced_discard,
        }

    if not support_records:
        return {
            **fact,
            "fact_id": fact_id,
            "status": "discarded",
            "confidence": "none",
            "discard_reason": "unresolved_anchor",
        }

    support_groups = {record["source_group"] for record in support_records}
    direct_support = sum(1 for record in support_records if record["support_level"] == "direct")
    official_direct = any(
        record["source_group"] == "ai_company_blogs"
        and float(record.get("trust_tier", 9) or 9) <= 1.5
        and record.get("source_relationship") != "hosted_vendor_post"
        and record["support_level"] == "direct"
        for record in support_records
    )
    noncommunity = [record for record in support_records if record["source_group"] != "community_signals"]
    corroborated_noncommunity = _is_corroborated_noncommunity(noncommunity)
    community_only = bool(support_groups) and support_groups == {"community_signals"}

    if official_direct:
        status = "safe"
        confidence = "high"
    elif direct_support >= 1 and corroborated_noncommunity:
        status = "safe"
        confidence = "medium"
    elif community_only:
        status = "cautious"
        confidence = "low"
    elif noncommunity:
        status = "cautious"
        confidence = "medium" if direct_support >= 1 else "low"
    else:
        status = "discarded"
        confidence = "none"

    result = {
        **fact,
        "fact_id": fact_id,
        "status": status,
        "confidence": confidence,
    }
    if status == "discarded":
        result["discard_reason"] = "insufficient_support"
    return result


def _is_corroborated_noncommunity(noncommunity_support_records: list[dict]) -> bool:
    if len(noncommunity_support_records) < 2:
        return False
    unique_sources = {
        (
            record.get("source_name", ""),
            record.get("source_url", ""),
        )
        for record in noncommunity_support_records
    }
    return len(unique_sources) >= 2


def _deduplicate_support_records(support_records: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for record in support_records:
        key = (
            record.get("record_key", ""),
            record.get("quote_anchor", ""),
            record.get("paragraph_index", -1),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _tokens(text: str) -> frozenset[str]:
    values = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(value for value in values if value not in STOPWORDS)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _support_rank(level: str) -> int:
    return {
        "partial": 0,
        "indirect": 1,
        "direct": 2,
    }.get(level, 0)


def _fact_id(fact_text: str, fact_type: str) -> str:
    basis = f"{fact_type}|{fact_text}"
    return f"fact_{hashlib.sha1(basis.encode('utf-8')).hexdigest()[:12]}"
