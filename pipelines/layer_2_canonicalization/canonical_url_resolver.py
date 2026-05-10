"""
Layer 2 — Module 4: Canonical URL + Identity Resolver

Normalizes URLs and generates stable canonical_document_id.

Canonical URL logic:
  1. Strip tracking parameters (utm_*, fbclid, gclid, ref, etc.)
  2. Normalize trailing slash
  3. Lowercase scheme and host, preserve path casing

canonical_document_id format:
  doc_{YYYYMMDD}_{source_id_slug}_{hash8}
  e.g. doc_20260508_openai_news_6cfef787

The hash is computed over (canonical_url + title) so it's stable across runs
for the same article.

Usage:
    python canonical_url_resolver.py --run-id run_2026_05_10_48h_auto
"""

import sys
import re
import json
import hashlib
import argparse
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_reader", "utm_name",
    "fbclid", "gclid", "msclkid", "dclid",
    "ref", "source", "campaign_id",
    "_ga", "_gl",
}


def canonical_url(url: str) -> str:
    """Strip tracking params, normalize scheme/host, return clean URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=False)
        clean_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        clean_query = urlencode(clean_qs, doseq=True)
        path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
        clean = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            clean_query,
            "",   # drop fragment
        ))
        return clean
    except Exception:
        return url


def _source_id_slug(source_id: str) -> str:
    """Convert source_id to a safe slug (max 20 chars)."""
    slug = re.sub(r"[^a-z0-9]+", "_", source_id.lower()).strip("_")
    return slug[:20]


def make_canonical_document_id(canonical_url_str: str, title: str,
                                source_id: str, iso_date: str | None) -> str:
    """
    Generate a stable canonical_document_id.

    Format: doc_{YYYYMMDD}_{source_id_slug}_{hash8}
    """
    date_str = "00000000"
    if iso_date:
        date_str = iso_date[:10].replace("-", "")

    content = f"{canonical_url_str}|{title}"
    hash8 = hashlib.sha256(content.encode()).hexdigest()[:8]
    slug  = _source_id_slug(source_id)

    return f"doc_{date_str}_{slug}_{hash8}"


def resolve(doc: dict, iso_date: str | None = None) -> dict:
    """
    Resolve canonical URL and generate document identity for a Layer 1 doc.

    Returns:
        {
            "canonical_document_id": str,
            "original_url": str,
            "canonical_url": str,
            "url_normalized": bool,
        }
    """
    item   = doc.get("item", {})
    source = doc.get("source", {})

    original_url  = item.get("url") or ""
    source_id     = source.get("source_id") or "unknown"
    title         = item.get("title") or ""

    canon_url = canonical_url(original_url)
    url_normalized = (canon_url != original_url)

    doc_id = make_canonical_document_id(canon_url, title, source_id, iso_date)

    return {
        "canonical_document_id": doc_id,
        "original_url":          original_url,
        "canonical_url":         canon_url,
        "url_normalized":        url_normalized,
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

    print(f"\nCanonical URL Resolver — {run_id}")
    seen = set()
    for doc in docs:
        sg = doc["source"]["source_group"]
        if sg in seen:
            continue
        seen.add(sg)
        result = resolve(doc, iso_date="2026-05-10T00:00:00Z")
        print(f"  [{sg}]")
        print(f"  Original URL  : {result['original_url'][:80]}")
        print(f"  Canonical URL : {result['canonical_url'][:80]}")
        print(f"  Doc ID        : {result['canonical_document_id']}")
        print(f"  Normalized    : {result['url_normalized']}")
        print()
