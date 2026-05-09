"""
Deduplicator — Layer 2, Module 2

Takes normalized documents and removes duplicates:
  - Pass 1: Exact URL match (after stripping tracking params)
  - Pass 2: Title similarity (>80% word overlap from different sources)

The "winner" is the doc with more content (longer raw_text).
Losers become "also_reported_by" references on the winner.

Usage:
    python deduplicator.py                                     # uses today's normalized file
    python deduplicator.py --input output/layer_2_processed/documents/normalized_2026-05-08.json
"""

import sys
import json
import re
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import PROCESSED_DOCS, ensure_output_dirs


# ── URL cleaning ──────────────────────────────────────────────────────────────

# Tracking params to strip
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
                     "ref", "source", "at_medium", "at_campaign"}

def clean_url(url):
    """Strip tracking parameters so we can compare base URLs."""
    if not url:
        return ""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=False)
    cleaned = {k: v for k, v in params.items() if k not in _TRACKING_PARAMS}
    clean_query = urlencode(cleaned, doseq=True) if cleaned else ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" + (f"?{clean_query}" if clean_query else "")


# ── Title similarity ──────────────────────────────────────────────────────────

def title_words(title):
    """Extract meaningful words from a title (lowercase, no short words)."""
    words = re.findall(r"[a-zA-Z]{3,}", title.lower())
    return set(words)

def word_overlap(title_a, title_b):
    """
    Calculate word overlap ratio between two titles.
    Returns 0.0 to 1.0 — ratio of shared words to the smaller set size.
    """
    words_a = title_words(title_a)
    words_b = title_words(title_b)
    if not words_a or not words_b:
        return 0.0
    shared = words_a & words_b
    smaller = min(len(words_a), len(words_b))
    return len(shared) / smaller


# ── Dedup logic ───────────────────────────────────────────────────────────────

TITLE_SIMILARITY_THRESHOLD = 0.80   # 80% word overlap = same article

def deduplicate(docs):
    """
    Remove duplicate documents. Returns (unique_docs, removed_count).

    Pass 1: Group by cleaned URL. Keep the doc with most content.
    Pass 2: For remaining docs, check title similarity across different sources.
    """
    # Pass 1: URL dedup
    url_groups = {}
    for doc in docs:
        curl = clean_url(doc["url"])
        if not curl:
            # No URL — keep as-is (some arXiv or HN items might have empty URLs)
            url_groups[doc["document_id"]] = [doc]
            continue
        if curl not in url_groups:
            url_groups[curl] = []
        url_groups[curl].append(doc)

    # Pick winner from each URL group
    after_url_dedup = []
    url_dupes_removed = 0
    for key, group in url_groups.items():
        # Sort by raw_text length descending — richest content wins
        group.sort(key=lambda d: len(d.get("raw_text", "")), reverse=True)
        winner = group[0]

        # Attach "also_reported_by" from losers
        if len(group) > 1:
            also = [{"document_id": d["document_id"], "module": d["module"], "publisher": d["publisher"]}
                    for d in group[1:]]
            winner["also_reported_by"] = also
            url_dupes_removed += len(group) - 1

        after_url_dedup.append(winner)

    # Pass 2: Title similarity dedup
    unique = []
    title_dupes_removed = 0

    for doc in after_url_dedup:
        is_dupe = False
        for existing in unique:
            # Only dedup across different source modules
            if doc["module"] == existing["module"]:
                continue
            sim = word_overlap(doc["title"], existing["title"])
            if sim >= TITLE_SIMILARITY_THRESHOLD:
                # This is a title dupe — merge into existing
                also = existing.get("also_reported_by", [])
                also.append({"document_id": doc["document_id"], "module": doc["module"],
                             "publisher": doc["publisher"], "title_similarity": round(sim, 2)})
                existing["also_reported_by"] = also

                # If the new doc has more content, swap the raw_text
                if len(doc.get("raw_text", "")) > len(existing.get("raw_text", "")):
                    existing["raw_text"] = doc["raw_text"]

                is_dupe = True
                title_dupes_removed += 1
                break

        if not is_dupe:
            unique.append(doc)

    return unique, url_dupes_removed, title_dupes_removed


def save_deduplicated(docs, date_str=None):
    """Save deduplicated documents."""
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    filepath = PROCESSED_DOCS / f"deduplicated_{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deduplicate normalized documents")
    parser.add_argument("--input", help="Path to normalized JSON (default: today's)")
    args = parser.parse_args()

    if args.input:
        input_path = args.input
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        input_path = PROCESSED_DOCS / f"normalized_{date_str}.json"

    print(f"Loading: {input_path}")
    docs = json.loads(Path(input_path).read_text(encoding="utf-8"))
    print(f"Input: {len(docs)} documents")

    unique, url_dupes, title_dupes = deduplicate(docs)

    print(f"\nDeduplication results:")
    print(f"  URL duplicates removed:   {url_dupes}")
    print(f"  Title duplicates removed: {title_dupes}")
    print(f"  Unique documents:         {len(unique)}")

    # Show some that had duplicates
    merged = [d for d in unique if d.get("also_reported_by")]
    if merged:
        print(f"\n  Documents with merged sources ({len(merged)}):")
        for d in merged[:5]:
            also = d["also_reported_by"]
            print(f"    [{d['module'][:12]}] {d['title'][:55]}")
            for a in also:
                print(f"      └ also from: {a['module']} ({a.get('publisher', '')})")

    filepath = save_deduplicated(unique)
    print(f"\nSaved to: {filepath}")
