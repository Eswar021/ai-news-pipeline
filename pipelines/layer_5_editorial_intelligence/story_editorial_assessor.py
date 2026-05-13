"""
Layer 5 — Story Editorial Assessor

Builds one compact editorial assessment per story by combining:
- evidence safety
- editorial relevance
- viewer value
- novelty
- format-specific scoring and recommendation
"""

from __future__ import annotations

_ROUNDUP_TIMELINESS = {
    "model_release": 88,
    "product_launch": 85,
    "feature_release": 85,
    "pricing_or_plan_change": 82,
    "infrastructure_or_chip_news": 75,
    "funding_or_acquisition": 72,
    "partnership": 68,
    "ai_safety": 70,
    "research_paper": 55,
    "tutorial_or_demo": 60,
    "regulatory": 65,
    "unknown": 55,
}


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _deep_dive_density_score(candidate: dict) -> int:
    verified = int(candidate.get("verified_claim_count", 0) or 0)
    if verified >= 20:
        return 100
    if verified >= 15:
        return 90
    if verified >= 8:
        return 70 + ((verified - 8) * 4)
    return verified * 8


def _roundup_score(candidate: dict, editorial_relevance: dict, viewer_value: dict, novelty: dict) -> int:
    story_type = candidate.get("story_type", "unknown") or "unknown"
    return _clamp(
        editorial_relevance.get("audience_fit_score", 60) * 0.35
        + viewer_value.get("viewer_value_score", 60) * 0.35
        + novelty.get("novelty_score", 70) * 0.15
        + _ROUNDUP_TIMELINESS.get(story_type, 60) * 0.15
    )


def _deep_dive_score(candidate: dict, editorial_relevance: dict, viewer_value: dict, novelty: dict) -> int:
    primary_bonus = 100 if int(candidate.get("primary_source_count", 0) or 0) > 0 else 55
    return _clamp(
        editorial_relevance.get("audience_fit_score", 60) * 0.30
        + viewer_value.get("viewer_value_score", 60) * 0.30
        + _deep_dive_density_score(candidate) * 0.25
        + novelty.get("novelty_score", 70) * 0.10
        + primary_bonus * 0.05
    )


def assess_one(
    candidate: dict,
    evidence_safety: dict,
    editorial_relevance: dict,
    viewer_value: dict,
    novelty: dict,
    *,
    allowed_formats: list[str],
    policy: dict,
) -> dict:
    novelty_skip_threshold = int(policy.get("novelty_skip_threshold", 45))
    roundup_min_score = int(policy.get("roundup_min_selection_score", 65))
    deep_dive_min_score = int(policy.get("deep_dive_min_selection_score", 80))

    format_scores = {}
    eligible_formats = []
    selection_reasons = []

    if novelty.get("novelty_score", 90) < novelty_skip_threshold:
        return {
            "story_id": candidate["story_id"],
            "story_title": candidate.get("story_title", ""),
            "evidence_gate": evidence_safety,
            "editorial_relevance": editorial_relevance,
            "viewer_value": viewer_value,
            "novelty": novelty,
            "format_scores": {},
            "eligible_formats": [],
            "recommended_format": "skip",
            "selection_score": 0,
            "selection_reason": "Novelty below profile threshold; skip for now.",
        }

    if evidence_safety.get("overall_status") != "safe":
        return {
            "story_id": candidate["story_id"],
            "story_title": candidate.get("story_title", ""),
            "evidence_gate": evidence_safety,
            "editorial_relevance": editorial_relevance,
            "viewer_value": viewer_value,
            "novelty": novelty,
            "format_scores": {},
            "eligible_formats": [],
            "recommended_format": "monitor_only",
            "selection_score": 0,
            "selection_reason": "No allowed format cleared the evidence gate.",
        }

    if "roundup" in allowed_formats:
        roundup_score = _roundup_score(candidate, editorial_relevance, viewer_value, novelty)
        format_scores["roundup"] = roundup_score
        if evidence_safety["formats"]["roundup"]["status"] == "safe" and roundup_score >= roundup_min_score:
            eligible_formats.append("roundup")
            selection_reasons.append(f"Roundup score {roundup_score} met profile threshold.")

    if "deep_dive" in allowed_formats:
        deep_dive_score = _deep_dive_score(candidate, editorial_relevance, viewer_value, novelty)
        format_scores["deep_dive"] = deep_dive_score
        if evidence_safety["formats"]["deep_dive"]["status"] == "safe" and deep_dive_score >= deep_dive_min_score:
            eligible_formats.append("deep_dive")
            selection_reasons.append(f"Deep dive score {deep_dive_score} met profile threshold.")

    if not eligible_formats:
        return {
            "story_id": candidate["story_id"],
            "story_title": candidate.get("story_title", ""),
            "evidence_gate": evidence_safety,
            "editorial_relevance": editorial_relevance,
            "viewer_value": viewer_value,
            "novelty": novelty,
            "format_scores": format_scores,
            "eligible_formats": [],
            "recommended_format": "monitor_only",
            "selection_score": max(format_scores.values()) if format_scores else 0,
            "selection_reason": "Story is interesting but did not clear the current format thresholds.",
        }

    if "deep_dive" in eligible_formats and "roundup" in eligible_formats:
        recommended_format = "deep_dive" if format_scores["deep_dive"] >= format_scores["roundup"] else "roundup"
    else:
        recommended_format = eligible_formats[0]

    return {
        "story_id": candidate["story_id"],
        "story_title": candidate.get("story_title", ""),
        "evidence_gate": evidence_safety,
        "editorial_relevance": editorial_relevance,
        "viewer_value": viewer_value,
        "novelty": novelty,
        "format_scores": format_scores,
        "eligible_formats": eligible_formats,
        "recommended_format": recommended_format,
        "selection_score": format_scores.get(recommended_format, 0),
        "selection_reason": " ".join(selection_reasons) or "Eligible for editorial selection.",
    }


def assess_all(
    candidates: list[dict],
    evidence_safety_results: list[dict],
    editorial_relevance_results: list[dict],
    viewer_value_results: list[dict],
    novelty_results: list[dict],
    *,
    allowed_formats: list[str],
    policy: dict,
) -> list[dict]:
    return [
        assess_one(
            candidate,
            evidence_safety,
            editorial_relevance,
            viewer_value,
            novelty,
            allowed_formats=allowed_formats,
            policy=policy,
        )
        for candidate, evidence_safety, editorial_relevance, viewer_value, novelty in zip(
            candidates,
            evidence_safety_results,
            editorial_relevance_results,
            viewer_value_results,
            novelty_results,
        )
    ]
