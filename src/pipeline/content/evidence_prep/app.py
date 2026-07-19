from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .config import DROP_QUERY_KEYS
from .contract import EvidencePrepRequest, EvidencePrepResponse, EvidencePrepStatus
from .utils import (
    clean_article_content,
    clean_text,
    normalize_content,
    parse_datetime,
    within_window,
)


IST = timezone(timedelta(hours=5, minutes=30))


def run(input_json: dict) -> dict:
    request = EvidencePrepRequest.model_validate(input_json)
    run_id = request.run.run_id
    records = request.input.news_collection.data.records
    window = request.config.collection_window.model_dump(mode="json")
    content_cleaning_config = request.config.content_cleaning.model_dump(mode="json")

    prepared_records: list[dict] = []
    decision_ledger: list[dict] = []
    dedup_index: dict[str, str] = {}
    content_status_counts = {"full": 0, "partial": 0, "title_only": 0}
    exclude_reason_counts: dict[str, int] = {}
    source_group_counts: dict[str, dict[str, int]] = {}
    excluded_records: list[dict] = []

    duplicate_count = 0
    excluded_count = 0

    for record in records:
        prepared, exclusion = _prepare_record(
            record,
            dedup_index,
            window,
            content_cleaning_config=content_cleaning_config,
        )

        group_name = clean_text(record.get("source_group", "")) or "unknown"
        group_summary = source_group_counts.setdefault(
            group_name,
            {
                "input": 0,
                "candidates": 0,
                "prepared": 0,
                "flagged": 0,
                "duplicates": 0,
                "excluded": 0,
            },
        )
        group_summary["input"] += 1

        if prepared is not None:
            prepared_records.append(prepared)
            group_summary["candidates"] += 1
            group_summary["prepared"] += 1
            reason_codes = list(prepared.get("preparation_warnings", []))
            decision_ledger.append(_build_decision(prepared, "candidate", reason_codes))
            if reason_codes:
                group_summary["flagged"] += 1
            status = prepared["content_status"]
            content_status_counts[status] = content_status_counts.get(status, 0) + 1
            continue

        if exclusion is None:
            continue
        excluded_count += 1
        group_summary["excluded"] += 1
        reason = exclusion["exclude_reason"] or "excluded"
        exclude_reason_counts[reason] = exclude_reason_counts.get(reason, 0) + 1
        excluded_records.append(exclusion)
        decision_ledger.append(
            {
                "record_id": exclusion.get("record_id", ""),
                "record_key": "",
                "source_group": exclusion.get("source_group", ""),
                "source": exclusion.get("source", ""),
                "title": exclusion.get("title", ""),
                "decision": "duplicate" if exclusion["is_duplicate"] else "hard_reject",
                "reason_codes": [reason],
                "decision_owner": "code",
            }
        )
        if exclusion["is_duplicate"]:
            duplicate_count += 1
            group_summary["duplicates"] += 1

    output_records = [
        {key: value for key, value in record.items() if key != "record_id"}
        for record in prepared_records
    ]
    generated_at = _iso_now()
    response_status = _overall_status(len(records), len(output_records))
    content_cleaning_summary = _content_cleaning_summary(prepared_records, content_cleaning_config)
    source_relationship_counts = _source_relationship_counts(prepared_records)
    decision_counts: dict[str, int] = {}
    for item in decision_ledger:
        decision = clean_text(item.get("decision")) or "unknown"
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
    quality_flag_counts = _quality_flag_counts(prepared_records)
    preparation_warning_counts = _preparation_warning_counts(prepared_records)

    response = EvidencePrepResponse(
        status=response_status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "record_count": len(output_records),
            "records": output_records,
            "decision_count": len(decision_ledger),
            "decision_ledger": decision_ledger,
        },
        summary={
            "run_id": run_id,
            "generated_at": generated_at,
            "status": response_status,
            "input_record_count": len(records),
            "prepared_record_count": len(output_records),
            "excluded_count": excluded_count,
            "duplicate_count": duplicate_count,
            "decision_counts": decision_counts,
            "quality_flag_counts": quality_flag_counts,
            "preparation_warning_counts": preparation_warning_counts,
            "content_status_counts": content_status_counts,
            "exclude_reason_counts": exclude_reason_counts,
            "source_groups": source_group_counts,
            "source_relationship_counts": source_relationship_counts,
            "content_cleaning": content_cleaning_summary,
            "excluded_records": excluded_records,
        },
        handoff={
            "record_count": len(output_records),
            "ready_for_editorial_triage": response_status == "ok" and len(output_records) > 0,
        },
    )
    return response.model_dump(mode="json")


def _overall_status(
    input_count: int,
    prepared_count: int,
) -> EvidencePrepStatus:
    if input_count == 0 or prepared_count == 0:
        return "failed"
    return "ok"


