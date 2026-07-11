from __future__ import annotations

import json
import re
from typing import Any

from src.pipeline.handoffs.common import clean_text, iso_now

from .contract import ChatGPTScriptParserRequest


RESPONSE_MARKER = "CHATGPT_PIPELINE_RESPONSE_V1"
SECTION_NAMES = ("NOTES", "SCRIPT", "METADATA")
STRUCTURED_SECTION_MARKER = "[SCRIPT_SECTIONS_JSON]"
INLINE_SECTION_RE = re.compile(r"^\[\[SECTION:(?P<section_id>[^\]]+)\]\]\s*$", re.MULTILINE)


def run(input_json: dict) -> dict:
    request = ChatGPTScriptParserRequest.model_validate(input_json)
    packet = request.input.video_packaging.data.video_packet
    config = request.config.model_dump(mode="json")
    generated_at = iso_now()
    errors: list[str] = []
    warnings: list[str] = []

    parsed_response = _parse_response(request.input.response_text)
    section_plan = _build_section_plan(packet, config)
    sections = _build_sections(parsed_response, section_plan, config, warnings)
    full_script = "\n\n".join(section["narration_text"] for section in sections).strip()
    total_words = len(full_script.split())
    estimated_seconds = _estimated_seconds(total_words, int(config["words_per_minute"]))
    target_seconds = int(packet.get("target_duration_seconds", 0) or 0)

    if len(sections) != len(section_plan):
        errors.append(f"Expected {len(section_plan)} script sections, found {len(sections)}")
    if not full_script:
        errors.append("Parsed script is empty")
    if target_seconds and abs(estimated_seconds - target_seconds) > int(config["duration_tolerance_seconds"]):
        warnings.append(
            f"Estimated script duration is {estimated_seconds:.1f}s versus the {target_seconds}s target; "
            "voiceover timing will be the source of truth for visual production."
        )

    checks = {"passed": not errors, "errors": errors, "warnings": warnings}
    script_package = {
        "package_type": "roundup_script",
        "selected_format": "roundup",
        "generation_source": "chatgpt_handoff",
        "script_source": request.input.script_source or "manual_chatgpt_response",
        "target_duration_seconds": target_seconds,
        "intro_seconds": int(packet.get("intro_seconds", 0) or 0),
        "closing_seconds": int(packet.get("closing_seconds", 0) or 0),
        "story_count": len(packet.get("stories", [])),
        "selected_story_ids": list(packet.get("selected_story_ids", [])),
        "section_plan": section_plan,
        "story_usage_cards": [],
        "script_strategy": clean_text(parsed_response.get("notes", "")),
        "revision_notes_applied": [],
        "reflection": {
            "enabled": False,
            "iterations": [],
            "revision_count": 0,
            "final_score": None,
            "note": "Authored and reviewed through the manual ChatGPT handoff.",
        },
        "sections": sections,
        "full_script": full_script,
        "full_script_stats": {
            "total_word_count": total_words,
            "estimated_duration_seconds": estimated_seconds,
            "section_order": [section["section_id"] for section in sections],
        },
        "manual_handoff": {
            "response_version": parsed_response["response_version"],
            "notes": parsed_response.get("notes", ""),
            "metadata_text": parsed_response.get("metadata", ""),
            "section_parse_mode": parsed_response.get("section_parse_mode", "plain_script"),
        },
        "checks": checks,
    }
    status = "ok" if checks["passed"] else "failed"
    return {
        "status": status,
        "data": {
            "run_id": request.run.run_id,
            "generated_at": generated_at,
            "selected_format": "roundup",
            "script_package": script_package,
        },
        "summary": {
            "run_id": request.run.run_id,
            "generated_at": generated_at,
            "status": status,
            "selected_format": "roundup",
            "section_count": len(sections),
            "story_section_count": sum(1 for section in sections if section["section_type"] == "story"),
            "total_word_count": total_words,
            "estimated_duration_seconds": estimated_seconds,
            "llm_call_count": 0,
            "generation_source": "chatgpt_handoff",
            "failure_reason": "; ".join(errors),
            "checks": checks,
        },
        "handoff": {"ready_for_metadata_creation": status == "ok"},
        "llm_calls": [],
    }


