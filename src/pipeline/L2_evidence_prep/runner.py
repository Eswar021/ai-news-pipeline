"""
L2 Evidence Prep — clean, normalize, and soft-deduplicate collected records.

Reads:
    output/{run_id}/run_manifest.json         → runtime contract
    output/{run_id}/L1/raw_records.json       → collected record list

Writes:
    output/{run_id}/L2/prepared_records.json  → same records with appended l2 fields
    output/{run_id}/L2/summary.json           → keep/drop/duplicate counts

LLM: no

Module execution order:
    1. load manifest and L1 records
    2. normalize title/content/date/url at record level
    3. soft-flag obvious duplicates
    4. write prepared records and summary

Usage:
    python -m src.pipeline.L2_evidence_prep.runner --run-id run_...
    python -m src.pipeline.L2_evidence_prep.runner --run-id current
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.pipeline.L1_collection.common import clean_text, parse_datetime


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


def run(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    run_id = manifest["run_id"]
    print(f"[L2] Run: {run_id}")
    l1_records = _load_l1_records(run_id)
    print(f"[L2] Input records: {l1_records['record_count']}")

    prepared_records: list[dict] = []
    dedup_index: dict[str, str] = {}
    content_status_counts = {"full": 0, "partial": 0, "title_only": 0}
    exclude_reason_counts: dict[str, int] = {}
    source_group_counts: dict[str, dict[str, int]] = {}

    kept_count = 0
    duplicate_count = 0
    excluded_count = 0

    for record in l1_records["records"]:
        prepared = dict(record)
        l2_fields = _prepare_l2_fields(record, dedup_index)
        prepared["l2"] = l2_fields
        prepared_records.append(prepared)

        status = l2_fields["content_status"]
        content_status_counts[status] = content_status_counts.get(status, 0) + 1

        group_name = record.get("source_group", "unknown")
        group_summary = source_group_counts.setdefault(
            group_name,
            {"total": 0, "kept_for_story_map": 0, "duplicates": 0, "excluded": 0},
        )
        group_summary["total"] += 1

        if l2_fields["keep_for_story_map"]:
            kept_count += 1
            group_summary["kept_for_story_map"] += 1
        else:
            excluded_count += 1
            group_summary["excluded"] += 1
            reason = l2_fields["exclude_reason"] or "excluded"
            exclude_reason_counts[reason] = exclude_reason_counts.get(reason, 0) + 1

        if l2_fields["is_duplicate"]:
            duplicate_count += 1
            group_summary["duplicates"] += 1

    payload = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "record_count": len(prepared_records),
        "kept_for_story_map_count": kept_count,
        "records": prepared_records,
    }
    summary = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "status": "ok",
        "total_records": len(prepared_records),
        "kept_for_story_map_count": kept_count,
        "excluded_count": excluded_count,
        "duplicate_count": duplicate_count,
        "content_status_counts": content_status_counts,
        "exclude_reason_counts": exclude_reason_counts,
        "source_groups": source_group_counts,
    }

    out_dir = OUTPUT_DIR / run_id / "L2"
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "prepared_records.json"
    summary_path = out_dir / "summary.json"
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"[L2] Kept for story map: {kept_count}  "
        f"Duplicates: {duplicate_count}  Excluded: {excluded_count}"
    )
    print(f"[L2] Wrote: {data_path}")
    return data_path


def _prepare_l2_fields(record: dict, dedup_index: dict[str, str]) -> dict:
    record_id = record["id"]
    normalized_title = clean_text(record.get("title", ""))
    normalized_content = clean_text(record.get("content", ""))
    published_at_iso = _normalize_published_at(record.get("published_at"))
    canonical_url = _canonicalize_url(record.get("url", ""))
    content_status = _resolve_content_status(record, normalized_title, normalized_content)

    keep_for_story_map = True
    exclude_reason = None
    is_duplicate = False
    canonical_record_id = record_id

    if not published_at_iso:
        keep_for_story_map = False
        exclude_reason = "missing_published_at"
    elif not normalized_title and not normalized_content:
        keep_for_story_map = False
        exclude_reason = "empty_record"

    dedup_key, dedup_reason = _build_dedup_key(
        record=record,
        canonical_url=canonical_url,
        normalized_title=normalized_title,
        published_at_iso=published_at_iso,
    )
    if keep_for_story_map and dedup_key:
        if dedup_key in dedup_index:
            is_duplicate = True
            canonical_record_id = dedup_index[dedup_key]
            keep_for_story_map = False
            exclude_reason = dedup_reason
        else:
            dedup_index[dedup_key] = record_id

    return {
        "published_at_iso": published_at_iso,
        "normalized_title": normalized_title,
        "normalized_content": normalized_content,
        "content_status": content_status,
        "canonical_url": canonical_url,
        "is_duplicate": is_duplicate,
        "canonical_record_id": canonical_record_id,
        "keep_for_story_map": keep_for_story_map,
        "exclude_reason": exclude_reason,
    }


def _normalize_published_at(value: str | None) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return ""
    return parsed.isoformat()


def _resolve_content_status(record: dict, normalized_title: str, normalized_content: str) -> str:
    metadata = record.get("metadata") or {}
    existing = metadata.get("content_status")
    if existing in {"full", "partial", "title_only"}:
        return existing

    if len(normalized_content) >= 400:
        return "full"
    if len(normalized_content) >= 50:
        return "partial"
    if normalized_title:
        return "title_only"
    return "partial"


def _build_dedup_key(
    *,
    record: dict,
    canonical_url: str,
    normalized_title: str,
    published_at_iso: str,
) -> tuple[str | None, str | None]:
    metadata = record.get("metadata") or {}
    if metadata.get("video_id"):
        return f"video:{metadata['video_id']}", "duplicate_video_id"

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
    return json.loads(path.read_text(encoding="utf-8"))


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
