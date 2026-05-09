"""
Context Builder — Layer 3, Module 5 (Final)

Pure code — no LLM. Merges all Layer 3 outputs into one structured
context packet that Layer 4's script writer reads.

Inputs (auto-detected from latest files):
    selected_topic_{date}.json   → story metadata + source articles
    summary_{date}.json          → synthesized narrative
    claims_{date}.json           → 17 verified facts with source URLs
    enriched_{date}.json         → background, implications, comparisons, audience angle

Output:
    output/layer_3_intelligence/context_packets/context_packet_{date}.json

The context packet is the FINAL output of Layer 3. Layer 4 reads ONLY
this one file — it doesn't need to know about any of the intermediate files.

Usage:
    python context_builder.py                   # uses latest files
    python context_builder.py --date 2026-05-08 # specific date
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import (
    INTEL_OUTPUT, INTEL_SUMMARIES, INTEL_RESEARCH,
    INTEL_CONTEXT, ensure_output_dirs
)


def find_latest(directory, pattern):
    candidates = sorted(Path(directory).glob(pattern), reverse=True)
    return candidates[0] if candidates else None


def load_all_inputs(date_str=None):
    """
    Load all four Layer 3 intermediate files.
    If date_str given, load that specific date. Otherwise auto-detect latest.
    Returns dict of all loaded data + the resolved date string.
    """
    if date_str:
        selected_path = INTEL_OUTPUT    / f"selected_topic_{date_str}.json"
        summary_path  = INTEL_SUMMARIES / f"summary_{date_str}.json"
        claims_path   = INTEL_OUTPUT    / f"claims_{date_str}.json"
        enriched_path = INTEL_RESEARCH  / f"enriched_{date_str}.json"
    else:
        selected_path = find_latest(INTEL_OUTPUT,    "selected_topic_*.json")
        summary_path  = find_latest(INTEL_SUMMARIES, "summary_*.json")
        claims_path   = find_latest(INTEL_OUTPUT,    "claims_*.json")
        enriched_path = find_latest(INTEL_RESEARCH,  "enriched_*.json")
        # Extract date from summary filename (it's the most stable)
        if summary_path:
            date_str = Path(summary_path).stem.replace("summary_", "")

    missing = []
    if not selected_path or not Path(selected_path).exists(): missing.append("selected_topic")
    if not summary_path  or not Path(summary_path).exists():  missing.append("summary")
    if not claims_path   or not Path(claims_path).exists():   missing.append("claims")
    if not enriched_path or not Path(enriched_path).exists(): missing.append("enriched")

    if missing:
        print(f"Missing Layer 3 files: {missing}")
        print("Run the full Layer 3 pipeline first:")
        print("  topic_selector.py → summarizer.py → claim_extractor.py → context_enricher.py")
        sys.exit(1)

    return {
        "selected": json.loads(Path(selected_path).read_text(encoding="utf-8")),
        "summary":  json.loads(Path(summary_path).read_text(encoding="utf-8")),
        "claims":   json.loads(Path(claims_path).read_text(encoding="utf-8")),
        "enriched": json.loads(Path(enriched_path).read_text(encoding="utf-8")),
        "date_str": date_str,
        "paths": {
            "selected": str(selected_path),
            "summary":  str(summary_path),
            "claims":   str(claims_path),
            "enriched": str(enriched_path),
        }
    }


def build_context_packet(inputs):
    """
    Assemble all Layer 3 outputs into one clean context packet.
    This is the document Layer 4 reads — it should be self-contained.
    """
    selected = inputs["selected"]
    summary  = inputs["summary"]
    claims   = inputs["claims"]
    enriched = inputs["enriched"]

    # ── Story identity ──
    topic      = selected.get("best_title") or selected.get("topic", "")
    score      = selected.get("selected_score", 0)
    rank       = selected.get("selected_rank", 0)
    headline   = selected.get("headline_suggestion", topic)

    # ── Source articles — clean list for the script writer ──
    raw_articles = selected.get("source_articles", [])
    sources = []
    for a in raw_articles:
        if not a.get("url"):
            continue
        sources.append({
            "title":       a.get("title", ""),
            "url":         a.get("url", ""),
            "publisher":   a.get("publisher", ""),
            "source_type": a.get("source_type", ""),
            "trust_tier":  a.get("trust_tier", 3),
            "published_at": a.get("published_at", ""),
        })

    # Sort sources by trust tier (best first)
    sources.sort(key=lambda s: s["trust_tier"])

    # ── Claims — split by confidence for script writer convenience ──
    all_claims   = claims.get("claims", [])
    high_conf    = [c for c in all_claims if c.get("confidence") == "high"]
    medium_conf  = [c for c in all_claims if c.get("confidence") == "medium"]
    statistics   = [c for c in all_claims if c.get("type") == "statistic"]
    key_facts    = [c for c in all_claims if c.get("type") in ("product_fact", "comparison")]

    # ── Assemble the packet ──
    packet = {
        # ── Identity ──
        "topic":             topic,
        "headline":          headline,
        "date":              inputs["date_str"],
        "built_at":          datetime.now().isoformat(),

        # ── Story quality signal ──
        "story_score":       score,
        "story_rank":        rank,
        "source_count":      len(sources),
        "entities":          selected.get("entities", {}),

        # ── The core content (in script-writer order of usefulness) ──
        "summary":           summary.get("summary_text", ""),

        # Enriched context sections
        "background":        enriched.get("background", ""),
        "why_it_matters":    enriched.get("why_it_matters", ""),
        "technical_breakdown": enriched.get("technical_breakdown", ""),
        "comparisons":       enriched.get("comparisons", ""),
        "audience_angle":    enriched.get("audience_angle", ""),

        # ── Verified claims — the factual backbone ──
        "key_statistics":    statistics,      # numbers, benchmarks — use on screen
        "key_facts":         key_facts,       # product facts and comparisons
        "all_claims":        all_claims,      # full list with source attribution

        # ── Source reference list ──
        "sources":           sources,

        # ── Metadata for Layer 4 ──
        "pipeline_metadata": {
            "layer3_files_used": inputs["paths"],
            "summary_words":     summary.get("word_count", 0),
            "total_claims":      claims.get("total_claims", 0),
            "claims_by_confidence": claims.get("by_confidence", {}),
            "enrichment_words":  enriched.get("total_enrichment_words", 0),
            "llm_models_used": {
                "summarizer":       summary.get("llm_profile", {}).get("model", ""),
                "claim_extractor":  claims.get("llm_profile", {}).get("model", ""),
                "context_enricher": enriched.get("llm_profile", {}).get("model", ""),
            }
        }
    }

    return packet


def save_packet(packet, date_str):
    """Save context packet to output/layer_3_intelligence/context_packets/"""
    ensure_output_dirs()
    filepath = INTEL_CONTEXT / f"context_packet_{date_str}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, ensure_ascii=False)
    return filepath


def print_packet_summary(packet):
    """Print a readable summary of what the context packet contains."""
    print(f"\n{'='*65}")
    print(f"  CONTEXT PACKET — Ready for Layer 4")
    print(f"{'='*65}")
    print(f"  Topic:        {packet['topic']}")
    print(f"  Headline:     {packet['headline']}")
    print(f"  Story score:  {packet['story_score']}/100 (rank #{packet['story_rank']})")
    print(f"  Sources:      {packet['source_count']}")
    print()
    print(f"  Content:")
    print(f"    Summary:          {len(packet['summary'].split()):4} words")
    print(f"    Background:       {len(packet['background'].split()):4} words")
    print(f"    Why it matters:   {len(packet['why_it_matters'].split()):4} words")
    print(f"    Tech breakdown:   {len(packet['technical_breakdown'].split()):4} words")
    print(f"    Comparisons:      {len(packet['comparisons'].split()):4} words")
    print(f"    Audience angle:   {len(packet['audience_angle'].split()):4} words")
    print(f"    ──────────────────────────────")
    total_words = sum(len(packet[s].split()) for s in
                      ['summary','background','why_it_matters','technical_breakdown','comparisons','audience_angle'])
    print(f"    TOTAL content:    {total_words:4} words")
    print()
    print(f"  Claims: {packet['pipeline_metadata']['total_claims']} total")
    print(f"    Statistics (for on-screen display): {len(packet['key_statistics'])}")
    for s in packet["key_statistics"]:
        print(f"      • {s['claim'][:70]}")
    print()
    print(f"  Sources:")
    for s in packet["sources"]:
        print(f"    [Tier {s['trust_tier']}] {s['publisher']:20} {s['title'][:40]}")
    print()
    print(f"  LLM models used: {packet['pipeline_metadata']['llm_models_used']}")


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assemble final Layer 3 context packet")
    parser.add_argument("--date", help="Specific date to build packet for (YYYY-MM-DD)")
    args = parser.parse_args()

    inputs = load_all_inputs(date_str=args.date)

    print(f"Loaded files for date: {inputs['date_str']}")
    for name, path in inputs["paths"].items():
        print(f"  {name:12} → {Path(path).name}")

    packet  = build_context_packet(inputs)
    filepath = save_packet(packet, inputs["date_str"])

    print_packet_summary(packet)

    print(f"{'='*65}")
    print(f"  Saved to: {filepath}")
    print(f"{'='*65}")
    print(f"\nLayer 3 complete. Next:")
    print(f"  python pipelines/layer_4_content/script_writer.py")