def _parse_response(text: str) -> dict[str, Any]:
    raw = text.strip()
    if not raw or raw.startswith("Paste the full CHATGPT_PIPELINE_RESPONSE_V1 response here"):
        raise ValueError("ChatGPT response is empty or still contains the placeholder")
    if RESPONSE_MARKER not in raw[:500]:
        raise ValueError(f"ChatGPT response must start with or near {RESPONSE_MARKER}")

    sections = _top_level_sections(raw)
    script_text = sections["script"].strip()
    structured = _structured_sections(script_text)
    if structured is not None:
        return {
            "response_version": RESPONSE_MARKER,
            "notes": sections.get("notes", ""),
            "metadata": sections.get("metadata", ""),
            "structured_sections": structured,
            "script": "",
            "section_parse_mode": "structured_json",
        }
    inline = _inline_sections(script_text)
    if inline:
        return {
            "response_version": RESPONSE_MARKER,
            "notes": sections.get("notes", ""),
            "metadata": sections.get("metadata", ""),
            "structured_sections": inline,
            "script": "",
            "section_parse_mode": "inline_markers",
        }
    cleaned = _clean_script(script_text)
    if not cleaned:
        raise ValueError("Parsed [SCRIPT] section is empty")
    return {
        "response_version": RESPONSE_MARKER,
        "notes": sections.get("notes", ""),
        "metadata": sections.get("metadata", ""),
        "structured_sections": None,
        "script": cleaned,
        "section_parse_mode": "weighted_paragraph_fallback",
    }


def _top_level_sections(raw: str) -> dict[str, str]:
    positions: list[tuple[int, str, int]] = []
    for marker in SECTION_NAMES:
        token = f"[{marker}]"
        index = raw.find(token)
        if index < 0:
            raise ValueError(f"ChatGPT response is missing required section {token}")
        positions.append((index, marker.lower(), index + len(token)))
    positions.sort()
    output: dict[str, str] = {}
    for item_index, (_, name, content_start) in enumerate(positions):
        content_end = positions[item_index + 1][0] if item_index + 1 < len(positions) else len(raw)
        output[name] = raw[content_start:content_end].strip()
    return output


def _structured_sections(script_text: str) -> list[dict[str, str]] | None:
    if STRUCTURED_SECTION_MARKER not in script_text:
        return None
    payload = script_text.split(STRUCTURED_SECTION_MARKER, 1)[1].strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", payload, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        payload = fenced.group(1).strip()
    data = json.loads(payload)
    items = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("[SCRIPT_SECTIONS_JSON] must contain an object with a sections list")
    return [dict(item) for item in items if isinstance(item, dict)]


def _inline_sections(script_text: str) -> list[dict[str, str]]:
    matches = list(INLINE_SECTION_RE.finditer(script_text))
    if not matches:
        return []
    sections: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(script_text)
        sections.append(
            {
                "section_id": clean_text(match.group("section_id")),
                "narration_text": _clean_script(script_text[start:end]),
            }
        )
    return sections


def _build_sections(
    parsed_response: dict[str, Any],
    section_plan: list[dict[str, Any]],
    config: dict[str, Any],
    warnings: list[str],
) -> list[dict[str, Any]]:
    provided = parsed_response.get("structured_sections")
    if provided is None:
        warnings.append(
            "The response used the legacy plain [SCRIPT] format; sections were inferred by weighted paragraph order. "
            "Use [[SECTION:<section_id>]] markers for exact story boundaries."
        )
        narration_by_id = _partition_script(parsed_response["script"], section_plan)
    else:
        narration_by_id = {
            clean_text(item.get("section_id")): _clean_script(item.get("narration_text", ""))
            for item in provided
        }
    expected_ids = {plan["section_id"] for plan in section_plan}
    unexpected = sorted(set(narration_by_id) - expected_ids)
    if unexpected:
        warnings.append(f"Ignored unexpected script section IDs: {unexpected}")

    output: list[dict[str, Any]] = []
    words_per_minute = int(config["words_per_minute"])
    for plan in section_plan:
        narration = narration_by_id.get(plan["section_id"], "").strip()
        if not narration:
            raise ValueError(f"ChatGPT response is missing narration for {plan['section_id']}")
        used_story_ids = [plan["story_id"]] if plan["section_type"] == "story" else list(plan["allowed_story_ids"])
        used_source_keys = list(plan["allowed_source_record_keys"]) if plan["section_type"] == "story" else []
        words = len(narration.split())
        output.append(
            {
                "section_id": plan["section_id"],
                "section_type": plan["section_type"],
                "section_order": plan["section_order"],
                "story_id": plan["story_id"],
                "story_title": plan["story_title"],
                "role": plan["role"],
                "target_seconds": plan["target_seconds"],
                "word_budget": plan["word_budget"],
                "narration_text": narration,
                "word_count": words,
                "estimated_seconds": _estimated_seconds(words, words_per_minute),
                "used_story_ids": used_story_ids,
                "used_source_record_keys": used_source_keys,
                "analysis_sentences": [],
            }
        )
    return output


