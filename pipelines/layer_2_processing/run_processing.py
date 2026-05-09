"""
Layer 2 Orchestrator — Run the full processing pipeline

Runs all 4 modules in sequence:
  1. Normalizer  — uniform schema + entity extraction
  2. Deduplicator — URL + title dedup
  3. Clusterer   — group same-story articles
  4. Ranker      — score clusters by importance

Input:  output/layer_1_raw/master_YYYY-MM-DD.json
Output: output/layer_2_processed/rankings/ranked_YYYY-MM-DD.json

Usage:
    python run_processing.py                                    # uses today's master file
    python run_processing.py --input output/layer_1_raw/master_2026-05-08.json
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import RAW_OUTPUT, ensure_output_dirs

from pipelines.layer_2_processing.normalizer import normalize_all, save_normalized
from pipelines.layer_2_processing.deduplicator import deduplicate, save_deduplicated
from pipelines.layer_2_processing.clusterer import build_clusters, format_clusters, save_clusters
from pipelines.layer_2_processing.ranker import rank_clusters, save_ranked


def run_processing(master_path, date_str=None):
    """Run the full Layer 2 pipeline."""

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    ensure_output_dirs()

    # ── Step 1: Normalize ──
    print("=" * 60)
    print("  Step 1: NORMALIZE")
    print("=" * 60)
    normalized = normalize_all(master_path)
    norm_path = save_normalized(normalized, date_str)
    print(f"  {len(normalized)} documents normalized → {norm_path}")

    # Entity stats
    with_companies = sum(1 for d in normalized if d["entities"]["companies"])
    with_models    = sum(1 for d in normalized if d["entities"]["models"])
    print(f"  Entities found: {with_companies} docs with companies, {with_models} with models")

    # ── Step 2: Deduplicate ──
    print()
    print("=" * 60)
    print("  Step 2: DEDUPLICATE")
    print("=" * 60)
    unique, url_dupes, title_dupes = deduplicate(normalized)
    dedup_path = save_deduplicated(unique, date_str)
    print(f"  {len(normalized)} → {len(unique)} documents ({url_dupes} URL dupes, {title_dupes} title dupes)")
    print(f"  Saved → {dedup_path}")

    # ── Step 3: Cluster ──
    print()
    print("=" * 60)
    print("  Step 3: CLUSTER")
    print("=" * 60)
    raw_clusters = build_clusters(unique)
    formatted_clusters = format_clusters(unique, raw_clusters)
    cluster_path = save_clusters(formatted_clusters, date_str)
    multi = sum(1 for c in formatted_clusters if c["source_count"] > 1)
    print(f"  {len(unique)} documents → {len(formatted_clusters)} clusters ({multi} multi-source)")
    print(f"  Saved → {cluster_path}")

    # ── Step 4: Rank ──
    print()
    print("=" * 60)
    print("  Step 4: RANK")
    print("=" * 60)
    ranked = rank_clusters(formatted_clusters, unique)
    ranked_path = save_ranked(ranked, date_str)
    print(f"  {len(ranked)} stories ranked")
    print(f"  Saved → {ranked_path}")

    # ── Summary ──
    print()
    print("=" * 60)
    print("  LAYER 2 COMPLETE — Top Stories")
    print("=" * 60)
    for r in ranked[:10]:
        src_auth = r["score_breakdown"]["source_authority"]["reason"][:30]
        print(f"  #{r['rank']:2}  Score: {r['total_score']:3}  [{r['source_count']} srcs]  {r['best_title'][:55]}")
    print()
    print(f"  Final output: {ranked_path}")

    return ranked_path


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run full Layer 2 processing pipeline")
    parser.add_argument("--input", help="Path to master JSON from Layer 1")
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")

    if args.input:
        master_path = args.input
    else:
        master_path = RAW_OUTPUT / f"master_{date_str}.json"

    if not Path(master_path).exists():
        print(f"Master file not found: {master_path}")
        print("Run: python pipelines/layer_1_extraction/run_extraction.py first")
        sys.exit(1)

    print(f"Master file: {master_path}\n")
    run_processing(master_path, date_str)
