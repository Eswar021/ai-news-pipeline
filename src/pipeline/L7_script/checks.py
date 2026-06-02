from __future__ import annotations

from collections import Counter
import re


VISUAL_DIRECTION_MARKERS = (
    "lower third",
    "on screen",
    "on-screen",
    "b-roll",
    "b roll",
    "overlay",
    "show on screen",
    "show this on screen",
    "show title card",
    "cut to",
    "visual note",
    "visual direction",
    "editor note",
)

MIN_TOTAL_DURATION_RATIO = 0.78
MIN_SECTION_WORD_RATIO = 0.9
INTERNAL_FACT_ID_RE = re.compile(r"\bfact_[a-z0-9_]+\b", re.IGNORECASE)


def build_full_script(section_scripts: list[dict]) -> dict:
    narration_text = "\n\n".join(section["narration_text"] for section in section_scripts).strip()
    word_count = sum(section["word_count"] for section in section_scripts)
    estimated_seconds = round(sum(float(section["estimated_seconds"]) for section in section_scripts), 1)
    return {
        "narration_text": narration_text,
        "total_word_count": word_count,
        "estimated_duration_seconds": estimated_seconds,
        "section_order": [section["section_id"] for section in section_scripts],
    }


def build_evidence_usage(section_scripts: list[dict], content_packet: dict) -> dict:
    used_fact_ids = []
    section_usage = []
    for section in section_scripts:
        used_fact_ids.extend(section.get("used_fact_ids", []))
        section_usage.append(
            {
                "section_id": section["section_id"],
                "story_id": section.get("story_id", ""),
                "used_fact_ids": list(section.get("used_fact_ids", [])),
                "required_fact_ids": list(section.get("required_fact_ids", [])),
                "required_cautious_fact_ids": list(section.get("required_cautious_fact_ids", [])),
                "optional_fact_ids": list(section.get("optional_fact_ids", [])),
                "available_fact_ids": list(section.get("available_fact_ids", [])),
                "omitted_required_fact_ids": list(section.get("omitted_required_fact_ids", [])),
            }
        )

    handoff = content_packet.get("layer7_handoff", {})
    required_fact_ids = list(handoff.get("required_fact_ids", []))
    required_cautious_fact_ids = list(handoff.get("required_cautious_fact_ids", []))
    used_required = [fact_id for fact_id in required_fact_ids if fact_id in used_fact_ids]
    omitted_required = [fact_id for fact_id in required_fact_ids if fact_id not in used_fact_ids]
    return {
        "used_fact_ids": _dedupe(used_fact_ids),
        "required_fact_ids": required_fact_ids,
        "required_cautious_fact_ids": required_cautious_fact_ids,
        "used_required_fact_ids": _dedupe(used_required),
        "omitted_required_fact_ids": _dedupe(omitted_required),
        "section_usage": section_usage,
        "fact_index": _build_fact_index(content_packet),
    }


def collect_visual_notes(section_scripts: list[dict]) -> list[dict]:
    notes = []
    for section in section_scripts:
        for index, note in enumerate(section.get("visual_notes", []), start=1):
            notes.append(
                {
                    "section_id": section["section_id"],
                    "note_id": f"{section['section_id']}_visual_{index:02d}",
                    "note": note,
                }
            )
    return notes


def check_script_package(package: dict, content_packet: dict) -> dict:
    errors = []
    warnings = []
    section_scripts = package.get("section_scripts", [])

    expected_sections = len(content_packet.get("segment_plan", [])) + 2
    if len(section_scripts) != expected_sections:
        errors.append(f"Expected {expected_sections} sections, found {len(section_scripts)}")

    for section in section_scripts:
        if section.get("omitted_required_fact_ids"):
            errors.append(
                f"{section['section_id']} omitted required facts: {section['omitted_required_fact_ids']}"
            )
        minimum_words = int(section.get("minimum_word_count", 0) or 0)
        if section.get("section_type") == "story" and minimum_words and section.get("word_count", 0) < minimum_words:
            message = (
                f"{section['section_id']} is below section target: "
                f"{section.get('word_count', 0)} words, minimum {minimum_words}"
            )
            if section.get("word_count", 0) >= minimum_words * MIN_SECTION_WORD_RATIO:
                warnings.append(message)
            else:
                errors.append(message)
        markers = _visual_markers_in_narration(section.get("narration_text", ""))
        if markers:
            errors.append(f"{section['section_id']} narration contains visual/editor directions: {markers}")
        leaked_fact_ids = _internal_fact_ids_in_narration(section.get("narration_text", ""))
        if leaked_fact_ids:
            errors.append(f"{section['section_id']} narration contains internal fact IDs: {leaked_fact_ids}")
        for warning in section.get("style_warnings", []):
            warnings.append(f"{section['section_id']} style warning: {warning}")

    usage = package.get("evidence_usage", {})
    if usage.get("omitted_required_fact_ids"):
        errors.append(f"Full script omitted required facts: {usage['omitted_required_fact_ids']}")

    target_seconds = int(content_packet.get("video", {}).get("target_duration_seconds", 0) or 0)
    estimated_seconds = float(package.get("full_script", {}).get("estimated_duration_seconds", 0) or 0)
    if target_seconds and estimated_seconds < target_seconds * MIN_TOTAL_DURATION_RATIO:
        errors.append(
            f"Full script is too short: estimated {estimated_seconds:.1f}s, "
            f"target {target_seconds}s"
        )

    used_counts = Counter(usage.get("used_fact_ids", []))
    repeated = [fact_id for fact_id, count in used_counts.items() if count > 2]
    if repeated:
        warnings.append(f"Some fact IDs are repeated across many sections: {repeated}")

    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _visual_markers_in_narration(text: str) -> list[str]:
    lower = text.lower()
    return [marker for marker in VISUAL_DIRECTION_MARKERS if marker in lower]


def _internal_fact_ids_in_narration(text: str) -> list[str]:
    return _dedupe(INTERNAL_FACT_ID_RE.findall(text))[:5]


def _build_fact_index(content_packet: dict) -> dict:
    fact_index = {}
    for segment in content_packet.get("segment_plan", []):
        for fact in segment.get("safe_facts", []) + segment.get("cautious_facts", []):
            fact_id = fact.get("fact_id", "")
            if not fact_id or fact_id in fact_index:
                continue
            fact_index[fact_id] = {
                "fact_id": fact_id,
                "fact_text": fact.get("fact_text", ""),
                "fact_type": fact.get("fact_type", ""),
                "status": fact.get("status", ""),
                "confidence": fact.get("confidence", ""),
                "support_records": fact.get("support_records", []),
            }
    return fact_index


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    kept = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        kept.append(value)
    return kept
