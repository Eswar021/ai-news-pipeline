from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .config import (
    AI_RELEVANCE_TERMS,
    CRYPTO_DOMAINS,
    CRYPTO_SOURCE_NAMES,
    CRYPTO_TERMS,
    DROP_QUERY_KEYS,
    FINANCE_NOISE_PATTERNS,
    GENERAL_DEV_PATTERNS,
    GENERIC_SOFTWARE_RELEASE_PATTERNS,
    GENERIC_TITLES,
    LISTING_PATH_PARTS,
    LOW_CONTEXT_CONSUMER_PATTERNS,
    PROMO_OR_DEAL_PATTERNS,
    RESEARCH_PRIORITY_TERMS,
)
from .contract import EvidencePrepRequest, EvidencePrepResponse, EvidencePrepStatus
from .utils import clean_text, normalize_content, parse_datetime, within_window


IST = timezone(timedelta(hours=5, minutes=30))


def run(input_json: dict) -> dict:
    request = EvidencePrepRequest.model_validate(input_json)
    run_id = request.run.run_id
    records = request.input.news_collection.data.records
    window = request.config.collection_window.model_dump(mode="json")
    query_themes = request.config.query_themes
    max_research_papers = request.config.max_research_papers

    prepared_records: list[dict] = []
    dedup_index: dict[str, str] = {}
    content_status_counts = {"full": 0, "partial": 0, "title_only": 0}
    exclude_reason_counts: dict[str, int] = {}
    source_group_counts: dict[str, dict[str, int]] = {}
    excluded_records: list[dict] = []

    duplicate_count = 0
    excluded_count = 0

    for record in records:
        prepared, exclusion = _prepare_record(record, dedup_index, window)

        group_name = clean_text(record.get("source_group", "")) or "unknown"
        group_summary = source_group_counts.setdefault(
            group_name,
            {"input": 0, "prepared": 0, "duplicates": 0, "excluded": 0},
        )
        group_summary["input"] += 1

        if prepared is not None:
            prepared_records.append(prepared)
            group_summary["prepared"] += 1
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
        if exclusion["is_duplicate"]:
            duplicate_count += 1
            group_summary["duplicates"] += 1

    prepared_records, research_exclusions = _rebalance_research_papers(
        prepared_records,
        query_themes,
        max_research_papers,
    )
    for exclusion in research_exclusions:
        excluded_count += 1
        excluded_records.append(exclusion)
        reason = exclusion["exclude_reason"]
        exclude_reason_counts[reason] = exclude_reason_counts.get(reason, 0) + 1
        group_summary = source_group_counts.setdefault(
            "research_papers",
            {"input": 0, "prepared": 0, "duplicates": 0, "excluded": 0},
        )
        group_summary["excluded"] += 1
        group_summary["prepared"] = max(0, group_summary["prepared"] - 1)
        status = exclusion["content_status"]
        content_status_counts[status] = max(0, content_status_counts.get(status, 0) - 1)

    output_records = [
        {key: value for key, value in record.items() if key != "record_id"}
        for record in prepared_records
    ]
    generated_at = _iso_now()
    response_status = _overall_status(len(records), len(output_records))

    response = EvidencePrepResponse(
        status=response_status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "record_count": len(output_records),
            "records": output_records,
        },
        summary={
            "run_id": run_id,
            "generated_at": generated_at,
            "status": response_status,
            "input_record_count": len(records),
            "prepared_record_count": len(output_records),
            "excluded_count": excluded_count,
            "duplicate_count": duplicate_count,
            "content_status_counts": content_status_counts,
            "exclude_reason_counts": exclude_reason_counts,
            "source_groups": source_group_counts,
            "excluded_records": excluded_records,
        },
        handoff={
            "record_count": len(output_records),
            "ready_for_story_mapping": response_status in {"ok", "partial"} and len(output_records) > 0,
        },
    )
    return response.model_dump(mode="json")


def _overall_status(input_count: int, prepared_count: int) -> EvidencePrepStatus:
    if input_count == 0 or prepared_count == 0:
        return "failed"
    return "ok"


