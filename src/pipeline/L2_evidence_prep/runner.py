"""
L2 Evidence Prep — clean, normalize, and soft-deduplicate collected records.

Reads:
    output/{run_id}/run_manifest.json         → runtime contract
    output/{run_id}/L1/raw_records.json       → collected record list

Writes:
    output/{run_id}/L2/prepared_records.json  → cleaned records for downstream story mapping
    output/{run_id}/L2/summary.json           → keep/drop/duplicate counts

LLM: no

Module execution order:
    1. load manifest and L1 records
    2. enforce manifest window and normalize title/content/date/url at record level
    3. soft-flag obvious duplicates
    4. write prepared records and summary

Usage:
    python -m src.pipeline.L2_evidence_prep.runner --run-id run_...
    python -m src.pipeline.L2_evidence_prep.runner --run-id current
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.pipeline.L1_collection.common import clean_text, normalize_content, parse_datetime, within_window


IST = timezone(timedelta(hours=5, minutes=30))
DROP_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "ref",
    "ref_src",
    "feature",
    "fbclid",
    "gclid",
    "si",
}
MAX_RESEARCH_PAPERS = 12
RESEARCH_PRIORITY_TERMS = {
    "ai",
    "artificial intelligence",
    "agent",
    "agents",
    "agentic",
    "llm",
    "large language model",
    "language model",
    "coding",
    "code",
    "developer",
    "copilot",
    "rag",
    "reasoning",
    "memory",
    "benchmark",
    "tool",
    "tools",
    "multimodal",
    "vision-language",
    "diffusion",
    "generative ai",
    "deep research",
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
AI_RELEVANCE_TERMS = {
    "ai",
    "artificial intelligence",
    "agent",
    "agents",
    "agentic",
    "chatgpt",
    "claude",
    "codex",
    "copilot",
    "deepmind",
    "gemini",
    "gpt",
    "llm",
    "machine learning",
    "model",
    "multimodal",
    "openai",
    "rag",
    "robotics",
}
CRYPTO_TERMS = {
    "crypto",
    "coin",
    "token",
    "blockchain",
    "protocol price",
    "price prediction",
    "surging",
    "hit new highs",
    "market cap",
}
CRYPTO_DOMAINS = {
    "beincrypto.com",
    "bitcoin.com",
    "coindesk.com",
    "cointelegraph.com",
    "cryptobriefing.com",
    "decrypt.co",
    "theblock.co",
}
CRYPTO_SOURCE_NAMES = {
    "beincrypto",
    "bitcoin.com",
    "coindesk",
    "cointelegraph",
    "crypto briefing",
    "cryptobriefing",
    "decrypt",
    "the block",
}
GENERIC_SOFTWARE_RELEASE_PATTERNS = [
    r"\bissue\s+\d+:\s+.*\breleased\b",
    r"\bdjango\s+\d+(?:\.\d+)*\b.*\breleased\b",
    r"\bgo\s+\d+(?:\.\d+)*\b.*\breleased\b",
    r"\bnode(?:\.js)?\s+\d+(?:\.\d+)*\b.*\breleased\b",
    r"\bruby\s+\d+(?:\.\d+)*\b.*\breleased\b",
    r"\brails\s+\d+(?:\.\d+)*\b.*\breleased\b",
]
GENERAL_DEV_PATTERNS = [
    r"\bwhat'?s new in go\b",
    r"\bcss\b",
    r"\bdjango\b",
    r"\bjavascript\b",
    r"\bpython package\b",
    r"\bweb framework\b",
]


def run(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    run_id = manifest["run_id"]
    query_themes = manifest["layer_1"]["query_themes"]
    print(f"[L2] Run: {run_id}")
    window = manifest["layer_0"]["collection_window"]
    l1_records = _load_l1_records(run_id)
    print(f"[L2] Input records: {l1_records['record_count']}")

    prepared_records: list[dict] = []
    dedup_index: dict[str, str] = {}
    content_status_counts = {"full": 0, "partial": 0, "title_only": 0}
    exclude_reason_counts: dict[str, int] = {}
    source_group_counts: dict[str, dict[str, int]] = {}
    excluded_records: list[dict] = []

    kept_count = 0
    duplicate_count = 0
    excluded_count = 0

    for record in l1_records["records"]:
        prepared, exclusion = _prepare_record(record, dedup_index, window)

        group_name = record.get("source_group", "unknown")
        group_summary = source_group_counts.setdefault(
            group_name,
            {"input": 0, "prepared": 0, "duplicates": 0, "excluded": 0},
        )
        group_summary["input"] += 1

        if prepared is not None:
            prepared_records.append(prepared)
            kept_count += 1
            group_summary["prepared"] += 1
            status = prepared["content_status"]
            content_status_counts[status] = content_status_counts.get(status, 0) + 1
        else:
            excluded_count += 1
            group_summary["excluded"] += 1
            reason = exclusion["exclude_reason"] or "excluded"
            exclude_reason_counts[reason] = exclude_reason_counts.get(reason, 0) + 1
            excluded_records.append(exclusion)
            if exclusion["is_duplicate"]:
                duplicate_count += 1
                group_summary["duplicates"] += 1

    prepared_records, research_exclusions = _rebalance_research_papers(prepared_records, query_themes)
    for exclusion in research_exclusions:
        excluded_count += 1
        excluded_records.append(exclusion)
        reason = exclusion["exclude_reason"]
        exclude_reason_counts[reason] = exclude_reason_counts.get(reason, 0) + 1
        source_group_counts["research_papers"]["excluded"] += 1
        source_group_counts["research_papers"]["prepared"] -= 1
        status = exclusion["content_status"]
        content_status_counts[status] = max(0, content_status_counts.get(status, 0) - 1)
    kept_count = len(prepared_records)

    output_records = [
        {key: value for key, value in record.items() if key != "record_id"}
        for record in prepared_records
    ]

    payload = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "record_count": kept_count,
        "records": output_records,
    }
    summary = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "status": "ok",
        "input_record_count": len(l1_records["records"]),
        "prepared_record_count": kept_count,
        "excluded_count": excluded_count,
        "duplicate_count": duplicate_count,
        "content_status_counts": content_status_counts,
        "exclude_reason_counts": exclude_reason_counts,
        "source_groups": source_group_counts,
        "excluded_records": excluded_records,
    }

    out_dir = OUTPUT_DIR / run_id / "L2"
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "prepared_records.json"
    summary_path = out_dir / "summary.json"
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"[L2] Prepared records: {kept_count}  "
        f"Duplicates: {duplicate_count}  Excluded: {excluded_count}"
    )
    print(f"[L2] Wrote: {data_path}")
    return data_path


def _prepare_record(record: dict, dedup_index: dict[str, str], window: dict) -> tuple[dict | None, dict | None]:
    record_id = record.get("record_id", "")
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
            "source_group": record.get("source_group", ""),
            "source": record.get("source", ""),
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
    prepared = {
        "record_key": _build_record_key(
            source=record.get("source", ""),
            url=canonical_url,
            title=normalized_title,
            published_at=published_at_iso,
        ),
        "record_id": record.get("record_id", ""),
        "source": record.get("source", ""),
        "source_group": record.get("source_group", ""),
        "source_type": record.get("source_type", ""),
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


def _rebalance_research_papers(prepared_records: list[dict], query_themes: list[str]) -> tuple[list[dict], list[dict]]:
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
        if kept_research >= MAX_RESEARCH_PAPERS:
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
        "record_id": record.get("record_id", ""),
        "source_group": record.get("source_group", ""),
        "source": record.get("source", ""),
        "title": record.get("title", ""),
        "exclude_reason": reason,
        "is_duplicate": False,
        "canonical_record_id": record.get("record_id", ""),
        "content_status": record.get("content_status", ""),
        "published_at": record.get("published_at", ""),
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
    if source_group in {"tech_news_apis", "youtube_podcast_transcripts"} and _is_generic_software_release(title, text):
        return "generic_software_release"
    if source_group in {"youtube_podcast_transcripts", "community_signals"} and _is_general_dev_noise(title, text):
        return "off_topic_general_dev"
    return None


def _topic_text(record: dict, title: str, content: str, canonical_url: str) -> str:
    parts = [
        title,
        canonical_url,
        record.get("description", ""),
        record.get("summary", ""),
        record.get("source_name", ""),
        record.get("channel_name", ""),
        " ".join(record.get("topics", []) or []),
        content[:2500],
    ]
    return clean_text(" ".join(part for part in parts if part)).lower()


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


def _has_ai_relevance(text: str) -> bool:
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


def _load_manifest(run_ref: str) -> dict:
    if run_ref == "current":
        path = CURRENT_MANIFEST_PATH
    else:
        path = OUTPUT_DIR / run_ref / "run_manifest.json"

    if not path.exists():
        if run_ref == "current":
            raise FileNotFoundError(
                "current_manifest.json not found. Run L0 first:\n"
                "  python -m src.pipeline.L0_manifest.runner --run-profile <name>"
            )
        raise FileNotFoundError(
            f"run_manifest.json not found for {run_ref}. Run L0 first:\n"
            "  python -m src.pipeline.L0_manifest.runner --run-profile <name>"
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if run_ref == "current":
        run_id = manifest.get("run_id")
        if not run_id:
            raise KeyError("output/current_manifest.json is missing run_id")
        run_manifest_path = OUTPUT_DIR / run_id / "run_manifest.json"
        if not run_manifest_path.exists():
            raise FileNotFoundError(f"Run manifest not found: {run_manifest_path}")
        manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    return manifest


def _load_l1_records(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L1" / "raw_records.json"
    if not path.exists():
        raise FileNotFoundError(
            f"L1/raw_records.json not found for {run_id}. "
            "This usually means the current manifest points to a run that only completed L0.\n"
            f"Run L1 first:\n  python -m src.pipeline.L1_collection.runner --run-id {run_id}\n"
            "or run both together:\n"
            f"  python -m src.pipeline.runner 1 2 --run-id {run_id}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("records"), list):
        raise ValueError(f"L1/raw_records.json has no valid records list: {path}")
    return data


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    path = run(args.run_id)
    print(path)
