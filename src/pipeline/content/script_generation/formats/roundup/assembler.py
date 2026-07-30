from __future__ import annotations

from typing import Any

from .utils import clean_text, dedupe, estimated_seconds, word_count


def assemble_script(
    *,
    section_plan: list[dict[str, Any]],
    director: dict[str, Any],
    story_segments: list[dict[str, Any]],
    bookends: dict[str, Any],
    words_per_minute: int,
    title_card_seconds: float,
) -> dict[str, Any]:
    segment_by_story = {clean_text(item.get("story_id")): item for item in story_segments}
    connector_by_story = {
        clean_text(item.get("target_story_id")): item
        for item in bookends.get("story_connectors", [])
    }
    sections: list[dict[str, Any]] = []

    for plan in section_plan:
        section_type = plan["section_type"]
        if section_type == "intro":
            beats = _normalize_bookend_beats(
                section_id=plan["section_id"],
                drafts=bookends.get("intro_beats", []),
                section_type="intro",
                words_per_minute=words_per_minute,
            )
            title_card = None
        elif section_type == "closing":
            beats = _normalize_bookend_beats(
                section_id=plan["section_id"],
                drafts=bookends.get("closing_beats", []),
                section_type="closing",
                words_per_minute=words_per_minute,
            )
            title_card = None
        else:
            sid = clean_text(plan.get("story_id"))
            segment = segment_by_story.get(sid)
            if segment is None:
                raise ValueError(f"Missing generated story segment for {sid}")
            connector = connector_by_story.get(sid)
            if connector is None:
                raise ValueError(f"Missing bookend connector for {sid}")
            beats = _normalize_story_beats(
                section_id=plan["section_id"],
                story_id=sid,
                transition_line=connector.get("transition_line", ""),
                transition_delivery=connector.get("delivery_direction"),
                drafts=segment.get("beats", []),
                words_per_minute=words_per_minute,
            )
            title_card = {
                "display_title": clean_text(connector.get("display_title")) or clean_text(segment.get("display_title")),
                "subtitle": clean_text(connector.get("title_card_subtitle")),
                "duration_seconds": round(float(title_card_seconds), 2),
                "voice_behavior": "continue",
                "anchor_beat_id": beats[0]["beat_id"],
            }

        sections.append(
            _assemble_section(
                plan=plan,
                beats=beats,
                title_card=title_card,
                words_per_minute=words_per_minute,
            )
        )

    full_script = "\n\n".join(section["narration_text"] for section in sections).strip()
    return {
        "generation_strategy": "director_plus_per_story_beats_plus_bookends",
        "episode_direction": director,
        "sections": sections,
        "full_script": full_script,
        "full_script_stats": {
            "total_word_count": word_count(full_script),
            "estimated_duration_seconds": estimated_seconds(full_script, words_per_minute),
            "section_order": [section["section_id"] for section in sections],
            "beat_count": sum(len(section["beats"]) for section in sections),
        },
        "audio_plan": {
            "unit_strategy": "one_audio_unit_per_section_with_beat_anchors",
            "units": [_audio_unit(section) for section in sections],
        },
    }


def _normalize_story_beats(
    *,
    section_id: str,
    story_id: str,
    transition_line: str,
    transition_delivery: dict[str, Any] | None,
    drafts: list[dict[str, Any]],
    words_per_minute: int,
) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    transition = clean_text(transition_line)
    if transition:
        raw.append(
            {
                "beat_type": "transition",
                "beat_function": "bridge",
                "narration_text": transition,
                "source_record_keys": [],
                "support_truth_ids": [],
                "creative_device": "none",
                "delivery_direction": dict(transition_delivery or _neutral_delivery_direction()),
            }
        )
    raw.extend(drafts)
    return _normalize_beats(
        section_id=section_id,
        story_id=story_id,
        drafts=raw,
        words_per_minute=words_per_minute,
    )