def _prepare_record(
    record: dict,
    dedup_index: dict[str, str],
    window: dict,
    *,
    content_cleaning_config: dict,
) -> tuple[dict | None, dict | None]:
    record_id = clean_text(record.get("record_id", ""))
    normalized_title = clean_text(record.get("title", ""))
    canonical_url = _canonicalize_url(record.get("url", ""))
    fallback_content = record.get("description", "") or record.get("summary", "") or normalized_title
    raw_source_content = str(record.get("content", "") or fallback_content or "")
    normalized_raw_content, content_status = normalize_content(
        record.get("content", ""),
        fallback=fallback_content,
    )
    normalized_content, content_cleaning = clean_article_content(
        normalized_raw_content,
        url=canonical_url,
        config=content_cleaning_config,
    )
    normalized_content, content_status = normalize_content(
        normalized_content,
        fallback=record.get("description", "") or record.get("summary", "") or normalized_title,
    )
    non_text_payload_detected = bool(content_cleaning.get("non_text_payload_detected"))
    prepared_raw_content = "" if non_text_payload_detected else raw_source_content
    published_at_iso = _normalize_published_at(record.get("published_at"))

    hard_reject_reason = None
    is_duplicate = False
    canonical_record_id = record_id
    preparation_warnings: list[str] = []
    incoming_quality_flags = record.get("quality_flags") or {}
    quality_flags = (
        dict(incoming_quality_flags) if isinstance(incoming_quality_flags, dict) else {}
    )
    if non_text_payload_detected:
        preparation_warnings.append("non_text_source_payload")
        quality_flags["non_text_source_payload"] = content_cleaning.get(
            "non_text_payload_kind", "unknown"
        )

    if not published_at_iso:
        preparation_warnings.append("missing_published_at")
        quality_flags["published_at_missing"] = True
    elif not within_window(published_at_iso, window["start"], window["end"]):
        hard_reject_reason = "outside_manifest_window"
    if not normalized_title and not normalized_content:
        hard_reject_reason = hard_reject_reason or "empty_record"

    if content_cleaning.get("modified"):
        quality_flags["content_cleaned"] = True

    dedup_key, dedup_reason = _build_dedup_key(
        record=record,
        canonical_url=canonical_url,
        normalized_title=normalized_title,
        published_at_iso=published_at_iso,
    )
    if hard_reject_reason is None and dedup_key:
        if dedup_key in dedup_index:
            is_duplicate = True
            canonical_record_id = dedup_index[dedup_key]
            hard_reject_reason = dedup_reason
        else:
            dedup_index[dedup_key] = record_id

    if hard_reject_reason is not None:
        return None, {
            "record_id": record_id,
            "source_group": clean_text(record.get("source_group", "")),
            "source": clean_text(record.get("source", "")),
            "title": normalized_title,
            "exclude_reason": hard_reject_reason,
            "is_duplicate": is_duplicate,
            "canonical_record_id": canonical_record_id,
            "content_status": content_status,
            "published_at": published_at_iso or clean_text(record.get("published_at", "")),
        }

    prepared = _build_prepared_record(
        record=record,
        normalized_title=normalized_title,
        raw_content=prepared_raw_content,
        normalized_content=normalized_content,
        published_at_iso=published_at_iso,
        canonical_url=canonical_url,
        content_status=content_status,
        content_cleaning=content_cleaning,
        quality_flags=quality_flags,
        preparation_warnings=preparation_warnings,
    )
    return prepared, None


def _normalize_published_at(value: str | None) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return ""
    return parsed.isoformat()


def _build_prepared_record(
    *,
    record: dict,
    normalized_title: str,
    raw_content: str,
    normalized_content: str,
    published_at_iso: str,
    canonical_url: str,
    content_status: str,
    content_cleaning: dict,
    quality_flags: dict,
    preparation_warnings: list[str],
) -> dict:
    metadata = record.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    prepared = {
        "record_key": _build_record_key(
            source=record.get("source", ""),
            url=canonical_url,
            title=normalized_title,
            published_at=published_at_iso,
        ),
        "record_id": clean_text(record.get("record_id", "")),
        "source": clean_text(record.get("source", "")),
        "source_group": clean_text(record.get("source_group", "")),
        "source_type": clean_text(record.get("source_type", "")),
        "title": normalized_title,
        "url": canonical_url,
        "published_at": published_at_iso,
        "content": normalized_content,
        "raw_content": raw_content,
        "cleaned_content": normalized_content,
        "content_status": content_status,
        "source_relationship": _source_relationship(record),
        "quality_flags": quality_flags,
        "preparation_warnings": list(dict.fromkeys(preparation_warnings)),
    }
    if content_cleaning.get("modified"):
        prepared["content_cleaning"] = content_cleaning

    optional_keys = [
        "collector",
        "source_name",
        "trust_tier",
        "author",
        "description",
        "summary",
        "provider",
        "category",
        "authors",
        "channel_name",
        "channel_id",
        "video_id",
        "hn_discussion_url",
        "score",
        "comment_count",
        "mode",
        "language",
        "stars",
        "forks",
        "topics",
        "content_source",
        "hosted_author_or_org",
        "transcript_status",
        "candidate_key",
    ]
    for key in optional_keys:
        value = record.get(key, metadata.get(key))
        if value is None:
            continue
        if isinstance(value, str):
            value = clean_text(value)
        if value == "" or value == []:
            continue
        prepared[key] = value

    return prepared


