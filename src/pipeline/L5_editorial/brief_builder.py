from __future__ import annotations

import json
from pathlib import Path

from src.llm.client import OpenAIJSONClient
from src.pipeline.L1_collection.common import clean_text


def build_selected_video(
    decision_result: dict,
    *,
    layer5_cfg: dict,
    system_prompt: str,
    log_path: Path,
) -> dict:
    if decision_result["action"] == "no_video":
        return {
            "format": "none",
            "target_duration_seconds": 0,
            "viewer_promise": "",
            "editorial_angle": "",
            "thesis_or_theme": "",
            "opening_hook_direction": "",
            "tone": "",
            "story_order": [],
            "blocked_angles": [],
        }

    client = OpenAIJSONClient(model=layer5_cfg["editorial_brief_model"])
    response = client.generate_json(
        module_name="editorial_brief_builder",
        system_prompt=system_prompt,
        user_prompt=_build_user_prompt(decision_result),
        log_path=log_path,
        metadata={
            "selected_format": decision_result["selected_format"],
            "selected_story_ids": decision_result["selected_story_ids"],
        },
    )
    return _validate_selected_video(response, decision_result)


def _build_user_prompt(decision_result: dict) -> str:
    selected = [_compact_selected_item(item) for item in decision_result["selected_evaluations"]]
    payload = {
        "selected_format": decision_result["selected_format"],
        "target_duration_seconds": decision_result["target_duration_seconds"],
        "decision_reason": decision_result["decision_reason"],
        "selected_stories": selected,
    }
    return (
        "Build editorial direction for the selected AI news roundup. Do not write the script, title, or thumbnail.\n"
        "Return JSON with exactly these keys: viewer_promise, editorial_angle, thesis_or_theme, "
        "opening_hook_direction, tone, story_order, blocked_angles.\n"
        "story_order must list only selected story_id values and include role, target_seconds, and guidance. "
        "Copy story_id values exactly; never shorten, rewrite, or regenerate them. "
        "Use each story's proposed_role and proposed_target_seconds exactly.\n\n"
        f"Selection:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _compact_selected_item(candidate: dict) -> dict:
    packet = candidate["fact_packet"]
    return {
        "story_id": candidate["story_id"],
        "story_title": candidate["story_title"],
        "proposed_role": candidate.get("segment_role", ""),
        "proposed_target_seconds": candidate.get("target_seconds", 0),
        "role_reason": candidate.get("role_reason", ""),
        "selection_path": candidate.get("selection_path", ""),
        "source_groups": candidate.get("source_groups", []),
        "source_relationship_counts": candidate.get("source_relationship_counts", {}),
        "viewer_value": candidate["viewer_value"],
        "opportunity_score": candidate["opportunity_score"],
        "readiness": candidate["readiness"],
        "safe_facts": [fact["fact_text"] for fact in packet.get("safe_facts", [])[:8]],
        "cautious_facts": [fact["fact_text"] for fact in packet.get("cautious_facts", [])[:4]],
    }


def _validate_selected_video(response: dict, decision_result: dict) -> dict:
    required_strings = ["viewer_promise", "editorial_angle", "thesis_or_theme", "opening_hook_direction", "tone"]
    for key in required_strings:
        if not clean_text(response.get(key, "")):
            raise ValueError(f"editorial_brief_builder response missing {key}")

    story_order = response.get("story_order")
    if not isinstance(story_order, list) or not story_order:
        raise ValueError("editorial_brief_builder response must include non-empty story_order")

    selected_ids = set(decision_result["selected_story_ids"])
    selected_by_id = {item["story_id"]: item for item in decision_result["selected_evaluations"]}
    cleaned_order = []
    for item in story_order:
        if not isinstance(item, dict):
            raise ValueError("editorial_brief_builder story_order entries must be objects")
        story_id = clean_text(item.get("story_id", ""))
        story_id = _resolve_selected_story_id(story_id, selected_ids)
        if not story_id:
            raise ValueError(f"editorial_brief_builder used unselected story_id: {story_id}")
        selected_item = selected_by_id[story_id]
        cleaned_order.append(
            {
                "story_id": story_id,
                "role": selected_item.get("segment_role", ""),
                "target_seconds": int(selected_item.get("target_seconds", 0)),
                "guidance": clean_text(item.get("guidance", "")),
            }
        )

    blocked_angles = response.get("blocked_angles", [])
    if not isinstance(blocked_angles, list):
        raise ValueError("editorial_brief_builder blocked_angles must be a list")

    return {
        "format": decision_result["selected_format"],
        "target_duration_seconds": decision_result["target_duration_seconds"],
        "viewer_promise": clean_text(response["viewer_promise"]),
        "editorial_angle": clean_text(response["editorial_angle"]),
        "thesis_or_theme": clean_text(response["thesis_or_theme"]),
        "opening_hook_direction": clean_text(response["opening_hook_direction"]),
        "tone": clean_text(response["tone"]),
        "story_order": cleaned_order,
        "blocked_angles": [clean_text(angle) for angle in blocked_angles if clean_text(angle)],
    }


def _resolve_selected_story_id(story_id: str, selected_ids: set[str]) -> str:
    if story_id in selected_ids:
        return story_id
    if not story_id:
        return ""
    if len(story_id) < 45:
        return ""

    matches = [selected_id for selected_id in selected_ids if selected_id.startswith(story_id)]
    if len(matches) == 1:
        return matches[0]
    return ""
