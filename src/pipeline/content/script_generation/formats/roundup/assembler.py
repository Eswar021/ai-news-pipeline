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
        else:
            sid = clean_text(plan.get("story_id"))
            segment = segment_by_story.get(sid)
            if segment is None:
                raise ValueError(f"Missing generated story segment for {sid}")
            connector = connector_by_story.get(sid)
            if connector is None:
                raise ValueError(f"Missing bookend connector for {sid}")
            beats = normalize_story_beats(
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
        generation_strategy="director_plus_per_story_beats_plus_bookends",
    )
