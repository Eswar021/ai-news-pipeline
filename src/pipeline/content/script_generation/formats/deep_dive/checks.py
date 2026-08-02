from __future__ import annotations

import re
from typing import Any

from ...shared.utils import story_id


INTERNAL_ID_RE = re.compile(
    r"\b(?:story|section|segment|record|fact|angle|truth)_[a-z0-9][a-z0-9_\-]*\b",
    re.IGNORECASE,
)


def check_script_package(
    script_package: dict[str, Any],
    video_packet: dict[str, Any],
    script_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    sections = list(script_package.get("sections", []))
    angle_count = int(script_package.get("angle_count", 0))
    expected_section_count = angle_count + 2  # intro + angles + closing

    if angle_count < 1:
        errors.append("deep_dive produced no angle sections")
    if len(sections) != expected_section_count:
        errors.append(
            f"Expected {expected_section_count} sections (intro + {angle_count} angles + closing), found {len(sections)}"
        )
    if sections:
        if sections[0].get("section_type") != "intro":
            errors.append("first section must be the intro")
        if sections[-1].get("section_type") != "closing":
            errors.append("last section must be the closing")

    topic_id = story_id(video_packet["stories"][0]) if video_packet.get("stories") else ""
    for section in sections:
        section_id = section.get("section_id", "")
        if not section.get("beats"):
            errors.append(f"{section_id} contains no beats")
        if section.get("section_type") == "story":
            if not section.get("title_card"):
                errors.append(f"{section_id} is an angle section but has no title card")
            if topic_id and section.get("story_id") not in ("", topic_id):
                errors.append(f"{section_id} references story {section.get('story_id')!r}; deep_dive expands only {topic_id!r}")
        leaked = sorted(set(INTERNAL_ID_RE.findall(str(section.get("narration_text", "")))))
        if leaked:
            warnings.append(f"{section_id} narration may leak internal IDs: {leaked[:3]}")

    if not str(script_package.get("full_script", "")).strip():
        errors.append("full_script is empty")

    return {"passed": not errors, "errors": errors, "warnings": warnings}
