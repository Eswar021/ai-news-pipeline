"""
Layer 2 — Module 2: Content Cleaner

Cleans raw_text from Layer 1 into usable plain text.

Rules applied (in order):
  1. Replace \xa0 and other non-standard whitespace with spaces
  2. Remove news API truncation markers: "[+XXXX chars]"
  3. Remove blog boilerplate patterns: "Loading…", "Share", standalone short nav tokens
  4. Remove repeated lines (dedup)
  5. Collapse multiple spaces/blank lines
  6. Strip leading/trailing whitespace

Source-group-aware:
  - ai_company_blogs: extra boilerplate patterns (nav artifacts from HTML stripping)
  - tech_news_apis:   truncation marker removal
  - research_papers:  minimal (text is already clean abstract)
  - community_signals: minimal (often empty, nothing to clean)

Usage:
    python content_cleaner.py --run-id run_2026_05_10_48h_auto
"""

import sys
import re
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


# Boilerplate phrases found in blog HTML-stripped text
_BLOG_BOILERPLATE = re.compile(
    r"\bLoading[…\.]{0,3}\s*"
    r"|\bShare\b\s*"
    r"|\bSubscribe\b\s*"
    r"|\bSign up\b\s*"
    r"|\bRead more\b\s*"
    r"|\bLearn more\b\s*"
    r"|\bClick here\b\s*"
    r"|\bCookie\b[^.]{0,60}\.\s*"
    r"|\bPrivacy Policy\b[^.]{0,60}\.\s*",
    re.IGNORECASE,
)

# Truncation marker from NewsAPI: "… [+4898 chars]"
_TRUNCATION_MARKER = re.compile(r"\[?\+\d+ chars?\]?", re.IGNORECASE)

# Leading date prefix in OpenAI/Anthropic blog text from the article header
# e.g. "May 8, 2026 Security Safety Running Codex safely at OpenAI"
# We detect this when the same title text appears near the start of raw_text
_MULTI_SPACE = re.compile(r"  +")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\xa0", " ")      # non-breaking space
    text = text.replace("​", "")     # zero-width space
    text = text.replace("\t", " ")        # tabs
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


def _remove_truncation_markers(text: str) -> str:
    return _TRUNCATION_MARKER.sub("", text).strip()


def _remove_blog_boilerplate(text: str) -> str:
    return _BLOG_BOILERPLATE.sub(" ", text)


def _dedup_repeated_phrases(text: str) -> str:
    """Remove exact duplicate sentences when the same long phrase appears twice."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    seen = set()
    out = []
    for part in parts:
        key = part.strip().lower()
        if len(key) > 40 and key in seen:
            continue
        seen.add(key)
        out.append(part)
    return " ".join(out)


def clean(raw_text: str, source_group: str = "", title: str = "") -> dict:
    """
    Clean raw_text and return a cleaning report.

    Args:
        raw_text:     Raw text from Layer 1 content.raw_text
        source_group: e.g. "ai_company_blogs", "tech_news_apis"
        title:        Document title (used to strip leading title duplication)

    Returns:
        {
            "clean_text": str,
            "original_char_count": int,
            "clean_char_count": int,
            "was_truncated": bool,
            "boilerplate_removed": bool,
        }
    """
    original_len = len(raw_text)
    text = raw_text

    if not text:
        return {
            "clean_text": "",
            "original_char_count": 0,
            "clean_char_count": 0,
            "was_truncated": False,
            "boilerplate_removed": False,
        }

    text = _normalize_whitespace(text)

    was_truncated = bool(_TRUNCATION_MARKER.search(text))
    if source_group == "tech_news_apis" or was_truncated:
        text = _remove_truncation_markers(text)

    boilerplate_removed = False
    if source_group == "ai_company_blogs":
        cleaned = _remove_blog_boilerplate(text)
        boilerplate_removed = (cleaned != text)
        text = cleaned

        # Strip leading noise: some blog posts start with date + category + title
        # e.g. "May 8, 2026 Security Safety Running Codex..." before actual content
        # Strategy: if the title appears in the first 200 chars, strip everything before
        # the first sentence of real content (first occurrence of a period after the title).
        if title:
            title_lower = title[:40].lower()
            prefix_zone = text[:300].lower()
            title_pos = prefix_zone.find(title_lower[:30])
            if title_pos >= 0:
                # Find first real paragraph start after title region
                after_title = text[title_pos + len(title_lower):]
                # Skip short tokens (categories, nav) and find first long sentence
                first_period = after_title.find(". ")
                if first_period > 0 and first_period < 120:
                    text = after_title[first_period + 2:]

    text = _dedup_repeated_phrases(text)
    text = _normalize_whitespace(text)

    return {
        "clean_text": text,
        "original_char_count": original_len,
        "clean_char_count": len(text),
        "was_truncated": was_truncated,
        "boilerplate_removed": boilerplate_removed,
    }


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    import json
    if args.run_id:
        run_id = args.run_id
    else:
        run_dirs = sorted(RUNS_DIR.glob("*/run_manifest.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = run_dirs[0].parent.name
        print(f"Auto-discovered run: {run_id}")

    raw_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    docs = [json.loads(l) for l in raw_path.read_text().splitlines() if l.strip()]

    print(f"\nContent Cleaner — {run_id}")
    print(f"Testing one doc from each source group:\n")

    seen_groups = set()
    for doc in docs:
        sg = doc["source"]["source_group"]
        if sg in seen_groups:
            continue
        seen_groups.add(sg)

        raw_text = doc["content"].get("raw_text", "")
        title    = doc["item"].get("title", "")
        result   = clean(raw_text, source_group=sg, title=title)

        print(f"  [{sg}]")
        print(f"  Title          : {title[:70]}")
        print(f"  Original chars : {result['original_char_count']}")
        print(f"  Clean chars    : {result['clean_char_count']}")
        print(f"  Truncated      : {result['was_truncated']}")
        print(f"  Boilerplate rm : {result['boilerplate_removed']}")
        print(f"  Clean preview  : {result['clean_text'][:200]}")
        print()
