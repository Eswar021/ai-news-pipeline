"""
Claim Extractor — Layer 3, Module 3

Reads the synthesized summary and the original source articles, then asks
the LLM to extract every verifiable factual claim and map each one back
to the exact source URL that supports it.

This is fundamentally different from the summarizer:
  - Summarizer → narrative prose, tells the story
  - Claim extractor → structured list of discrete facts with source attribution

Why this matters for your YouTube channel:
  Every fact you say on camera can be traced to a source. If you say
  "Claude Opus 4.7 lifted coding resolution by 13% over Opus 4.6" you
  can show that source on screen. This is what separates credible AI news
  from rumor channels.

The LLM only extracts claims that are DIRECTLY backed by a source article.
It does NOT invent or infer facts — if something isn't in the sources, it
doesn't appear here. That's the job of context_enricher in Module 4.

Output: claims_YYYY-MM-DD.json — consumed by context_enricher.py next.

Usage:
    python claim_extractor.py                                   # uses latest files
    python claim_extractor.py --summary output/.../summary_2026-05-08.json
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import INTEL_OUTPUT, INTEL_SUMMARIES, INTEL_OUTPUT, ensure_output_dirs
from config.llm_config import get_profile
from llm.llm_client import make_llm
from llm.llm_logger import call_llm


MODULE_NAME = "claim_extractor"


def build_sources_reference(source_articles):
    """
    Build a compact source reference block so the LLM knows
    which URL maps to which publisher/type — used in the prompt.
    """
    lines = []
    for i, a in enumerate(source_articles, start=1):
        publisher = a.get("publisher", "Unknown")
        source_type = a.get("source_type", "")
        trust_tier = a.get("trust_tier", 3)
        url = a.get("url", "")
        lines.append(f"  Source {i}: {publisher} | {source_type} | Tier {trust_tier} | {url}")
    return "\n".join(lines)


def build_prompt(summary_data, selected_topic_data):
    """
    Build the claim extraction prompt.

    The LLM is given:
      1. The synthesized summary (what we know)
      2. The list of source URLs (so it can attribute each claim)

    It must output claims in a strict format we can parse.
    """
    summary_text = summary_data.get("summary_text", "")
    topic = summary_data.get("topic", "")
    source_articles = selected_topic_data.get("source_articles", [])

    # Only meaningful articles (same filter as summarizer)
    meaningful_articles = [a for a in source_articles if len(a.get("raw_text", "")) >= 200]
    sources_block = build_sources_reference(meaningful_articles)

    n_sources = len(meaningful_articles)

    prompt = f"""You are a fact-checking analyst for an AI news channel. Your job is to extract every specific, verifiable factual claim from the summary below and map each claim back to its source.

Topic: {topic}

Available sources ({n_sources} total):
{sources_block}

---

Summary to analyze:
{summary_text}

---

Extract every factual claim from this summary. For each claim:

RULES:
1. Only extract claims that are DIRECTLY stated in the summary (which came from the sources)
2. Do NOT extract opinions, speculation, or vague statements ("may improve", "could help")
3. Do NOT invent or infer — if a number or fact isn't stated, don't include it
4. One claim per entry — split compound statements into separate claims
5. Map each claim to the MOST SPECIFIC source that supports it (prefer lower-numbered/higher-trust sources)

OUTPUT FORMAT — output ONLY a JSON array, no other text:
[
  {{
    "claim": "exact factual statement here",
    "source_url": "https://...",
    "source_name": "Publisher name",
    "type": "statistic|quote|date_event|product_fact|comparison|other",
    "confidence": "high|medium|low"
  }},
  ...
]

Confidence guide:
  high   = directly and explicitly stated in the source article
  medium = clearly implied or paraphrased from the source
  low    = inferred across multiple sources, less certain

