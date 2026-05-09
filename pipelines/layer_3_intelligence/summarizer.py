"""
Summarizer — Layer 3, Module 2

Takes all source articles from the selected topic and produces a single
comprehensive narrative synthesis. This is the first "real" LLM work —
reading 6 different perspectives on the same story and producing one
coherent, research-grade summary.

What it does:
  - Filters out articles with no meaningful content (< 200 chars)
  - Sorts articles by trust tier (best source first in the prompt)
  - Sends all article texts to LLM with a focused synthesis prompt
  - Preserves specific numbers, benchmarks, quotes, and dates
  - Notes where sources agree or provide unique angles

Output: summary_YYYY-MM-DD.json — consumed by claim_extractor.py next.

Usage:
    python summarizer.py                                        # uses today's selected topic
    python summarizer.py --input output/.../selected_topic_2026-05-08.json
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import INTEL_OUTPUT, INTEL_SUMMARIES, ensure_output_dirs
from config.llm_config import get_profile
from llm.llm_client import make_llm
from llm.llm_logger import call_llm


MODULE_NAME = "summarizer"

# Only include articles with at least this many chars of text — below this is just a title
MIN_TEXT_LEN = 200


def filter_articles(articles):
    """
    Keep only articles with meaningful content.
    Sort by trust tier (Tier 1 first) so the best sources appear first in the prompt.
    """
    meaningful = [a for a in articles if len(a.get("raw_text", "")) >= MIN_TEXT_LEN]
    # Sort ascending by trust_tier — 1 (official) comes before 3 (community)
    meaningful.sort(key=lambda a: a.get("trust_tier", 3))
    return meaningful


def build_articles_block(articles):
    """
    Build the articles section of the prompt — each article clearly labelled
    with its source type, publisher, and trust tier so the LLM understands
    which sources are authoritative vs. community discussion.
    """
    tier_labels = {
        1: "Official Company Source",
        1.5: "Research Paper / Academic",
        2: "Established Media",
        3: "Community Discussion",
    }

    blocks = []
    for i, a in enumerate(articles, start=1):
        tier = a.get("trust_tier", 3)
        tier_label = tier_labels.get(tier, f"Tier {tier}")
        publisher = a.get("publisher", "Unknown")
        title = a.get("title", "")
        url = a.get("url", "")
        raw_text = a.get("raw_text", "")

        block = f"""--- SOURCE {i}: {publisher} [{tier_label}] ---
Title: {title}
URL: {url}
Content:
{raw_text}
"""
        blocks.append(block)

    return "\n".join(blocks)


def build_prompt(topic_data, articles):
    """
    Build the synthesis prompt. The LLM is told it's a research analyst
    synthesizing multiple sources — not a writer yet. Just synthesis of facts.
    """
    best_title = topic_data.get("best_title", topic_data.get("topic", ""))
    articles_block = build_articles_block(articles)
    n = len(articles)

    prompt = f"""You are a senior research analyst for an AI news organization. Your job is to synthesize multiple sources about the same topic into one comprehensive, factually accurate summary.

Topic: {best_title}

Below are {n} source articles about this topic, ordered from most authoritative to least authoritative.

{articles_block}

---

Write a comprehensive synthesis of these sources. Follow these rules:

1. PRESERVE ALL SPECIFICS — keep every number, percentage, benchmark score, date, model name, and direct quote exactly as stated in the sources
2. ATTRIBUTE FACTS — when stating a key fact, note which source it comes from (e.g. "According to Anthropic's official blog..." or "The research paper notes...")
3. COVER ALL ANGLES — each source may add unique information. Make sure all meaningful angles are covered
4. NOTE DISAGREEMENTS — if sources present different numbers or perspectives, mention both
5. LENGTH — aim for 400-700 words. Enough to cover everything, not so long it's padded
6. TONE — factual, journalistic, neutral. No hype. No opinions.

Write the synthesis now:"""

    return prompt


def run_summarizer(selected_topic_path):
    """
    Main summarizer function. Loads selected topic, runs LLM synthesis,
    returns the summary dict.
    """
    topic_data = json.loads(Path(selected_topic_path).read_text(encoding="utf-8"))
    all_articles = topic_data.get("source_articles", [])

    # Filter to only meaningful articles
    articles = filter_articles(all_articles)
    skipped = len(all_articles) - len(articles)

    print(f"  Source articles: {len(all_articles)} total, {len(articles)} with content, {skipped} skipped (too short)")
    for a in articles:
        print(f"    [Tier {a['trust_tier']}] {len(a['raw_text']):6} chars | {a['publisher']:20} | {a['title'][:45]}")

    # Build prompt
    prompt = build_prompt(topic_data, articles)
    total_chars = sum(len(a.get("raw_text", "")) for a in articles)
    print(f"\n  Prompt built — {len(prompt):,} chars (~{len(prompt)//4:,} tokens) sent to LLM")

    # Call LLM with logging
    profile = get_profile(MODULE_NAME)
    llm = make_llm(**profile)

    summary_text = call_llm(
        llm,
        prompt,
        module=MODULE_NAME,
        metadata={
            "topic": topic_data.get("best_title", ""),
            "articles_count": len(articles),
            "skipped_count": skipped,
            "total_source_chars": total_chars,
        }
    )

    return {
        "topic": topic_data.get("best_title", ""),
        "generated_at": datetime.now().isoformat(),
        "llm_profile": profile,
        "articles_used": len(articles),
        "articles_skipped": skipped,
        "source_urls": [a["url"] for a in articles],
        "summary_text": summary_text,
        "word_count": len(summary_text.split()),
    }


def save_summary(summary, date_str=None):
    """Save summary to output/layer_3_intelligence/summaries/"""
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    filepath = INTEL_SUMMARIES / f"summary_{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthesize source articles into one summary")
    parser.add_argument("--input", help="Path to selected_topic JSON (default: today's)")
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")

    if args.input:
        input_path = args.input
    else:
        # Find the most recent selected_topic file (handles cross-day runs)
        candidates = sorted(INTEL_OUTPUT.glob("selected_topic_*.json"), reverse=True)
        if not candidates:
            print("No selected_topic file found. Run topic_selector.py first.")
            sys.exit(1)
        input_path = candidates[0]
        # Extract the date from the filename for saving the output with matching date
        date_str = input_path.stem.replace("selected_topic_", "")

    print(f"Loading: {input_path}")
    print()

    profile = get_profile(MODULE_NAME)
    print(f"LLM profile: {profile['provider']}/{profile['model']}")
    print()

    summary = run_summarizer(input_path)

    filepath = save_summary(summary, date_str)

    print()
    print(f"Summary: {summary['word_count']} words")
    print(f"Saved to: {filepath}")
    print()
    print("--- SUMMARY ---")
    print(summary["summary_text"])
    print()
    print(f"Next: python pipelines/layer_3_intelligence/claim_extractor.py")