def _prepare_record(
    record: dict,
    dedup_index: dict[str, str],
    window: dict,
) -> tuple[dict | None, dict | None]:
    record_id = clean_text(record.get("record_id", ""))
    normalized_title = clean_text(record.get("title", ""))
    normalized_content, content_status = normalize_content(
        record.get("content", ""),
        fallback=record.get("description", "") or record.get("summary", "") or normalized_title,
    )
    published_at_iso = _normalize_published_at(record.get("published_at"))
    canonical_url = _canonicalize_url(record.get("url", ""))

    exclude_reason = None
    is_duplicate = False
    canonical_record_id = record_id

    if not published_at_iso:
        exclude_reason = "missing_published_at"
    elif not within_window(published_at_iso, window["start"], window["end"]):
        exclude_reason = "outside_manifest_window"
    elif not normalized_title and not normalized_content:
        exclude_reason = "empty_record"
    elif _is_listing_record(record, canonical_url, normalized_title):
        exclude_reason = "listing_page"
    elif _is_generic_title(normalized_title):
        exclude_reason = "generic_title"
    else:
        exclude_reason = (
            _official_content_exclusion_reason(record, normalized_title, normalized_content)
            or _topic_exclusion_reason(record, normalized_title, normalized_content, canonical_url)
        )

    dedup_key, dedup_reason = _build_dedup_key(
        record=record,
        canonical_url=canonical_url,
        normalized_title=normalized_title,
        published_at_iso=published_at_iso,
    )
    if exclude_reason is None and dedup_key:
        if dedup_key in dedup_index:
            is_duplicate = True
            canonical_record_id = dedup_index[dedup_key]
            exclude_reason = dedup_reason
        else:
            dedup_index[dedup_key] = record_id

    if exclude_reason is not None:
        return None, {
            "record_id": record_id,
            "source_group": clean_text(record.get("source_group", "")),
            "source": clean_text(record.get("source", "")),
            "title": normalized_title,
            "exclude_reason": exclude_reason,
            "is_duplicate": is_duplicate,
            "canonical_record_id": canonical_record_id,
            "content_status": content_status,
            "published_at": published_at_iso or clean_text(record.get("published_at", "")),
        }

    prepared = _build_prepared_record(
        record=record,
        normalized_title=normalized_title,
        normalized_content=normalized_content,
        published_at_iso=published_at_iso,
        canonical_url=canonical_url,
        content_status=content_status,
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
    normalized_content: str,
    published_at_iso: str,
    canonical_url: str,
    content_status: str,
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
        "content_status": content_status,
        "source_relationship": _source_relationship(record),
    }

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
        "content_integrity_status",
        "content_integrity_reason",
        "content_title_overlap",
        "content_title_coverage",
        "hosted_author_or_org",
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


def _rebalance_research_papers(
    prepared_records: list[dict],
    query_themes: list[str],
    max_research_papers: int,
) -> tuple[list[dict], list[dict]]:
    retained: list[dict] = []
    research: list[tuple[int, dict]] = []
    excluded: list[dict] = []

    for record in prepared_records:
        if record.get("source_group") != "research_papers":
            retained.append(record)
            continue
        score = _score_research_paper(record, query_themes)
        research.append((score, record))

    research.sort(
        key=lambda item: (
            item[0],
            item[1].get("published_at", ""),
        ),
        reverse=True,
    )

    kept_research = 0
    for score, record in research:
        if score <= 0:
            excluded.append(_build_research_exclusion(record, "low_research_relevance"))
            continue
        if kept_research >= max_research_papers:
            excluded.append(_build_research_exclusion(record, "research_overflow"))
            continue
        retained.append(record)
        kept_research += 1

    return retained, excluded


def _score_research_paper(record: dict, query_themes: list[str]) -> int:
    title = clean_text(record.get("title", "")).lower()
    content = clean_text(record.get("content", "")).lower()
    score = 0

    phrases = {clean_text(theme).lower() for theme in query_themes if clean_text(theme)}
    for term in phrases | RESEARCH_PRIORITY_TERMS:
        if not term:
            continue
        if term in title:
            score += 3
        elif term in content:
            score += 1

    if record.get("category") == "cs.AI":
        score += 1
    return score


def _build_research_exclusion(record: dict, reason: str) -> dict:
    return {
        "record_id": clean_text(record.get("record_id", "")),
        "source_group": clean_text(record.get("source_group", "")),
        "source": clean_text(record.get("source", "")),
        "title": clean_text(record.get("title", "")),
        "exclude_reason": reason,
        "is_duplicate": False,
        "canonical_record_id": clean_text(record.get("record_id", "")),
        "content_status": clean_text(record.get("content_status", "")),
        "published_at": clean_text(record.get("published_at", "")),
    }


def _is_listing_record(record: dict, canonical_url: str, normalized_title: str) -> bool:
    if record.get("source_group") != "ai_company_blogs":
        return False
    path = urlparse(canonical_url).path.lower()
    if any(part in path for part in LISTING_PATH_PARTS):
        return True
    return _is_generic_title(normalized_title)


def _is_generic_title(title: str) -> bool:
    cleaned = clean_text(title).lower()
    if cleaned in GENERIC_TITLES:
        return True
    return cleaned.startswith("page ") and len(cleaned.split()) <= 2


def _is_short_official_summary(record: dict, content: str) -> bool:
    if record.get("source_group") != "ai_company_blogs":
        return False
    if record.get("content_source") != "entry_summary":
        return False
    return len(clean_text(content)) < 700


def _official_content_exclusion_reason(record: dict, title: str, content: str) -> str | None:
    if record.get("source_group") != "ai_company_blogs":
        return None

    integrity = clean_text(record.get("content_integrity_status", "")).lower()
    if integrity == "wrong_article":
        return "official_content_wrong_article"
    if integrity == "title_mismatch":
        return "official_content_title_mismatch"

    if _is_short_official_summary(record, content):
        return "official_content_too_short"
    if record.get("content_source") == "article_body" and _official_title_mismatch(title, content):
        return "official_content_title_mismatch"
    if record.get("content_source") == "article_body" and len(clean_text(content)) < 700:
        return "official_content_too_short"
    return None


