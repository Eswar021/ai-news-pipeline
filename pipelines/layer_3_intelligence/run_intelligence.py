"""
Layer 3 Orchestrator — Run the full intelligence pipeline

Runs all 5 modules in sequence:
  1. topic_selector  — pick which story to cover (manual or --auto)
  2. summarizer      — LLM synthesizes source articles
  3. claim_extractor — LLM extracts verified claims with source URLs
  4. context_enricher — LLM adds background, implications, comparisons
  5. context_builder  — code-only: assembles final context packet

Input:  output/layer_2_processed/rankings/ranked_YYYY-MM-DD.json
Output: output/layer_3_intelligence/context_packets/context_packet_YYYY-MM-DD.json

Usage:
    python run_intelligence.py              # manual topic selection
    python run_intelligence.py --auto       # LLM picks the topic
    python run_intelligence.py --pick 2     # pick rank 2 story
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import INTEL_CONTEXT, ensure_output_dirs

from pipelines.layer_3_intelligence.topic_selector import (
    load_ranked_stories, auto_select, build_selected_topic,
    load_source_articles, save_selected, display_stories
)
from pipelines.layer_3_intelligence.summarizer import (
    run_summarizer, save_summary
)
from pipelines.layer_3_intelligence.claim_extractor import (
    run_claim_extractor, save_claims
)
from pipelines.layer_3_intelligence.context_enricher import (
    run_enricher, save_enriched
)
from pipelines.layer_3_intelligence.context_builder import (
    load_all_inputs, build_context_packet, save_packet, print_packet_summary
)

from config.paths import PROCESSED_DOCS, PROCESSED_RANKINGS


def run_intelligence(auto=False, pick=None, top=10):
    ensure_output_dirs()
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Resolve today's ranked file
    candidates = sorted(PROCESSED_RANKINGS.glob("ranked_*.json"), reverse=True)
    if not candidates:
        print("No ranked file found. Run Layer 2 first:")
        print("  python pipelines/layer_2_processing/run_processing.py")
        sys.exit(1)
    ranked_path = candidates[0]
    docs_path   = sorted(PROCESSED_DOCS.glob("deduplicated_*.json"), reverse=True)[0]

    # Infer date from the ranked file
    date_str = Path(ranked_path).stem.replace("ranked_", "")

    # ── Step 1: Topic Selection ──
    print("=" * 65)
    print("  Step 1: TOPIC SELECTION")
    print("=" * 65)
    stories = load_ranked_stories(ranked_path, top_n=top)

    if auto:
        print(f"  LLM auto-selecting from top {len(stories)} stories...")
        selected_story, reason, headline, _ = auto_select(stories)
        selection_mode = "auto"
    elif pick:
        selected_story = next((s for s in stories if s["rank"] == pick), stories[0])
        reason = f"Manually selected rank {pick}"
        headline = selected_story["best_title"][:60]
        selection_mode = "manual"
    else:
        display_stories(stories)
        choice = input("Pick a story number: ").strip()
        pick_rank = int(choice) if choice.isdigit() else 1
        selected_story = next((s for s in stories if s["rank"] == pick_rank), stories[0])
        reason = f"Manually selected rank {pick_rank}"
        headline = selected_story["best_title"][:60]
        selection_mode = "manual"

    print(f"  Selected #{selected_story['rank']}: {selected_story['best_title'][:55]}")
    articles = load_source_articles(docs_path, selected_story["document_ids"])
    selected_topic = build_selected_topic(selected_story, articles, reason, headline, selection_mode)
    selected_path  = save_selected(selected_topic, date_str)
    print(f"  {len(articles)} source articles loaded → {selected_path.name}")

    # ── Step 2: Summarize ──
    print()
    print("=" * 65)
    print("  Step 2: SUMMARIZE")
    print("=" * 65)
    summary = run_summarizer(selected_path)
    summary_path = save_summary(summary, date_str)
    print(f"  {summary['word_count']} words → {summary_path.name}")

    # ── Step 3: Extract Claims ──
    print()
    print("=" * 65)
    print("  Step 3: EXTRACT CLAIMS")
    print("=" * 65)
    claims = run_claim_extractor(summary_path, selected_path)
    claims_path = save_claims(claims, date_str)
    print(f"  {claims['total_claims']} claims extracted → {claims_path.name}")

    # ── Step 4: Enrich ──
    print()
    print("=" * 65)
    print("  Step 4: ENRICH CONTEXT")
    print("=" * 65)
    enriched = run_enricher(summary_path, claims_path, selected_path)
    enriched_path = save_enriched(enriched, date_str)
    print(f"  {enriched['total_enrichment_words']} words added → {enriched_path.name}")

    # ── Step 5: Build context packet ──
    print()
    print("=" * 65)
    print("  Step 5: BUILD CONTEXT PACKET")
    print("=" * 65)
    inputs  = load_all_inputs(date_str=date_str)
    packet  = build_context_packet(inputs)
    packet_path = save_packet(packet, date_str)

    print_packet_summary(packet)
    print(f"\nLayer 3 complete → {packet_path}")
    return packet_path


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run full Layer 3 intelligence pipeline")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--auto", action="store_true", help="LLM picks the topic")
    mode.add_argument("--pick", type=int, help="Directly pick story by rank number")
    parser.add_argument("--top", type=int, default=10, help="Consider top N stories (default 10)")
    args = parser.parse_args()

    run_intelligence(auto=args.auto, pick=args.pick, top=args.top)
