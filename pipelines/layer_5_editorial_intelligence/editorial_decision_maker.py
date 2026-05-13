"""
Layer 5 — Editorial Decision Maker

Selects the run-level video decision from the compact story editorial assessments.
"""

from __future__ import annotations


def _entity_name(candidate: dict) -> str:
    companies = candidate.get("companies", [])
    return companies[0].lower() if companies else "unknown"


def _roundup_episode_theme(selected: list[dict]) -> str:
    companies = list({_entity_name(candidate) for candidate in selected if _entity_name(candidate) != "unknown"})
    story_types = sorted({candidate.get("story_type", "unknown") for candidate in selected if candidate.get("story_type")})
    if len(companies) >= 3:
        company_text = f"{', '.join(companies[:2]).title()} and others"
    elif companies:
        company_text = " and ".join(company.title() for company in companies[:2])
    else:
        company_text = "AI companies"
    type_text = ", ".join(story_types[:3]) if story_types else "new developments"
    return f"This week's AI updates: {company_text} across {type_text}."


def decide(
    candidates: list[dict],
    story_assessments: list[dict],
    *,
    run_profile: dict,
    layer5_policy: dict,
) -> dict:
    requested_format = run_profile.get("target_format", "auto")
    decision_mode = run_profile.get("decision_mode", "auto_route")
    roundup_min_stories = int(layer5_policy.get("roundup_min_stories", 5))
    roundup_max_stories = int(layer5_policy.get("roundup_max_stories", 8))
    deep_dive_threshold = int(layer5_policy.get("deep_dive_min_selection_score", 80))

    candidate_by_id = {candidate["story_id"]: candidate for candidate in candidates}
    active = [assessment for assessment in story_assessments if assessment["recommended_format"] not in ("skip", "monitor_only")]

    rejected = []
    for assessment in story_assessments:
        if assessment["recommended_format"] in ("skip", "monitor_only"):
            rejected.append(
                {
                    "story_id": assessment["story_id"],
                    "story_title": assessment.get("story_title", ""),
                    "rejection_reason": assessment["recommended_format"],
                    "details": [assessment.get("selection_reason", "")],
                    "recommended_action": "monitor_only",
                }
            )

    if not active:
        return {
            "decision": "no_video",
            "reason": "No story cleared the editorial selection gates.",
            "recommended_action": "continue_monitoring",
            "selected_story_ids": [],
            "rejected_candidates": rejected,
            "requested_format": requested_format,
        }

    deep_dive_candidates = sorted(
        [assessment for assessment in active if "deep_dive" in assessment.get("eligible_formats", [])],
        key=lambda assessment: assessment.get("format_scores", {}).get("deep_dive", assessment.get("selection_score", 0)),
        reverse=True,
    )
    roundup_candidates = sorted(
        [assessment for assessment in active if "roundup" in assessment.get("eligible_formats", [])],
        key=lambda assessment: assessment.get("format_scores", {}).get("roundup", assessment.get("selection_score", 0)),
        reverse=True,
    )

    def _reject_unselected(selected_ids: set[str], reason: str) -> None:
        for assessment in active:
            if assessment["story_id"] not in selected_ids:
                rejected.append(
                    {
                        "story_id": assessment["story_id"],
                        "story_title": assessment.get("story_title", ""),
                        "rejection_reason": reason,
                        "details": [assessment.get("selection_reason", "")],
                        "recommended_action": "monitor_only",
                    }
                )

    if decision_mode == "forced_format":
        if requested_format == "deep_dive":
            if not deep_dive_candidates:
                return {
                    "decision": "no_video",
                    "reason": "Requested deep_dive run produced no eligible deep-dive story.",
                    "recommended_action": "continue_monitoring",
                    "selected_story_ids": [],
                    "rejected_candidates": rejected,
                    "requested_format": requested_format,
                }
            winner = deep_dive_candidates[0]
            _reject_unselected({winner["story_id"]}, "not_selected_for_this_run")
            return {
                "decision": "create_video",
                "selected_format": "deep_dive",
                "primary_story_id": winner["story_id"],
                "supporting_story_ids": [],
                "decision_confidence": round(winner["selection_score"] / 100, 2),
                "decision_reasons": [
                    "Forced-format profile requested deep_dive.",
                    winner.get("selection_reason", ""),
                ],
                "episode_theme": None,
                "rejected_candidates": rejected,
                "requested_format": requested_format,
            }

        if requested_format == "roundup":
            if len(roundup_candidates) < roundup_min_stories:
                return {
                    "decision": "no_video",
                    "reason": (
                        f"Requested roundup run produced only {len(roundup_candidates)} eligible story/stories; "
                        f"minimum required is {roundup_min_stories}."
                    ),
                    "recommended_action": "continue_monitoring",
                    "selected_story_ids": [],
                    "rejected_candidates": rejected,
                    "requested_format": requested_format,
                }
            selected = roundup_candidates[:roundup_max_stories]
            selected_ids = [assessment["story_id"] for assessment in selected]
            _reject_unselected(set(selected_ids), "not_selected_for_roundup")
            selected_candidates = [candidate_by_id[story_id] for story_id in selected_ids if story_id in candidate_by_id]
            avg_score = sum(assessment["selection_score"] for assessment in selected) / len(selected)
            return {
                "decision": "create_video",
                "selected_format": "roundup",
                "primary_story_id": None,
                "selected_story_ids": selected_ids,
                "decision_confidence": round(avg_score / 100, 2),
                "decision_reasons": [
                    "Forced-format profile requested roundup.",
                    f"{len(selected_ids)} stories selected for roundup.",
                ],
                "episode_theme": _roundup_episode_theme(selected_candidates),
                "rejected_candidates": rejected,
                "requested_format": requested_format,
            }

    top_deep_dive = deep_dive_candidates[0] if deep_dive_candidates else None
    roundup_bundle = roundup_candidates[:roundup_max_stories]

    if len(roundup_bundle) >= roundup_min_stories:
        roundup_average = sum(assessment["selection_score"] for assessment in roundup_bundle) / len(roundup_bundle)
        if top_deep_dive and top_deep_dive["selection_score"] >= deep_dive_threshold and top_deep_dive["selection_score"] >= roundup_average + 12:
            _reject_unselected({top_deep_dive["story_id"]}, "not_selected_for_this_run")
            return {
                "decision": "create_video",
                "selected_format": "deep_dive",
                "primary_story_id": top_deep_dive["story_id"],
                "supporting_story_ids": [],
                "decision_confidence": round(top_deep_dive["selection_score"] / 100, 2),
                "decision_reasons": [
                    "Auto-route selected a standout deep dive over the roundup bundle.",
                    top_deep_dive.get("selection_reason", ""),
                ],
                "episode_theme": None,
                "rejected_candidates": rejected,
                "requested_format": requested_format,
            }

        selected_ids = [assessment["story_id"] for assessment in roundup_bundle]
        _reject_unselected(set(selected_ids), "not_selected_for_roundup")
        selected_candidates = [candidate_by_id[story_id] for story_id in selected_ids if story_id in candidate_by_id]
        return {
            "decision": "create_video",
            "selected_format": "roundup",
            "primary_story_id": None,
            "selected_story_ids": selected_ids,
            "decision_confidence": round(roundup_average / 100, 2),
            "decision_reasons": [
                "Auto-route selected a roundup bundle.",
                f"{len(selected_ids)} stories met roundup selection quality.",
            ],
            "episode_theme": _roundup_episode_theme(selected_candidates),
            "rejected_candidates": rejected,
            "requested_format": requested_format,
        }

    if top_deep_dive:
        _reject_unselected({top_deep_dive["story_id"]}, "not_selected_for_this_run")
        return {
            "decision": "create_video",
            "selected_format": "deep_dive",
            "primary_story_id": top_deep_dive["story_id"],
            "supporting_story_ids": [],
            "decision_confidence": round(top_deep_dive["selection_score"] / 100, 2),
            "decision_reasons": [
                "Auto-route selected deep dive because there were not enough roundup-quality stories.",
                top_deep_dive.get("selection_reason", ""),
            ],
            "episode_theme": None,
            "rejected_candidates": rejected,
            "requested_format": requested_format,
        }

    return {
        "decision": "no_video",
        "reason": "Stories were interesting but did not produce a viable roundup bundle or deep-dive candidate.",
        "recommended_action": "continue_monitoring",
        "selected_story_ids": [],
        "rejected_candidates": rejected,
        "requested_format": requested_format,
    }