def _build_section_plan(packet: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    stories = sorted(
        packet["stories"],
        key=lambda story: int((story.get("video_segment") or {}).get("segment_order", 999999)),
    )
    words_per_minute = int(config["words_per_minute"])
    all_story_ids = [_story_id(story) for story in stories]
    all_source_keys = _dedupe(key for story in stories for key in _source_keys(story))
    plan = [
        _plan_item(
            section_id="section_00_intro",
            section_type="intro",
            order=0,
            target_seconds=int(packet.get("intro_seconds", 0) or 0),
            words_per_minute=words_per_minute,
            allowed_story_ids=all_story_ids,
            allowed_source_keys=all_source_keys,
        )
    ]
    for story in stories:
        segment = story.get("video_segment") or {}
        order = int(segment.get("segment_order", 0) or 0)
        sid = _story_id(story)
        plan.append(
            _plan_item(
                section_id=f"section_{order:02d}_{sid}",
                section_type="story",
                order=order,
                target_seconds=int(segment.get("target_seconds", 0) or 0),
                words_per_minute=words_per_minute,
                story_id=sid,
                story_title=clean_text(story.get("story_title") or story.get("title")),
                role=clean_text(segment.get("role")),
                allowed_story_ids=[sid],
                allowed_source_keys=_source_keys(story),
            )
        )
    plan.append(
        _plan_item(
            section_id="section_99_closing",
            section_type="closing",
            order=len(stories) + 1,
            target_seconds=int(packet.get("closing_seconds", 0) or 0),
            words_per_minute=words_per_minute,
            allowed_story_ids=all_story_ids,
            allowed_source_keys=all_source_keys,
        )
    )
    return plan


def _plan_item(
    *,
    section_id: str,
    section_type: str,
    order: int,
    target_seconds: int,
    words_per_minute: int,
    allowed_story_ids: list[str],
    allowed_source_keys: list[str],
    story_id: str = "",
    story_title: str = "",
    role: str = "",
) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "section_type": section_type,
        "section_order": order,
        "story_id": story_id,
        "story_title": story_title,
        "role": role,
        "target_seconds": target_seconds,
        "word_budget": max(1, round(target_seconds * words_per_minute / 60)),
        "allowed_story_ids": allowed_story_ids,
        "allowed_source_record_keys": allowed_source_keys,
    }


def _partition_script(script: str, section_plan: list[dict[str, Any]]) -> dict[str, str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", script) if part.strip()]
    if len(paragraphs) < len(section_plan):
        paragraphs = [part.strip() for part in re.split(r"(?<=[.!?])\s+", script) if part.strip()]
    if len(paragraphs) < len(section_plan):
        raise ValueError(
            f"Legacy [SCRIPT] response has {len(paragraphs)} usable blocks but {len(section_plan)} sections are required"
        )

    remaining = list(paragraphs)
    output: dict[str, str] = {}
    for index, plan in enumerate(section_plan):
        sections_left = len(section_plan) - index
        if sections_left == 1:
            chosen = remaining
            remaining = []
        else:
            target_words = max(1, int(plan["word_budget"]))
            max_take = len(remaining) - (sections_left - 1)
            take = 1
            words = len(remaining[0].split())
            while take < max_take and words < target_words:
                candidate_words = len(remaining[take].split())
                if words >= target_words * 0.65 and abs(words - target_words) <= abs(words + candidate_words - target_words):
                    break
                words += candidate_words
                take += 1
            chosen = remaining[:take]
            remaining = remaining[take:]
        output[plan["section_id"]] = "\n\n".join(chosen).strip()
    return output


def _clean_script(text: Any) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").replace("\r", "").split("\n"):
        line = raw_line.strip()
        if not line or line in {"---", "***"}:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line.startswith("```"):
            continue
        if line.lower().startswith("transition:"):
            line = line.split(":", 1)[1].strip()
        line = line.replace("**", "").strip()
        if line:
            lines.append(line)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _story_id(story: dict[str, Any]) -> str:
    sid = clean_text(story.get("story_id") or story.get("id"))
    if not sid:
        raise ValueError("Selected story is missing story_id")
    return sid


def _source_keys(story: dict[str, Any]) -> list[str]:
    segment = story.get("video_segment") or {}
    keys = list(segment.get("source_record_keys") or [])
    keys.extend(record.get("record_key", "") for record in story.get("records", []) if isinstance(record, dict))
    return _dedupe(keys)


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            output.append(cleaned)
    return output


def _estimated_seconds(words: int, words_per_minute: int) -> float:
    return round(words / words_per_minute * 60, 2) if words else 0.0