def _source_relationship(record: dict) -> str:
    existing = clean_text(record.get("source_relationship", ""))
    if existing:
        return existing

    source_group = clean_text(record.get("source_group", ""))
    if source_group == "ai_company_blogs":
        return "first_party"
    if source_group == "tech_news_apis":
        return "third_party"
    if source_group == "research_papers":
        return "research"
    if source_group == "youtube_podcast_transcripts":
        return "channel_or_creator"
    if source_group == "community_signals":
        return "community"
    return "unknown"


def _content_cleaning_summary(records: list[dict], config: dict) -> dict:
    details = [record.get("content_cleaning") for record in records if isinstance(record.get("content_cleaning"), dict)]
    rule_counts: dict[str, int] = {}
    for detail in details:
        rule = clean_text(detail.get("applied_rule")) or "unknown"
        rule_counts[rule] = rule_counts.get(rule, 0) + 1
    return {
        "enabled": bool(config.get("enabled", True)),
        "configured_rule_count": len(config.get("rules", [])),
        "modified_record_count": len(details),
        "removed_char_count": sum(int(detail.get("removed_chars", 0)) for detail in details),
        "applied_rule_counts": rule_counts,
    }


def _source_relationship_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        relationship = clean_text(record.get("source_relationship")) or "unknown"
        counts[relationship] = counts.get(relationship, 0) + 1
    return counts


def _quality_flag_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        flags = record.get("quality_flags") or {}
        if not isinstance(flags, dict):
            continue
        for name, value in flags.items():
            if value is False or value is None or value == "" or value == []:
                continue
            counts[name] = counts.get(name, 0) + 1
    return counts


def _preparation_warning_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for warning in record.get("preparation_warnings") or []:
            name = clean_text(warning)
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


def _build_decision(record: dict, decision: str, reason_codes: list[str]) -> dict:
    return {
        "record_id": clean_text(record.get("record_id", "")),
        "record_key": clean_text(record.get("record_key", "")),
        "source_group": clean_text(record.get("source_group", "")),
        "source": clean_text(record.get("source", "")),
        "title": clean_text(record.get("title", "")),
        "decision": decision,
        "reason_codes": list(dict.fromkeys(clean_text(item) for item in reason_codes if clean_text(item))),
        "decision_owner": "code",
    }


def _build_record_key(*, source: str, url: str, title: str, published_at: str) -> str:
    basis = "|".join(
        [
            clean_text(source).lower(),
            clean_text(url).lower(),
            clean_text(title).lower(),
            clean_text(published_at).lower(),
        ]
    )
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"record_{digest}"


def _build_dedup_key(
    *,
    record: dict,
    canonical_url: str,
    normalized_title: str,
    published_at_iso: str,
) -> tuple[str | None, str | None]:
    if record.get("video_id"):
        return f"video:{record['video_id']}", "duplicate_video_id"

    arxiv_id = _extract_arxiv_id(canonical_url)
    if arxiv_id:
        return f"arxiv:{arxiv_id}", "duplicate_arxiv_id"

    if canonical_url:
        return f"url:{canonical_url}", "duplicate_url"

    day = published_at_iso[:10] if published_at_iso else ""
    source_group = record.get("source_group", "")
    if normalized_title and day and source_group:
        return f"title:{source_group}:{day}:{normalized_title.lower()}", "duplicate_title_same_day"

    return None, None


def _canonicalize_url(value: str) -> str:
    raw = clean_text(value)
    if not raw:
        return ""

    try:
        parsed = urlparse(raw)
    except Exception:
        return raw

    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path or ""
    if path != "/":
        path = path.rstrip("/")

    query_pairs = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in DROP_QUERY_KEYS
    ]
    query = urlencode(query_pairs, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def _extract_arxiv_id(canonical_url: str) -> str:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", canonical_url, re.IGNORECASE)
    if not match:
        return ""
    value = match.group(1)
    return value.removesuffix(".pdf")


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