def _normalize_bookend_beats(
    *,
    section_id: str,
    drafts: list[dict[str, Any]],
    section_type: str,
    words_per_minute: int,
) -> list[dict[str, Any]]:
    if not drafts:
        raise ValueError(f"{section_id} must contain at least one {section_type} beat")
    enriched = [
        {
            **draft,
            "source_record_keys": [],
            "support_truth_ids": [],
            "creative_device": "none",
            "beat_function": _bookend_beat_function(section_type, draft.get("beat_type", "")),
        }
        for draft in drafts
    ]
    return _normalize_beats(
        section_id=section_id,
        story_id="",
        drafts=enriched,
        words_per_minute=words_per_minute,
    )


def _normalize_beats(
    *,
    section_id: str,
    story_id: str,
    drafts: list[dict[str, Any]],
    words_per_minute: int,
) -> list[dict[str, Any]]:
    beats: list[dict[str, Any]] = []
    for order, draft in enumerate(drafts, start=1):
        narration = clean_text(draft.get("narration_text"))
        if not narration:
            raise ValueError(f"{section_id} beat {order} has empty narration")
        beats.append(
            {
                "beat_id": f"{section_id}_beat_{order:02d}",
                "beat_order": order,
                "beat_type": clean_text(draft.get("beat_type")),
                "beat_function": clean_text(draft.get("beat_function")) or "explanation",
                "story_id": story_id,
                "narration_text": narration,
                "word_count": word_count(narration),
                "estimated_seconds": estimated_seconds(narration, words_per_minute),
                "source_record_keys": dedupe(list(draft.get("source_record_keys") or [])),
                "support_truth_ids": dedupe(list(draft.get("support_truth_ids") or [])),
                "creative_device": clean_text(draft.get("creative_device")) or "none",
                "delivery_direction": dict(draft.get("delivery_direction") or _neutral_delivery_direction()),
            }
        )
    return beats


def _assemble_section(
    *,
    plan: dict[str, Any],
    beats: list[dict[str, Any]],
    title_card: dict[str, Any] | None,
    words_per_minute: int,
) -> dict[str, Any]:
    narration = " ".join(beat["narration_text"] for beat in beats).strip()
    used_source_keys = dedupe(
        [key for beat in beats for key in beat.get("source_record_keys", [])]
    )
    used_story_ids = [plan["story_id"]] if plan.get("story_id") else list(plan.get("allowed_story_ids", []))
    return {
        "section_id": plan["section_id"],
        "section_type": plan["section_type"],
        "section_order": int(plan["section_order"]),
        "story_id": clean_text(plan.get("story_id")),
        "story_title": clean_text(plan.get("story_title")),
        "role": clean_text(plan.get("role")),
        "writing_guidance": dict(plan.get("writing_guidance") or {}),
        "title_card": title_card,
        "beats": beats,
        "narration_text": narration,
        "word_count": word_count(narration),
        "estimated_seconds": estimated_seconds(narration, words_per_minute),
        "used_story_ids": used_story_ids,
        "used_source_record_keys": used_source_keys,
        "analysis_sentences": [],
    }


def _audio_unit(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "audio_unit_id": f"audio_{section['section_id']}",
        "section_id": section["section_id"],
        "section_type": section["section_type"],
        "story_id": section.get("story_id", ""),
        "story_title": section.get("story_title", ""),
        "narration_text": section["narration_text"],
        "beat_ids": [beat["beat_id"] for beat in section["beats"]],
    }


def _bookend_beat_function(section_type: str, beat_type: str) -> str:
    if section_type == "intro":
        return "episode_hook" if clean_text(beat_type) == "hook" else "episode_setup"
    return "episode_payoff"


def _neutral_delivery_direction() -> dict[str, Any]:
    return {
        "performance_intent": "Deliver this beat naturally and make its purpose clear.",
        "emotional_color": "engaged",
        "pace": "conversational",
        "energy": "engaged",
        "emphasis_phrases": [],
        "pause_after": "none",
    }