Extract all claims now (aim for 10-20 claims):"""

    return prompt, meaningful_articles


def parse_claims_response(response_text, source_articles):
    """
    Parse the LLM's JSON response into a list of claim dicts.
    The LLM is instructed to output pure JSON — extract it cleanly.
    """
    # Strip any markdown code fences the LLM might add
    text = response_text.strip()
    if text.startswith("```"):
        # Remove first and last ``` lines
        lines = text.split("\n")
        # Find the first and last ``` lines and strip them
        start = next(i for i, l in enumerate(lines) if l.startswith("```"))
        end = next(i for i, l in enumerate(reversed(lines)) if l.startswith("```"))
        text = "\n".join(lines[start + 1: len(lines) - end - 1])

    claims = json.loads(text)

    # Validate each claim has required fields, fill defaults if missing
    cleaned = []
    valid_types = {"statistic", "quote", "date_event", "product_fact", "comparison", "other"}
    valid_confidence = {"high", "medium", "low"}

    for c in claims:
        if not c.get("claim"):
            continue
        cleaned.append({
            "claim":       c.get("claim", "").strip(),
            "source_url":  c.get("source_url", ""),
            "source_name": c.get("source_name", ""),
            "type":        c.get("type", "other") if c.get("type") in valid_types else "other",
            "confidence":  c.get("confidence", "medium") if c.get("confidence") in valid_confidence else "medium",
        })

    return cleaned


def run_claim_extractor(summary_path, selected_topic_path):
    """
    Main claim extraction function.
    Loads summary + selected topic, runs LLM extraction, returns claims dict.
    """
    summary_data = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    selected_topic_data = json.loads(Path(selected_topic_path).read_text(encoding="utf-8"))

    topic = summary_data.get("topic", "")
    print(f"  Topic: {topic}")
    print(f"  Summary: {summary_data['word_count']} words")
    print(f"  Sources to reference: {len(selected_topic_data.get('source_articles', []))}")

    # Build prompt
    prompt, meaningful_articles = build_prompt(summary_data, selected_topic_data)
    print(f"\n  Prompt built — {len(prompt):,} chars (~{len(prompt)//4:,} tokens) sent to LLM")

    # Call LLM with logging
    profile = get_profile(MODULE_NAME)
    llm = make_llm(**profile)

    response_text = call_llm(
        llm,
        prompt,
        module=MODULE_NAME,
        metadata={
            "topic": topic,
            "summary_word_count": summary_data.get("word_count", 0),
            "source_count": len(meaningful_articles),
        }
    )

    # Parse the response
    claims = parse_claims_response(response_text, meaningful_articles)

    return {
        "topic": topic,
        "generated_at": datetime.now().isoformat(),
        "llm_profile": profile,
        "total_claims": len(claims),
        "claims": claims,

        # Stats breakdown
        "by_type": _count_by(claims, "type"),
        "by_confidence": _count_by(claims, "confidence"),
        "by_source": _count_by_source(claims),
    }


def _count_by(claims, field):
    counts = {}
    for c in claims:
        val = c.get(field, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts


def _count_by_source(claims):
    counts = {}
    for c in claims:
        name = c.get("source_name", "unknown")
        counts[name] = counts.get(name, 0) + 1
    return counts


def save_claims(claims_data, date_str=None):
    """Save extracted claims to output/layer_3_intelligence/"""
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # Save alongside the other intel files (not in a subfolder — same level as summary)
    filepath = INTEL_OUTPUT / f"claims_{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(claims_data, f, indent=2, ensure_ascii=False)

    return filepath


def find_latest(directory, pattern):
    """Find the most recently created file matching a glob pattern."""
    candidates = sorted(Path(directory).glob(pattern), reverse=True)
    if not candidates:
        return None
    return candidates[0]


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract verifiable claims from summary")
    parser.add_argument("--summary", help="Path to summary JSON")
    parser.add_argument("--topic",   help="Path to selected_topic JSON (for source URLs)")
    args = parser.parse_args()

    # Resolve inputs — auto-detect latest if not provided
    summary_path = args.summary or find_latest(INTEL_SUMMARIES, "summary_*.json")
    topic_path   = args.topic   or find_latest(INTEL_OUTPUT,   "selected_topic_*.json")

    if not summary_path:
        print("No summary file found. Run summarizer.py first.")
        sys.exit(1)
    if not topic_path:
        print("No selected_topic file found. Run topic_selector.py first.")
        sys.exit(1)

    # Extract date from filename for saving
    date_str = Path(summary_path).stem.replace("summary_", "")

    print(f"Summary:       {summary_path}")
    print(f"Selected topic:{topic_path}")
    print()

    profile = get_profile(MODULE_NAME)
    print(f"LLM profile: {profile['provider']}/{profile['model']}")
    print()

    claims_data = run_claim_extractor(summary_path, topic_path)

    filepath = save_claims(claims_data, date_str)

    # Print results
    print()
    print(f"Extracted {claims_data['total_claims']} claims")
    print(f"  By type:       {claims_data['by_type']}")
    print(f"  By confidence: {claims_data['by_confidence']}")
    print(f"  By source:     {claims_data['by_source']}")
    print()
    print("Claims:")
    for i, c in enumerate(claims_data["claims"], start=1):
        conf_icon = {"high": "✓", "medium": "~", "low": "?"}.get(c["confidence"], "?")
        print(f"  {i:2}. [{conf_icon}] [{c['type']:12}] {c['claim'][:70]}")
        print(f"       → {c['source_name']} | {c['source_url'][:60]}")

    print()
    print(f"Saved to: {filepath}")
    print(f"\nNext: python pipelines/layer_3_intelligence/context_enricher.py")
