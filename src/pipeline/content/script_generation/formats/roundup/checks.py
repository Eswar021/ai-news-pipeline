from __future__ import annotations

import re
from typing import Any

from ...shared.utils import dedupe, estimated_seconds, story_id, word_count


INTERNAL_ID_RE = re.compile(
    r"\b(?:story|section|segment|record|fact)_[a-z0-9][a-z0-9_\-]*\b",
    re.IGNORECASE,
)
def build_full_script(section_scripts: list[dict[str, Any]], words_per_minute: int) -> dict[str, Any]:
    narration_text = "\n\n".join(section["narration_text"] for section in section_scripts).strip()
    return {
        "narration_text": narration_text,
        "total_word_count": word_count(narration_text),
        "estimated_duration_seconds": estimated_seconds(narration_text, words_per_minute),
        "section_order": [section["section_id"] for section in section_scripts],
    }


def check_script_package(
    script_package: dict[str, Any],
    video_packet: dict[str, Any],
    script_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    sections = list(script_package.get("sections", []))
    section_plan = list(script_package.get("section_plan", []))
    stories = list(video_packet.get("stories", []))
    selected_story_ids = {story_id(story) for story in stories}
    expected_section_count = len(stories) + 2

    if len(sections) != expected_section_count:
        errors.append(f"Expected {expected_section_count} script sections, found {len(sections)}")
    if section_plan:
        planned_ids = [section.get("section_id", "") for section in section_plan]
        actual_ids = [section.get("section_id", "") for section in sections]
        if actual_ids != planned_ids:
            errors.append(f"Script section order does not match section_plan: {actual_ids} != {planned_ids}")

    expected_story_sections = len(stories)
    actual_story_sections = sum(1 for section in sections if section.get("section_type") == "story")
    if actual_story_sections != expected_story_sections:
        errors.append(f"Expected {expected_story_sections} story sections, found {actual_story_sections}")

    known_source_keys = _source_key_index(stories)
    observed_beat_ids: set[str] = set()
    for section in sections:
        section_id = section.get("section_id", "")
        narration = section.get("narration_text", "")
        if not narration.strip():
            errors.append(f"{section_id} narration_text is empty")
        leaked_ids = _internal_ids_in_narration(narration)
        if leaked_ids:
            errors.append(f"{section_id} narration contains internal IDs: {leaked_ids}")

        beats = section.get("beats")
        if not isinstance(beats, list) or not beats:
            errors.append(f"{section_id} beats are missing or empty")
            beats = []
        reconstructed = " ".join(str(beat.get("narration_text", "")).strip() for beat in beats).strip()
        if reconstructed != narration.strip():
            errors.append(f"{section_id} narration_text is not the deterministic concatenation of its beats")
        for expected_order, beat in enumerate(beats, start=1):
            beat_id = str(beat.get("beat_id", "")).strip()
            if not beat_id:
                errors.append(f"{section_id} contains a beat without beat_id")
            elif beat_id in observed_beat_ids:
                errors.append(f"Duplicate beat_id: {beat_id}")
            else:
                observed_beat_ids.add(beat_id)
            if int(beat.get("beat_order", 0) or 0) != expected_order:
                errors.append(f"{section_id} beat order is not contiguous at {beat_id or expected_order}")
            beat_narration = str(beat.get("narration_text", ""))
            beat_leaks = _internal_ids_in_narration(beat_narration)
            if beat_leaks:
                errors.append(f"{beat_id} narration contains internal IDs: {beat_leaks}")

        used_story_ids = set(section.get("used_story_ids", []))
        if not used_story_ids <= selected_story_ids:
            errors.append(f"{section_id} used story IDs outside selected stories: {sorted(used_story_ids - selected_story_ids)}")

        used_source_keys = set(section.get("used_source_record_keys", []))
        unknown_source_keys = sorted(used_source_keys - set(known_source_keys))
        if unknown_source_keys:
            errors.append(f"{section_id} used unknown source record keys: {unknown_source_keys}")

        if section.get("section_type") == "story":
            title_card = section.get("title_card")
            if not isinstance(title_card, dict) or not str(title_card.get("display_title", "")).strip():
                errors.append(f"{section_id} is missing its story title-card contract")
            elif title_card.get("voice_behavior") != "continue":
                errors.append(f"{section_id} title card must use voice_behavior=continue")

    estimated = float(script_package.get("full_script_stats", {}).get("estimated_duration_seconds", 0) or 0)
    duration_policy = dict(script_package.get("duration_policy") or video_packet.get("duration_policy") or {})
    configured_ceiling = duration_policy.get("configured_ceiling_seconds")
    if configured_ceiling is None:
        configured_ceiling = video_packet.get("target_duration_seconds")
    if configured_ceiling and estimated > float(configured_ceiling):
        warnings.append(
            "Observed script duration exceeds the configured editorial ceiling: "
            f"estimated {estimated:.1f}s, ceiling {float(configured_ceiling):.1f}s. "
            "The script remains valid because duration is observational, not an approval quota."
        )

    return {
        "passed": not errors,
        "errors": dedupe(errors),
        "warnings": dedupe(warnings),
        "validation_scope": "structural_integrity_and_provenance_only",
    }


def _internal_ids_in_narration(text: str) -> list[str]:
    return dedupe(INTERNAL_ID_RE.findall(text))[:8]


def _source_key_index(stories: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for story in stories:
        for record in story.get("records", []):
            key = record.get("record_key", "")
            if key:
                index[key] = record
        for key in (story.get("video_segment") or {}).get("source_record_keys", []):
            if key and key not in index:
                index[key] = {}
    return index
