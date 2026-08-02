from __future__ import annotations

from typing import Any

from ...shared.utils import clean_text, source_record_keys, story_id, story_title


def build_deep_dive_section_inputs(
    story: dict[str, Any],
    director: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """intro + one section per planned angle (in director order) + closing."""
    briefs_by_id = {clean_text(b.get("angle_id")): b for b in director.get("angle_briefs", [])}
    ordered = [clean_text(a) for a in director.get("ordered_angle_ids", []) if clean_text(a)]
    if not ordered:
        raise ValueError("deep-dive director returned no ordered angles")

    sections = [_intro_section(story, director, config)]
    for order, angle_id in enumerate(ordered, start=1):
        brief = briefs_by_id.get(angle_id)
        if brief is None:
            raise ValueError(f"deep-dive director ordered angle {angle_id} without a matching brief")
        sections.append(_angle_section(story, brief, order, len(ordered), config))
    sections.append(_closing_section(story, director, config))
    return sections


def _intro_section(story: dict[str, Any], director: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "section_id": "section_00_intro",
        "section_type": "intro",
        "section_order": 0,
        "story_id": "",
        "story_title": "",
        "role": "",
        "writing_guidance": _writing_guidance(config, "intro"),
        "allowed_story_ids": [story_id(story)],
        "allowed_source_record_keys": source_record_keys(story),
        "prompt_payload": {
            "task": "Write the opening section for a single-topic deep-dive video.",
            "section_goal": (
                "Open on the most striking concrete detail of the topic, make clear why it deserves "
                "several focused minutes, and promise the payoff without listing every angle."
            ),
            "writing_guidance": _writing_guidance(config, "intro"),
            "script_style": config["script_style"],
            "episode_direction": director,
            "topic_title": story_title(story),
        },
    }


def _angle_section(
    story: dict[str, Any],
    brief: dict[str, Any],
    order: int,
    angle_total: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    angle_id = clean_text(brief.get("angle_id"))
    return {
        "section_id": f"section_{order:02d}_{angle_id}",
        "section_type": "story",
        "section_order": order,
        "story_id": story_id(story),
        "story_title": story_title(story),
        "role": "angle",
        "angle_id": angle_id,
        "angle_label": clean_text(brief.get("angle_label")),
        "writing_guidance": _writing_guidance(config, "angle"),
        "allowed_story_ids": [story_id(story)],
        "allowed_source_record_keys": source_record_keys(story),
        "prompt_payload": {
            "task": "Write one angle section of a single-topic deep-dive video.",
            "section_goal": clean_text(brief.get("angle_promise")) or "Advance one facet of the topic clearly.",
            "angle_position": {"index": order, "of": angle_total, "is_first_angle": order == 1},
            "angle_brief": brief,
            "writing_guidance": _writing_guidance(config, "angle"),
            "script_style": config["script_style"],
            "assigned_story": story,
        },
    }


def _closing_section(story: dict[str, Any], director: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "section_id": "section_99_closing",
        "section_type": "closing",
        "section_order": 999,
        "story_id": "",
        "story_title": "",
        "role": "",
        "writing_guidance": _writing_guidance(config, "closing"),
        "allowed_story_ids": [story_id(story)],
        "allowed_source_record_keys": source_record_keys(story),
        "prompt_payload": {
            "task": "Write the closing section for a single-topic deep-dive video.",
            "section_goal": (
                "Land the single argument in plain language, give the honest takeaway, "
                "and end with a short natural signoff."
            ),
            "writing_guidance": _writing_guidance(config, "closing"),
            "script_style": config["script_style"],
            "episode_direction": director,
            "topic_title": story_title(story),
        },
    }


def _writing_guidance(config: dict[str, Any], key: str) -> dict[str, Any]:
    guidance = dict((config.get("writing_guidance") or {}).get(key) or {})
    guidance["enforcement"] = "soft_editorial_guidance_only"
    return guidance
