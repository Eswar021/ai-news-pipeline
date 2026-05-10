"""
Layer 3 — Module 3: Exact Duplicate Detector

Detects and groups exact or near-exact duplicate documents:
  1. Same canonical URL (different tracking params already stripped by Layer 2)
  2. Same normalized title within the same source_group

For each duplicate group, picks one representative document:
  - prefer higher trust tier (lower number)
  - prefer more complete content (full > abstract_only > partial > title_only)
  - prefer earlier published_at

Returns the deduplicated doc list plus a duplicate_groups record.

Usage:
    python exact_duplicate_detector.py --run-id run_2026_05_10_48h_auto
"""

import re
import sys
import json
import hashlib
import argparse
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_COMPLETENESS_ORDER = {"full": 0, "abstract_only": 1, "partial": 2, "title_only": 3, "metadata_only": 4}
_TITLE_NOISE = re.compile(r"[^a-z0-9 ]")


def _title_key(title: str) -> str:
    """Normalize title to a dedup key."""
    t = title.lower().strip()
    t = _TITLE_NOISE.sub("", t)
    t = " ".join(t.split())
    return hashlib.sha1(t.encode()).hexdigest()[:12]


def _pick_representative(group: list[dict]) -> dict:
    """Choose the best document from a duplicate group."""
    def sort_key(d):
        tier = d.get("trust_tier", 4)
        comp = _COMPLETENESS_ORDER.get(d.get("content_completeness", ""), 99)
        date = d.get("published_at") or "9999"
        return (tier, comp, date)
    return sorted(group, key=sort_key)[0]


def detect(docs: list[dict]) -> dict:
    """
    Detect exact duplicates across the document list.

    Returns:
        {
            "deduplicated_docs":  [doc, ...],   # one per group; others collapsed
            "duplicate_groups":   [group, ...],
            "duplicate_doc_ids":  {duplicate_doc_id: representative_doc_id},
            "counts": {...},
        }
    """
    # ── Group by canonical URL ─────────────────────────────────────────────────
    url_groups: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        url = (doc.get("canonical_url") or "").rstrip("/")
        if url:
            url_groups[url].append(doc)

    # ── Group by title key within same source_group ────────────────────────────
    title_groups: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        tk = _title_key(doc.get("title", ""))
        sg = doc.get("source_group", "")
        title_groups[f"{sg}|{tk}"].append(doc)

    # ── Merge into duplicate groups ────────────────────────────────────────────
    seen_doc_ids: set[str] = set()
    processed_groups: set[frozenset] = set()
    duplicate_groups: list[dict] = []
    duplicate_doc_ids: dict[str, str] = {}   # dup_id → representative_id

    def _record_group(group_docs: list[dict], dup_type: str):
        if len(group_docs) < 2:
            return
        key = frozenset(d["canonical_document_id"] for d in group_docs)
        if key in processed_groups:
            return
        processed_groups.add(key)

        rep = _pick_representative(group_docs)
        rep_id = rep["canonical_document_id"]
        dups = [d for d in group_docs if d["canonical_document_id"] != rep_id]
        dup_ids = [d["canonical_document_id"] for d in dups]

        for did in dup_ids:
            duplicate_doc_ids[did] = rep_id

        duplicate_groups.append({
            "duplicate_group_id":       f"dup_{len(duplicate_groups)+1:03d}",
            "representative_document_id": rep_id,
            "duplicate_document_ids":   dup_ids,
            "duplicate_type":           dup_type,
            "group_size":               len(group_docs),
            "confidence":               1.0 if dup_type == "same_canonical_url" else 0.9,
        })

    for url, group in url_groups.items():
        if len(group) > 1:
            _record_group(group, "same_canonical_url")

    for key, group in title_groups.items():
        if len(group) > 1:
            _record_group(group, "same_normalized_title_in_source_group")

    # ── Build deduplicated doc list ────────────────────────────────────────────
    dup_ids_set = set(duplicate_doc_ids.keys())
    deduplicated = [d for d in docs if d["canonical_document_id"] not in dup_ids_set]

    return {
        "deduplicated_docs": deduplicated,
        "duplicate_groups":  duplicate_groups,
        "duplicate_doc_ids": duplicate_doc_ids,
        "counts": {
            "input_docs":           len(docs),
            "deduplicated_docs":    len(deduplicated),
            "removed_duplicates":   len(dup_ids_set),
            "duplicate_groups":     len(duplicate_groups),
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_2" / "canonical_documents.jsonl").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    docs = [json.loads(l)
            for l in (RUNS_DIR / run_id / "layer_2" / "canonical_documents.jsonl")
            .read_text().splitlines() if l.strip()]

    result = detect(docs)
    print(f"\nExact Duplicate Detector — {run_id}")
    for k, v in result["counts"].items():
        print(f"  {k:30}: {v}")
    if result["duplicate_groups"]:
        print("\n  Duplicate groups found:")
        for g in result["duplicate_groups"]:
            rep = g["representative_document_id"]
            dups = g["duplicate_document_ids"]
            print(f"    [{g['duplicate_type']}] rep={rep[:40]} dups={dups}")
