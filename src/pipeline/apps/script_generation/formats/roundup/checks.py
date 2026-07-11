from __future__ import annotations

import re
from typing import Any

from .config import VISUAL_DIRECTION_MARKERS
from .utils import dedupe, estimated_seconds, story_id, word_count


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
    *,
    duration_tolerance_seconds: int,
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
    for section in sections:
        section_id = section.get("section_id", "")
        narration = section.get("narration_text", "")
        if not narration.strip():
            errors.append(f"{section_id} narration_text is empty")
        markers = _visual_markers_in_narration(narration)
        if markers:
            errors.append(f"{section_id} narration contains visual/editor directions: {markers}")
        leaked_ids = _internal_ids_in_narration(narration)
        if leaked_ids:
            errors.append(f"{section_id} narration contains internal IDs: {leaked_ids}")

        used_story_ids = set(section.get("used_story_ids", []))
        if not used_story_ids <= selected_story_ids:
            errors.append(f"{section_id} used story IDs outside selected stories: {sorted(used_story_ids - selected_story_ids)}")

        used_source_keys = set(section.get("used_source_record_keys", []))
        unknown_source_keys = sorted(used_source_keys - set(known_source_keys))
        if unknown_source_keys:
            errors.append(f"{section_id} used unknown source record keys: {unknown_source_keys}")

    target_seconds = int(video_packet.get("target_duration_seconds", 0) or 0)
    estimated = float(script_package.get("full_script_stats", {}).get("estimated_duration_seconds", 0) or 0)
    if target_seconds and abs(estimated - target_seconds) > duration_tolerance_seconds:
        errors.append(
            f"Full script duration drift exceeds tolerance: estimated {estimated:.1f}s, "
            f"target {target_seconds}s, tolerance {duration_tolerance_seconds}s"
        )

    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _visual_markers_in_narration(text: str) -> list[str]:
    lower = text.lower()
    return [marker for marker in VISUAL_DIRECTION_MARKERS if marker in lower]


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
