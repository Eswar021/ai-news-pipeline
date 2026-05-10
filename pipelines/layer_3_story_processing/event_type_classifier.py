"""
Layer 3 — Module 5: Event Type Classifier

Classifies each document's event type using:
  - source_group (research_papers → research_paper)
  - title keyword matching (priority ordered rules)
  - entity signals (model entity → more likely model_release)

Event types:
  model_release, product_launch, research_paper, benchmark_result,
  open_source_release, funding_or_acquisition, regulation_or_policy,
  partnership, pricing_or_plan_change, safety_or_risk_issue,
  community_controversy, infrastructure_or_chip_news, tutorial_or_demo, unknown

Zero LLM calls — all rule-based.

Usage:
    python event_type_classifier.py --run-id run_2026_05_10_48h_auto
"""

import re
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


# ── Keyword rules (evaluated in order; first match wins) ──────────────────────

_RULES: list[tuple[str, list[str], float]] = [
    # (event_type, keywords_in_title_or_text, base_confidence)
    ("model_release", [
        r"\bnew model\b", r"\bmodel release\b", r"\bintroducing .{0,30}(model|llm|gpt|claude|gemini|llama|qwen|mistral)",
        r"\blaunches?.{0,20}(model|llm)\b", r"\bopen.?sourc.{0,10}(model|weights)\b",
        r"\bintroducing (gpt|claude|gemini|llama|qwen|grok|o\d)",
        r"\b(gpt|claude|gemini|llama|qwen|grok|mistral|codex)[\s\-]?\d",
    ], 0.85),

    ("product_launch", [
        r"\bintroducing\b", r"\blaunche[sd]\b", r"\blaunch\b", r"\bannounce[sd]\b",
        r"\bnew (feature|product|tool|app|service|assistant|agent|platform)\b",
        r"\bnow available\b", r"\brolling out\b", r"\bships?\b",
    ], 0.78),

    ("benchmark_result", [
        r"\bbenchmark\b", r"\bstate.of.the.art\b", r"\bsota\b",
        r"\bsurpass\b", r"\boutperform\b", r"\bevaluation\b",
        r"\bscor(?:es?|ing)\b.{0,30}(percent|%|point)",
    ], 0.80),

    ("open_source_release", [
        r"\bopen.sourc\b", r"\bopen.weight\b", r"\bgithub.com\b",
        r"\bopen.releas\b", r"\bopen source\b", r"\bopen weights\b",
    ], 0.82),

    ("funding_or_acquisition", [
        r"\bfunding\b", r"\braised?\b.{0,20}\$", r"\$\d+.{0,10}(million|billion|m\b|b\b)",
        r"\bacquisition\b", r"\bacquired\b", r"\bmerger\b", r"\bipo\b",
        r"\binvestment\b", r"\bvaluation\b", r"\bseries [a-e]\b",
    ], 0.85),

    ("regulation_or_policy", [
        r"\bregulat\b", r"\bpolic\b", r"\blegislat\b", r"\bai act\b",
        r"\bgovernance\b", r"\bcompliance\b", r"\bban\b.{0,10}(ai|model)",
        r"\bsafety guidelin\b", r"\beu\b.{0,10}(ai|rule|law)",
    ], 0.82),

    ("pricing_or_plan_change", [
        r"\bpric\b", r"\bsubscription\b", r"\bplan\b.{0,10}(change|update|tier)",
        r"\bfree tier\b", r"\bads\b", r"\bmonetiz\b",
        r"\bpaywall\b", r"\bpremium\b",
    ], 0.80),

    ("safety_or_risk_issue", [
        r"\bsafety\b", r"\brisk\b", r"\bharm\b", r"\bjailbreak\b",
        r"\bvulnerabilit\b", r"\bexploit\b", r"\bhallucination\b",
        r"\bbiased?\b", r"\bmisuse\b", r"\bdanger\b",
    ], 0.75),

    ("infrastructure_or_chip_news", [
        r"\bchip\b", r"\bgpu\b", r"\bsemiconductor\b", r"\bdata center\b",
        r"\binfrastructure\b", r"\btpu\b", r"\bnpu\b", r"\bcompute\b.{0,20}(cloud|hardware)",
        r"\bcluster\b.{0,20}(gpu|compute)", r"\bnvidia\b",
    ], 0.80),

    ("partnership", [
        r"\bpartnership\b", r"\bcollaborat\b", r"\bintegrat\b.{0,20}(with|into)",
        r"\bpowered by\b", r"\bteams up\b", r"\bworks with\b",
    ], 0.75),

    ("community_controversy", [
        r"\bcontroversy\b", r"\bdebate\b", r"\bcriticism\b", r"\bcriticiz\b",
        r"\bbacklash\b", r"\bconcern\b", r"\bworried\b", r"\bmiserable\b",
        r"\bproblem\b.{0,20}(with|in)\b",
    ], 0.70),

    ("tutorial_or_demo", [
        r"\btutorial\b", r"\bhow to\b", r"\bguide\b", r"\bwalkthrough\b",
        r"\bdemonstrat\b", r"\bdemo\b", r"\bexample\b.{0,10}(code|use|using)",
    ], 0.70),
]