def _topic_exclusion_reason(record: dict, title: str, content: str, canonical_url: str) -> str | None:
    source_group = record.get("source_group", "")
    if source_group not in {"tech_news_apis", "youtube_podcast_transcripts", "community_signals"}:
        return None

    if _is_crypto_domain_or_source(record, canonical_url):
        return "off_topic_crypto"

    text = _topic_text(record, title, content, canonical_url)
    if _is_crypto_noise(text):
        return "off_topic_crypto"
    if source_group == "tech_news_apis" and _is_finance_noise(title, text):
        return "off_topic_finance"
    if source_group == "tech_news_apis" and _is_promotional_or_deal_noise(title, text):
        return "promotional_or_deal"
    if source_group == "tech_news_apis" and _is_low_context_consumer_noise(title, text):
        return "off_topic_consumer_or_generic_news"
    if source_group in {"tech_news_apis", "youtube_podcast_transcripts"} and _is_generic_software_release(title, text):
        return "generic_software_release"
    if source_group in {"youtube_podcast_transcripts", "community_signals"} and _is_general_dev_noise(title, text):
        return "off_topic_general_dev"
    return None


def _topic_text(record: dict, title: str, content: str, canonical_url: str) -> str:
    topics = record.get("topics", []) or []
    topic_text = " ".join(clean_text(item) for item in topics if isinstance(item, str))
    parts = [
        title,
        canonical_url,
        record.get("description", ""),
        record.get("summary", ""),
        record.get("source_name", ""),
        record.get("channel_name", ""),
        topic_text,
        content[:2500],
    ]
    return clean_text(" ".join(str(part) for part in parts if part)).lower()


def _is_crypto_domain_or_source(record: dict, canonical_url: str) -> bool:
    host = urlparse(canonical_url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if any(host == domain or host.endswith(f".{domain}") for domain in CRYPTO_DOMAINS):
        return True

    source_name = clean_text(record.get("source_name", "")).lower()
    return source_name in CRYPTO_SOURCE_NAMES


def _is_crypto_noise(text: str) -> bool:
    if not any(term in text for term in CRYPTO_TERMS):
        return False
    return any(
        marker in text
        for marker in (
            " price ",
            " price prediction",
            " coin ",
            " token ",
            " market cap",
            " near protocol",
            " surging",
            " new highs",
        )
    )


def _is_generic_software_release(title: str, text: str) -> bool:
    if _has_ai_relevance(title):
        return False
    return any(re.search(pattern, title, re.IGNORECASE) for pattern in GENERIC_SOFTWARE_RELEASE_PATTERNS)


def _is_general_dev_noise(title: str, text: str) -> bool:
    title_matches = any(re.search(pattern, title, re.IGNORECASE) for pattern in GENERAL_DEV_PATTERNS)
    if title_matches and not _has_ai_relevance(title):
        return True
    if _has_ai_relevance(text):
        return False
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in GENERAL_DEV_PATTERNS)


def _is_finance_noise(title: str, text: str) -> bool:
    if _has_ai_relevance(title):
        return False
    return any(re.search(pattern, title, re.IGNORECASE) for pattern in FINANCE_NOISE_PATTERNS)


def _is_promotional_or_deal_noise(title: str, text: str) -> bool:
    if _has_ai_relevance(title):
        return False
    return any(re.search(pattern, title, re.IGNORECASE) for pattern in PROMO_OR_DEAL_PATTERNS)


def _is_low_context_consumer_noise(title: str, text: str) -> bool:
    if _has_ai_relevance(title):
        return False
    return any(re.search(pattern, title, re.IGNORECASE) for pattern in LOW_CONTEXT_CONSUMER_PATTERNS)


def _has_ai_relevance(text: str) -> bool:
    text = clean_text(text).lower()
    for term in AI_RELEVANCE_TERMS:
        if len(term) <= 4 and re.search(rf"\b{re.escape(term)}\b", text):
            return True
        if len(term) > 4 and term in text:
            return True
    return False


def _official_title_mismatch(title: str, content: str) -> bool:
    title_tokens = _important_title_tokens(title)
    if len(title_tokens) < 3:
        return False
    lead_tokens = _important_title_tokens(clean_text(content)[:120])
    if clean_text(title).lower() in clean_text(content).lower()[:500]:
        return False
    overlap = title_tokens & lead_tokens
    coverage = len(overlap) / len(title_tokens)
    return len(overlap) <= 1 or coverage < 0.22


def _important_title_tokens(text: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "with",
        "your",
    }
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", clean_text(text).lower()):
        if len(token) < 3 and token != "ai":
            continue
        if token in stopwords:
            continue
        tokens.add(token)
    return tokens


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
