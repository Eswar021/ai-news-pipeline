from __future__ import annotations

import re

from src.pipeline.L1_collection.common import clean_text


PROCEDURAL_PATTERNS = [
    r"\bchoose\b",
    r"\bclick\b",
    r"\bnavigate\b",
    r"\bselect\b",
    r"\breturn to\b",
    r"\bgo to\b",
    r"\bopen the\b",
    r"\badd the\b",
    r"\bconfigure\b",
    r"\binstall\b",
    r"\brun\s+(uv|pip|npm|python|docker|git|curl)\b",
    r"\bdelete the\b",
    r"\bcheckbox\b",
    r"\bdrop[- ]?down\b",
    r"\bdialog\b",
    r"\bfor this walkthrough\b",
    r"\bto get started\b",
    r"\bbefore you begin\b",
    r"\bprerequisites?\b",
    r"\badministrative access\b",
    r"\bdefault network mode\b",
    r"\brequired before\b",
]
META_PATTERNS = [
    r"\bweekend editor\b",
    r"\bauthor\b",
    r"\bbyline\b",
    r"\bfollow\b",
    r"\bupvote\b",
    r"\bcomment count\b",
    r"\bback to articles\b",
    r"\barticle published\b",
    r"\bannouncement was published\b",
    r"\bwas published on\b",
    r"\bpublished on\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{4})\b",
    r"\bguest post is co-written\b",
    r"\bcompany size:\b",
]
CODE_CONFIG_PATTERNS = [
    r"\.ya?ml\b",
    r"\buser_prompt\b",
    r"\bsystem_prompt\b",
    r"\b--[a-z0-9_-]+\b",
    r"\bapi scopes?\b",
    r"\bcallback url\b",
    r"\boauth\b",
]
LOW_VALUE_PATTERNS = [
    r"\bshows? (a|the)? ?connected status\b",
    r"\bshows? not signed in\b",
    r"\bpage shows\b",
    r"\bcard shows\b",
    r"\bsection shows\b",
    r"\bbutton labeled\b",
    r"\bdownload button\b",
    r"\bdownload page\b",
    r"\bclick download\b",
    r"\bjensen huang spoke at\b",
    r"\bcan write code\b",
    r"\bai can help search, suggest, and verify\b",
    r"\bcan help search, suggest, and verify\b",
    r"\bcan help search\b.*\bsuggest\b.*\bverify\b",
    r"\bcan also revise generated tokens\b",
    r"\bto begin using\b",
    r"\bcomplete the following steps\b",
    r"\busers? can try\b",
    r"\bavailable for download\b",
]

KEEP_TYPES = {
    "event_fact",
    "timeline_fact",
    "product_fact",
    "model_capability",
    "feature_claim",
    "benchmark_claim",
    "research_claim",
    "business_claim",
    "partnership_claim",
    "pricing_claim",
    "quote_claim",
    "statistic_claim",
    "limitation_claim",
    "risk_claim",
    "interpretive_claim",
    "prediction_claim",
}


def filter_story_facts(story_with_provenance: dict) -> dict:
    filtered_sets: list[dict] = []
    discard_counts: dict[str, int] = {}

    for record_set in story_with_provenance["record_fact_sets"]:
        filtered_facts: list[dict] = []
        for fact in record_set["facts"]:
            reason = _discard_reason(fact, record_set["record"])
            if reason:
                fact = {
                    **fact,
                    "force_discard_reason": reason,
                    "usefulness_status": "discard",
                    "usefulness_score": 0,
                }
                discard_counts[reason] = discard_counts.get(reason, 0) + 1
            else:
                fact = {
                    **fact,
                    "usefulness_status": "keep",
                    "usefulness_score": _usefulness_score(fact),
                }
            filtered_facts.append(fact)
        filtered_sets.append({**record_set, "facts": filtered_facts})

    return {
        **story_with_provenance,
        "record_fact_sets": filtered_sets,
        "filter_discard_counts": discard_counts,
    }


def _discard_reason(fact: dict, record: dict) -> str | None:
    text = clean_text(fact.get("fact_text", ""))
    anchor = clean_text(fact.get("quote_anchor", ""))
    combined = f"{text} {anchor}".lower()

    if _record_has_suspicious_content(record):
        return "suspicious_record_content"
    if not fact.get("support_records"):
        return "unresolved_anchor"
    if len(text) < 25:
        return "too_short"
    if fact.get("fact_type") not in KEEP_TYPES:
        return "low_value_fact_type"
    if _matches(combined, META_PATTERNS):
        return "metadata_or_article_chrome"
    if _matches(combined, LOW_VALUE_PATTERNS):
        return "low_value_detail"
    if _matches(combined, CODE_CONFIG_PATTERNS):
        return "code_or_config_detail"
    if _matches(combined, PROCEDURAL_PATTERNS):
        return "procedural_instruction"
    if fact.get("fact_type") == "prediction_claim" and not _is_concrete_prediction(text):
        return "low_value_prediction_claim"
    if fact.get("fact_type") == "interpretive_claim" and not _is_source_grounded_significance(text):
        return "low_value_interpretive_claim"
    return None


def _record_has_suspicious_content(record: dict) -> bool:
    if record.get("content_integrity_status") in {"wrong_article", "title_mismatch", "too_short"}:
        return True
    if record.get("source_group") == "ai_company_blogs" and len(clean_text(record.get("content", ""))) < 700:
        return True
    return False


def _usefulness_score(fact: dict) -> int:
    text = clean_text(fact.get("fact_text", "")).lower()
    fact_type = fact.get("fact_type", "")
    score = 0

    if fact_type in {"event_fact", "timeline_fact", "partnership_claim", "pricing_claim"}:
        score += 4
    elif fact_type in {"product_fact", "model_capability", "benchmark_claim", "research_claim", "business_claim", "prediction_claim"}:
        score += 3
    elif fact_type in {"feature_claim", "limitation_claim", "risk_claim", "statistic_claim", "quote_claim", "interpretive_claim"}:
        score += 2

    if re.search(r"\b\d+(\.\d+)?%?\b", text):
        score += 2
    if fact_type == "prediction_claim" and _is_concrete_prediction(text):
        score += 2
    if fact_type == "interpretive_claim" and _has_significance_marker(text):
        score += 1
    if re.search(r"\b(launch|announce|partner|release|available|roll out|benchmark|risk|limitation)\b", text):
        score += 2
    if len(text) > 220:
        score -= 1
    return score


def _is_concrete_prediction(text: str) -> bool:
    lowered = clean_text(text).lower()
    if re.search(r"[$€£]\s?\d", lowered):
        return True
    if re.search(r"\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|trillion|bn|m|t)\b", lowered):
        return True
    if re.search(r"\b20\d{2}\b", lowered):
        return True
    return bool(
        re.search(r"\b(projected|forecast|expected|estimated|predict|could reach|will reach)\b", lowered)
        and len(lowered) >= 80
    )


def _is_source_grounded_significance(text: str) -> bool:
    lowered = clean_text(text).lower()
    if len(lowered) < 70:
        return False
    return _has_significance_marker(lowered)


def _has_significance_marker(text: str) -> bool:
    return bool(
        re.search(
            r"\b(first time|milestone|breakthrough|demonstrates|shows|suggests|enables|could change|"
            r"impact|implication|significant|accelerate|influence|adoption|enterprise|workflow|"
            r"research|safety|security|competition|limitation|risk)\b",
            clean_text(text).lower(),
        )
    )


def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
