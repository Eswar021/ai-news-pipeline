"""
Layer 2 — Module 3: Metadata Normalizer

Standardizes metadata across all source types:
  - Normalize published_at to ISO 8601 UTC (three formats observed in real data)
  - Normalize author/publisher
  - Assign content_type from source_group + source_type
  - Extract/normalize language (default "en")

Date formats handled:
  - RSS    : "Fri, 08 May 2026 12:30:00 GMT"
  - Human  : "May 7, 2026" or "Apr 16, 2026"
  - ISO T  : "2026-05-09T13:00:02Z" or "2026-05-10T06:20:50+00:00"
  - ISO sp : "2026-05-10 00:06:56" (NewsData.io format)

Usage:
    python metadata_normalizer.py --run-id run_2026_05_10_48h_auto
"""

import sys
import re
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


# ── Date parsing ──────────────────────────────────────────────────────────────

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_RSS_RE    = re.compile(
    r"(\d{1,2})\s+(\w{3})\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\s+(?:GMT|UTC|[+-]\d{4})")
_HUMAN_RE  = re.compile(r"(\w{3,9})\s+(\d{1,2}),?\s+(\d{4})")


def normalize_date(raw: str) -> tuple[str | None, str]:
    """
    Parse a raw date string to ISO 8601 UTC.

    Returns (iso_string, confidence) where confidence is "high", "low", or "missing".
    """
    if not raw or not raw.strip():
        return None, "missing"

    raw = raw.strip()

    # Already ISO 8601 (with or without timezone)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[:19], fmt[:len(fmt)])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "high"
        except ValueError:
            pass

    # Handle ISO with offset like "2026-05-10T06:20:50+00:00"
    iso_offset = re.match(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})[+-]\d{2}:\d{2}$", raw)
    if iso_offset:
        try:
            dt = datetime.strptime(iso_offset.group(1), "%Y-%m-%dT%H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "high"
        except ValueError:
            pass

    # RSS format: "Fri, 08 May 2026 12:30:00 GMT"
    m = _RSS_RE.search(raw)
    if m:
        try:
            day, mon_str, year, h, mi, s = m.groups()
            mon = _MONTH_MAP.get(mon_str[:3].lower())
            if mon:
                dt = datetime(int(year), mon, int(day), int(h), int(mi), int(s),
                               tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "high"
        except (ValueError, TypeError):
            pass

    # Human format: "May 7, 2026" or "April 16, 2026"
    m = _HUMAN_RE.search(raw)
    if m:
        try:
            mon_str, day, year = m.groups()
            mon = _MONTH_MAP.get(mon_str[:3].lower())
            if mon:
                dt = datetime(int(year), mon, int(day), tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "low"
        except (ValueError, TypeError):
            pass

    return None, "missing"


# ── Content-type assignment ───────────────────────────────────────────────────

_CONTENT_TYPE_MAP = {
    "ai_company_blogs":          "announcement",
    "research_papers":           "research_paper",
    "tech_news_apis":            "news_article",
    "community_signals":         "community_post",
    "github_open_source_signals": "github_repository",
    "youtube_podcast_transcripts": "video_transcript",
}

_SOURCE_TYPE_OVERRIDES = {
    "research_paper": "research_paper",
    "video_transcript": "video_transcript",
    "community_signal": "community_post",
    "official_company_blog": "announcement",
    "tech_news_api": "news_article",
    "github_repository": "github_repository",
}


def assign_content_type(source_group: str, source_type: str = "") -> str:
    override = _SOURCE_TYPE_OVERRIDES.get(source_type)
    if override:
        return override
    return _CONTENT_TYPE_MAP.get(source_group, "unknown")


# ── Author/publisher normalization ────────────────────────────────────────────

def normalize_author(item: dict, source: dict) -> dict:
    """Return normalized author and publisher fields."""
    author    = (item.get("author") or "").strip()
    company   = (item.get("company") or "").strip()
    publisher = (item.get("publisher") or "").strip()
    source_name = (source.get("source_name") or "").strip()

    if not author:
        author = company or publisher or source_name or "Unknown"
    if not publisher:
        publisher = company or source_name or author

    return {"author": author, "publisher": publisher}


# ── Main normalize function ───────────────────────────────────────────────────

def normalize(doc: dict) -> dict:
    """
    Extract and normalize metadata from a Layer 1 raw document.

    Returns:
        {
            "title": str,
            "author": str,
            "publisher": str,
            "published_at": str | None,        # ISO 8601 UTC
            "date_confidence": str,             # "high" | "low" | "missing"
            "language": str,
            "content_type": str,
            "metadata_warnings": [str],
        }
    """
    item   = doc.get("item", {})
    source = doc.get("source", {})

    title       = (item.get("title") or "").strip()
    raw_date    = item.get("published_at") or ""
    language    = (item.get("language") or "en").strip() or "en"
    source_group = source.get("source_group", "")
    source_type  = source.get("source_type", "")

    iso_date, date_confidence = normalize_date(raw_date)
    author_info  = normalize_author(item, source)
    content_type = assign_content_type(source_group, source_type)

    warnings = []
    if not title:
        warnings.append("missing_title")
    if date_confidence == "missing":
        warnings.append("missing_publish_date")
    elif date_confidence == "low":
        warnings.append("low_confidence_date")

    return {
        "title":            title or "Untitled",
        "author":           author_info["author"],
        "publisher":        author_info["publisher"],
        "published_at":     iso_date,
        "date_confidence":  date_confidence,
        "language":         language,
        "content_type":     content_type,
        "metadata_warnings": warnings,
    }


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    if args.run_id:
        run_id = args.run_id
    else:
        run_dirs = sorted(RUNS_DIR.glob("*/run_manifest.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = run_dirs[0].parent.name
        print(f"Auto-discovered run: {run_id}")

    raw_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    docs = [json.loads(l) for l in raw_path.read_text().splitlines() if l.strip()]

    print(f"\nMetadata Normalizer — {run_id}")
    seen = set()
    for doc in docs:
        sg = doc["source"]["source_group"]
        if sg in seen:
            continue
        seen.add(sg)
        result = normalize(doc)
        raw_date = doc["item"].get("published_at", "")
        print(f"  [{sg}]")
        print(f"  Title         : {result['title'][:65]}")
        print(f"  Raw date      : {raw_date[:40]}")
        print(f"  ISO date      : {result['published_at']} ({result['date_confidence']})")
        print(f"  content_type  : {result['content_type']}")
        print(f"  author        : {result['author']}")
        print(f"  warnings      : {result['metadata_warnings']}")
        print()
