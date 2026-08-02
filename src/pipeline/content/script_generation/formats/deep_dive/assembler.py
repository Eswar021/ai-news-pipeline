from __future__ import annotations

from typing import Any

from ...shared.assembly import (
    assemble_section,
    finalize_script,
    normalize_bookend_beats,
    normalize_story_beats,
)
from ...shared.utils import clean_text


def assemble_script(
    *,
    section_plan: list[dict[str, Any]],
    director: dict[str, Any],
    angle_segments: list[dict[str, Any]],
    bookends: dict[str, Any],
    words_per_minute: int,
    title_card_seconds: float,
) -> dict[str, Any]:
    segment_by_angle = {clean_text(item.get("angle_id")): item for item in angle_segments}
    sections: list[dict[str, Any]] = []

    for plan in section_plan:
        section_type = plan["section_type"]
        if section_type == "intro":
            beats = normalize_bookend_beats(
                section_id=plan["section_id"],
                drafts=bookends.get("intro_beats", []),
                section_type="intro",
                words_per_minute=words_per_minute,
            )
            title_card = None
        elif section_type == "closing":
            beats = normalize_bookend_beats(
                section_id=plan["section_id"],
                drafts=bookends.get("closing_beats", []),
                section_type="closing",
                words_per_minute=words_per_minute,
            )
            title_card = None
        else:  # angle section (section_type == "story")
            angle_id = clean_text(plan.get("angle_id"))
            segment = segment_by_angle.get(angle_id)
            if segment is None:
                raise ValueError(f"Missing generated angle segment for {angle_id}")
            # The section writer bridges each angle within its own beats, so no
            # separate transition line is prepended here.
            beats = normalize_story_beats(
                section_id=plan["section_id"],
                story_id=clean_text(plan.get("story_id")),
                transition_line="",
                transition_delivery=None,
                drafts=segment.get("beats", []),
                words_per_minute=words_per_minute,
            )
            title_card = {
                "display_title": clean_text(plan.get("angle_label")) or clean_text(segment.get("display_title")),
                "subtitle": "",
                "duration_seconds": round(float(title_card_seconds), 2),
                "voice_behavior": "continue",
                "anchor_beat_id": beats[0]["beat_id"],
            }

        sections.append(
            assemble_section(
                plan=plan,
                beats=beats,
                title_card=title_card,
                words_per_minute=words_per_minute,
            )
        )

    return finalize_script(
        sections=sections,
        director=director,
        words_per_minute=words_per_minute,
        generation_strategy="deep_dive_director_plus_per_angle_beats_plus_bookends",
    )