_COMPILED_RULES: list[tuple[str, list[re.Pattern], float]] = [
    (event_type, [re.compile(kw, re.IGNORECASE) for kw in keywords], conf)
    for event_type, keywords, conf in _RULES
]


def classify(doc: dict, entity_map: dict | None = None) -> dict:
    """
    Classify a document's event type.

    Args:
        doc:        canonical document dict
        entity_map: output from entity_topic_mapper for this doc (optional)

    Returns:
        {
            "canonical_document_id": str,
            "event_type": str,
            "event_type_confidence": float,
            "event_type_reasons": [str],
        }
    """
    doc_id = doc["canonical_document_id"]
    source_group = doc.get("source_group", "")
    title = (doc.get("title") or "").strip()
    search_text = title[:300]

    reasons = []

    # ── Source-group hard rules ────────────────────────────────────────────────
    if source_group == "research_papers":
        return {
            "canonical_document_id": doc_id,
            "event_type":            "research_paper",
            "event_type_confidence": 0.95,
            "event_type_reasons":    ["source_group_is_research_papers"],
        }

    if source_group == "github_open_source_signals":
        return {
            "canonical_document_id": doc_id,
            "event_type":            "open_source_release",
            "event_type_confidence": 0.88,
            "event_type_reasons":    ["source_group_is_github"],
        }

    if source_group == "youtube_podcast_transcripts":
        return {
            "canonical_document_id": doc_id,
            "event_type":            "tutorial_or_demo",
            "event_type_confidence": 0.75,
            "event_type_reasons":    ["source_group_is_youtube"],
        }

    # ── Keyword matching ───────────────────────────────────────────────────────
    best_event = "unknown"
    best_conf  = 0.0
    best_reasons: list[str] = []

    for event_type, patterns, base_conf in _COMPILED_RULES:
        matched_keywords = [p.pattern[:40] for p in patterns if p.search(search_text)]
        if matched_keywords:
            # Boost if it's an official blog (product_launch/model_release are more likely)
            conf = base_conf
            if source_group == "ai_company_blogs" and event_type in (
                "model_release", "product_launch", "pricing_or_plan_change"
            ):
                conf = min(conf + 0.05, 0.95)
                reasons.append("official_blog_boost")

            if conf > best_conf:
                best_conf   = conf
                best_event  = event_type
                best_reasons = [f"keyword:{kw}" for kw in matched_keywords[:3]]

    # ── Entity boost for model_release ────────────────────────────────────────
    if entity_map and best_event in ("product_launch", "unknown"):
        if entity_map.get("entities", {}).get("models"):
            best_event = "model_release"
            best_conf  = max(best_conf, 0.78)
            best_reasons.append("model_entity_detected")

    # ── Community signals default ──────────────────────────────────────────────
    if best_event == "unknown" and source_group == "community_signals":
        best_event = "community_controversy"
        best_conf  = 0.45
        best_reasons = ["community_signal_fallback"]

    if best_event == "unknown" and source_group == "ai_company_blogs":
        best_event = "product_launch"
        best_conf  = 0.60
        best_reasons = ["official_blog_fallback"]

    return {
        "canonical_document_id": doc_id,
        "event_type":            best_event,
        "event_type_confidence": round(best_conf, 3),
        "event_type_reasons":    (best_reasons + reasons)[:6],
    }


def classify_all(docs: list[dict], entity_maps: list[dict] | None = None) -> list[dict]:
    entity_index = {}
    if entity_maps:
        entity_index = {e["canonical_document_id"]: e for e in entity_maps}

    return [classify(doc, entity_index.get(doc["canonical_document_id"])) for doc in docs]


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

    results = classify_all(docs)

    from collections import Counter
    print(f"\nEvent Type Classifier — {run_id}")
    print(f"  Processed: {len(results)} docs")
    counts = Counter(r["event_type"] for r in results)
    print("\n  Event type distribution:")
    for ev, n in counts.most_common():
        print(f"    {ev:35}: {n}")
    print("\n  Sample blog classifications:")
    blog_results = [(d, r) for d, r in zip(docs, results) if d["source_group"] == "ai_company_blogs"][:6]
    for doc, r in blog_results:
        print(f"    {doc['title'][:55]:55} → {r['event_type']} ({r['event_type_confidence']})")
