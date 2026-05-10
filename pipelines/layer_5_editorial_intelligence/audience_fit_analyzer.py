"""
Layer 5 — Module 3: Audience Fit Analyzer

Rule-based scoring of how well each story matches the channel's audience.
Also computes impact dimensions (merged from design module 5.6).

Audience: technical_but_accessible (AI developers and tech professionals)
Channel: AI Signal Brief — evidence-first, practical, low-hype

Scoring components:
  topic_relevance     — how well the story's topics match channel focus
  entity_relevance    — how known/relevant the entities are to the audience
  practical_usefulness — can the viewer take something away?
  technical_accessibility — can this be explained clearly to the audience?

Impact dimensions (from 5.6):
  developer_impact, consumer_impact, enterprise_impact, research_impact

Key function:
    analyze_all(candidates) → list of audience_fit dicts

Usage:
    python audience_fit_analyzer.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

# ── Story type → base audience fit ────────────────────────────────────────────
_TYPE_BASE_SCORE = {
    "model_release":              88,
    "product_launch":             82,
    "feature_release":            82,
    "pricing_or_plan_change":     78,
    "research_paper":             72,
    "infrastructure_or_chip_news": 68,
    "ai_safety":                  74,
    "partnership":                62,
    "funding_or_acquisition":     58,
    "tutorial_or_demo":           65,
    "regulatory":                 56,
    "unknown":                    50,
}

# ── Topic keywords → relevance bonus ──────────────────────────────────────────
_TOPIC_BONUSES = {
    "coding":      8,
    "agent":       8,
    "workflow":    7,
    "developer":   7,
    "api":         6,
    "open-source": 6,
    "benchmark":   5,
    "model":       5,
    "safety":      4,
    "enterprise":  3,
    "business":    2,
    "infrastructure": 3,
    "voice":       4,
}

# ── Major AI entities known to the audience ────────────────────────────────────
_MAJOR_ENTITIES = {
    "openai", "anthropic", "google", "deepmind", "meta", "mistral",
    "hugging face", "stability", "cohere", "nvidia", "microsoft",
    "amazon", "aws", "apple", "xai", "inflection", "together",
}

# ── Story type → impact dimensions ────────────────────────────────────────────
_TYPE_IMPACT = {
    "model_release":               {"developer": 85, "consumer": 60, "enterprise": 70, "research": 40},
    "product_launch":              {"developer": 75, "consumer": 65, "enterprise": 72, "research": 20},
    "feature_release":             {"developer": 80, "consumer": 55, "enterprise": 68, "research": 15},
    "pricing_or_plan_change":      {"developer": 82, "consumer": 70, "enterprise": 85, "research": 10},
    "research_paper":              {"developer": 60, "consumer": 20, "enterprise": 35, "research": 90},
    "infrastructure_or_chip_news": {"developer": 65, "consumer": 20, "enterprise": 75, "research": 40},
    "ai_safety":                   {"developer": 55, "consumer": 40, "enterprise": 50, "research": 70},
    "partnership":                 {"developer": 50, "consumer": 35, "enterprise": 80, "research": 20},
    "funding_or_acquisition":      {"developer": 40, "consumer": 25, "enterprise": 75, "research": 15},
    "tutorial_or_demo":            {"developer": 75, "consumer": 50, "enterprise": 40, "research": 10},
    "regulatory":                  {"developer": 45, "consumer": 55, "enterprise": 70, "research": 30},
    "unknown":                     {"developer": 45, "consumer": 35, "enterprise": 45, "research": 20},
}

# ── Topic keywords → developer impact boost ───────────────────────────────────
_DEV_TOPIC_BOOST = {"coding", "agent", "workflow", "api", "developer", "open-source"}


def _topic_bonus(topics: list[str]) -> int:
    bonus = 0
    combined = " ".join(topics).lower()
    for keyword, val in _TOPIC_BONUSES.items():
        if keyword in combined:
            bonus += val
    return min(bonus, 20)  # cap bonus at 20


def _entity_known(companies: list[str]) -> bool:
    for c in companies:
        if any(maj in c.lower() for maj in _MAJOR_ENTITIES):
            return True
    return False


def _technical_accessibility(story_type: str) -> int:
    # research_paper is harder to make accessible; product launches are easiest
    accessibility_map = {
        "model_release": 85,
        "product_launch": 90,
        "feature_release": 88,
        "pricing_or_plan_change": 92,
        "research_paper": 60,
        "infrastructure_or_chip_news": 70,
        "ai_safety": 75,
        "tutorial_or_demo": 88,
        "partnership": 85,
        "funding_or_acquisition": 88,
        "regulatory": 72,
        "unknown": 65,
    }
    return accessibility_map.get(story_type, 70)


def _impact_dimensions(story_type: str, topics: list[str]) -> dict:
    base = dict(_TYPE_IMPACT.get(story_type, _TYPE_IMPACT["unknown"]))
    # Boost developer impact if coding/agent topics present
    combined = " ".join(topics).lower()
    if any(kw in combined for kw in _DEV_TOPIC_BOOST):
        base["developer"] = min(base["developer"] + 10, 100)
    return base


def _audience_segment(story_type: str, topics: list[str]) -> str:
    combined = " ".join(topics).lower()
    if "coding" in combined or "developer" in combined or "api" in combined:
        return "AI developers and engineers"
    if story_type == "research_paper":
        return "ML researchers and technical professionals"
    if story_type in ("pricing_or_plan_change", "funding_or_acquisition"):
        return "Tech professionals and startup founders"
    return "AI-curious developers and tech professionals"


def _audience_risk(audience_fit_score: int, story_type: str) -> str:
    if story_type == "research_paper" or audience_fit_score < 60:
        return "medium"
    if audience_fit_score < 50:
        return "high"
    return "low"


def analyze(candidate: dict) -> dict:
    story_type = candidate.get("story_type", "unknown") or "unknown"
    topics     = candidate.get("topics", [])
    companies  = candidate.get("companies", [])

    base_score    = _TYPE_BASE_SCORE.get(story_type, 50)
    topic_bonus   = _topic_bonus(topics)
    entity_bonus  = 5 if _entity_known(companies) else -5
    practical     = min(base_score + topic_bonus // 2, 95)
    accessibility = _technical_accessibility(story_type)

    # Weighted composite
    fit_score = int(
        base_score   * 0.35 +
        (base_score + topic_bonus) * 0.25 +   # topic_relevance
        practical    * 0.25 +
        accessibility * 0.15 +
        entity_bonus
    )
    fit_score = max(min(fit_score, 100), 10)

    impact     = _impact_dimensions(story_type, topics)
    main_impact = max(impact, key=impact.get)

    fit_reasons = []
    if topic_bonus >= 10:
        fit_reasons.append("Strong topic match with channel focus.")
    if _entity_known(companies):
        fit_reasons.append(f"Major AI entity ({', '.join(companies[:2])}) known to audience.")
    if accessibility >= 85:
        fit_reasons.append("Story can be explained clearly without excessive technical depth.")
    if impact["developer"] >= 75:
        fit_reasons.append("Directly relevant to developer workflow or AI tools.")
    if not fit_reasons:
        fit_reasons.append("Moderate match with channel thesis and audience profile.")

    return {
        "story_id":            candidate["story_id"],
        "audience_fit_score":  fit_score,
        "best_audience_segment": _audience_segment(story_type, topics),
        "fit_reasons":         fit_reasons,
        "audience_risk":       _audience_risk(fit_score, story_type),
        "impact_dimensions": {
            "developer_impact":   impact["developer"],
            "consumer_impact":    impact["consumer"],
            "enterprise_impact":  impact["enterprise"],
            "research_impact":    impact["research"],
            "main_impact_dimension": main_impact,
        },
    }


def analyze_all(candidates: list[dict]) -> list[dict]:
    return [analyze(c) for c in candidates]


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_4" / "story_fact_sheets.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_5_editorial_intelligence.editorial_candidate_loader import load
    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result = load(run_id, layer3_dir, layer4_dir)
    candidates = result["editorial_candidates"]

    fit_results = analyze_all(candidates)
    print(f"\nAudience Fit Analyzer — {run_id}")
    for cand, af in zip(candidates, fit_results):
        print(f"  {cand['story_title'][:48]:48s}  "
              f"fit={af['audience_fit_score']:3d}  "
              f"risk={af['audience_risk']:<6}  "
              f"dev_impact={af['impact_dimensions']['developer_impact']}")
