"""
Layer 2 — Module 6: Trust Tier + Source Role Tagger

Assigns trust_tier, source_role, and usage flags per document.

Trust tiers:
  1    — official company blog / official docs
  1.5  — research paper (academic)
  2    — reputable news/tech publication
  2.5  — GitHub repo / open-source technical artifact
  3    — community signal (HN, Reddit, etc.)
  4    — weak or unknown source

Source roles:
  primary_evidence    — official source, can support factual claims
  research_evidence   — peer-reviewed or preprint, can support technical claims
  secondary_evidence  — reputable media, can support factual claims with caveats
  technical_artifact  — GitHub repo, can support technical facts (stars, license, etc.)
  trend_signal_only   — community signal, cannot be treated as truth
  not_for_claims      — metadata-only, too weak for any claim

Usage flags:
  can_support_factual_claims     — source can back a script claim
  can_support_technical_claims   — source can back a code/model claim
  can_support_trend_signal       — source signals audience interest
  can_support_quote              — source text can be quoted verbatim in script

Usage:
    python trust_tier_tagger.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


_GROUP_TRUST = {
    "ai_company_blogs": {
        "trust_tier":   1,
        "source_role":  "primary_evidence",
        "can_support_factual_claims":   True,
        "can_support_technical_claims": True,
        "can_support_trend_signal":     False,
        "can_support_quote":            True,
    },
    "research_papers": {
        "trust_tier":   1.5,
        "source_role":  "research_evidence",
        "can_support_factual_claims":   True,
        "can_support_technical_claims": True,
        "can_support_trend_signal":     False,
        "can_support_quote":            True,
    },
    "tech_news_apis": {
        "trust_tier":   2,
        "source_role":  "secondary_evidence",
        "can_support_factual_claims":   True,
        "can_support_technical_claims": False,
        "can_support_trend_signal":     True,
        "can_support_quote":            False,
    },
    "github_open_source_signals": {
        "trust_tier":   2.5,
        "source_role":  "technical_artifact",
        "can_support_factual_claims":   True,
        "can_support_technical_claims": True,
        "can_support_trend_signal":     True,
        "can_support_quote":            False,
    },
    "community_signals": {
        "trust_tier":   3,
        "source_role":  "trend_signal_only",
        "can_support_factual_claims":   False,
        "can_support_technical_claims": False,
        "can_support_trend_signal":     True,
        "can_support_quote":            False,
    },
    "youtube_podcast_transcripts": {
        "trust_tier":   2,
        "source_role":  "secondary_evidence",
        "can_support_factual_claims":   True,
        "can_support_technical_claims": False,
        "can_support_trend_signal":     True,
        "can_support_quote":            True,
    },
}

_DEFAULT_TRUST = {
    "trust_tier":   4,
    "source_role":  "not_for_claims",
    "can_support_factual_claims":   False,
    "can_support_technical_claims": False,
    "can_support_trend_signal":     False,
    "can_support_quote":            False,
}


def tag(doc: dict, content_completeness: str = "full") -> dict:
    """
    Assign trust tier and source role to a document.

    Args:
        doc:                   Layer 1 raw document dict
        content_completeness:  From content_quality_classifier

    Returns:
        Trust record dict.
    """
    source       = doc.get("source", {})
    source_group = source.get("source_group", "")
    hint         = source.get("trust_tier_hint")

    trust = _GROUP_TRUST.get(source_group, _DEFAULT_TRUST).copy()

    # Respect Layer 1 hint if it's more conservative (higher tier number = less trust)
    if hint is not None and float(hint) > trust["trust_tier"]:
        trust["trust_tier"] = float(hint)

    # Downgrade claim usability if content is incomplete
    if content_completeness == "title_only":
        trust["can_support_factual_claims"]   = False
        trust["can_support_technical_claims"] = False
        trust["can_support_quote"]            = False
    elif content_completeness == "metadata_only":
        trust["can_support_factual_claims"]   = False
        trust["can_support_technical_claims"] = False
        trust["can_support_quote"]            = False

    return trust


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

    print(f"\nTrust Tier Tagger — {run_id}")
    seen = set()
    for doc in docs:
        sg = doc["source"]["source_group"]
        if sg in seen:
            continue
        seen.add(sg)
        trust = tag(doc, content_completeness="full")
        print(f"  [{sg}]")
        print(f"  trust_tier             : {trust['trust_tier']}")
        print(f"  source_role            : {trust['source_role']}")
        print(f"  can_support_factual    : {trust['can_support_factual_claims']}")
        print(f"  can_support_technical  : {trust['can_support_technical_claims']}")
        print(f"  can_support_trend      : {trust['can_support_trend_signal']}")
        print(f"  can_support_quote      : {trust['can_support_quote']}")
        print()
