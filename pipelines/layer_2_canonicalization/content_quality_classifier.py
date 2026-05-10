"""
Layer 2 — Module 5: Content Quality Classifier

Assigns quality score, content completeness, and usability flags.

content_completeness values:
  full            — complete article / full transcript
  partial         — truncated snippet or partial fetch
  abstract_only   — research paper with only abstract
  title_only      — HN/community post with no body text
  metadata_only   — GitHub repo stats, no README

Quality score (0.0 – 1.0):
  Full article (>1500 chars clean)   → 0.85 – 0.95
  Good article (500–1500 chars)      → 0.65 – 0.85
  Short snippet (100–500 chars)      → 0.40 – 0.65
  Very short (<100 chars)            → 0.20 – 0.40
  Empty                              → 0.10

Research abstracts get a quality bonus (they're intentionally abstract_only,
not accidentally partial).

Usability flags:
  usable_for_story_clustering  — true if we have title + any content signal
  usable_for_claim_extraction  — true if full/abstract_only with >200 chars
  usable_for_trend_signal      — true for community/news even if partial

Usage:
    python content_quality_classifier.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def classify(clean_text: str, source_group: str,
             layer1_content_available: str = "",
             title: str = "") -> dict:
    """
    Classify content quality.

    Args:
        clean_text:                 Cleaned text from content_cleaner
        source_group:               e.g. "research_papers"
        layer1_content_available:   Layer 1 content_available field if present
        title:                      Document title (used if text is empty)

    Returns:
        {
            "content_completeness": str,
            "word_count": int,
            "char_count": int,
            "quality_score": float,
            "usable_for_story_clustering": bool,
            "usable_for_claim_extraction": bool,
            "usable_for_trend_signal": bool,
            "quality_warnings": [str],
        }
    """
    char_count = len(clean_text)
    word_count = len(clean_text.split()) if clean_text else 0
    warnings   = []

    # ── Determine content_completeness ────────────────────────────────────────
    if layer1_content_available == "title_only" or (char_count == 0 and title):
        completeness = "title_only"
    elif layer1_content_available == "partial" or (
        clean_text and clean_text.rstrip().endswith("…") and char_count < 500
    ):
        completeness = "partial"
    elif source_group == "research_papers":
        completeness = "abstract_only"
    elif source_group == "github_open_source_signals" and char_count < 300:
        completeness = "metadata_only"
    elif char_count > 800:
        completeness = "full"
    elif char_count > 100:
        completeness = "partial"
    elif char_count > 0:
        completeness = "partial"
    else:
        completeness = "title_only"

    # ── Quality score ─────────────────────────────────────────────────────────
    if completeness == "title_only":
        score = 0.15
        warnings.append("title_only_no_body_text")
    elif completeness == "metadata_only":
        score = 0.20
        warnings.append("metadata_only")
    elif completeness == "abstract_only":
        # Abstracts are intentionally short but high quality — research-grade
        if char_count >= 300:
            score = 0.75
        elif char_count >= 100:
            score = 0.55
        else:
            score = 0.35
            warnings.append("very_short_abstract")
    elif completeness == "partial":
        if char_count >= 400:
            score = 0.55
        elif char_count >= 150:
            score = 0.40
        else:
            score = 0.25
            warnings.append("very_short_snippet")
    else:  # full
        if char_count >= 3000:
            score = 0.92
        elif char_count >= 1500:
            score = 0.85
        elif char_count >= 800:
            score = 0.72
        else:
            score = 0.60

    # Bonus for research papers regardless of length
    if source_group == "research_papers":
        score = min(1.0, score + 0.05)

    # ── Usability flags ───────────────────────────────────────────────────────
    has_title   = bool(title and title.strip())
    has_content = char_count >= 50

    usable_for_story_clustering = has_title or has_content
    usable_for_claim_extraction = (
        has_content and char_count >= 200 and
        completeness in ("full", "abstract_only")
    )
    usable_for_trend_signal = has_title or (
        source_group in ("community_signals", "tech_news_apis")
    )

    if not usable_for_claim_extraction and completeness == "partial" and char_count >= 150:
        warnings.append("partial_content_not_suitable_for_claim_extraction")

    return {
        "content_completeness":        completeness,
        "word_count":                  word_count,
        "char_count":                  char_count,
        "quality_score":               round(score, 3),
        "usable_for_story_clustering": usable_for_story_clustering,
        "usable_for_claim_extraction": usable_for_claim_extraction,
        "usable_for_trend_signal":     usable_for_trend_signal,
        "quality_warnings":            warnings,
    }


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from pipelines.layer_2_canonicalization.content_cleaner import clean as clean_text

    if args.run_id:
        run_id = args.run_id
    else:
        run_dirs = sorted(RUNS_DIR.glob("*/run_manifest.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = run_dirs[0].parent.name
        print(f"Auto-discovered run: {run_id}")

    raw_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    docs = [json.loads(l) for l in raw_path.read_text().splitlines() if l.strip()]

    print(f"\nContent Quality Classifier — {run_id}")
    seen = set()
    for doc in docs:
        sg = doc["source"]["source_group"]
        if sg in seen:
            continue
        seen.add(sg)
        title    = doc["item"].get("title", "")
        raw      = doc["content"].get("raw_text", "")
        ca       = doc["content"].get("content_available", "")
        cleaned  = clean_text(raw, sg, title)["clean_text"]
        result   = classify(cleaned, sg, ca, title)
        print(f"  [{sg}]")
        print(f"  Title         : {title[:65]}")
        print(f"  Completeness  : {result['content_completeness']}")
        print(f"  Chars         : {result['char_count']}  Words: {result['word_count']}")
        print(f"  Quality score : {result['quality_score']}")
        print(f"  Claim extract : {result['usable_for_claim_extraction']}")
        print(f"  Trend signal  : {result['usable_for_trend_signal']}")
        print(f"  Warnings      : {result['quality_warnings']}")
        print()
