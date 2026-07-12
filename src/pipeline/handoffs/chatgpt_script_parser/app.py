from __future__ import annotations

import json
import re
from typing import Any

from src.pipeline.contracts import build_script_provenance, require_matching_run_id
from src.pipeline.handoffs.common import clean_text, iso_now

from .contract import ChatGPTScriptParserRequest


RESPONSE_MARKER = "CHATGPT_PIPELINE_RESPONSE_V1"
SECTION_NAMES = ("NOTES", "SCRIPT", "METADATA")
STRUCTURED_SECTION_MARKER = "[SCRIPT_SECTIONS_JSON]"
INLINE_SECTION_RE = re.compile(r"^\[\[SECTION:(?P<section_id>[^\]]+)\]\]\s*$", re.MULTILINE)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"\b[\w'-]+\b")
ALLOWED_BEAT_TYPES = {
    "hook", "transition", "what_changed", "explanation", "example",
    "why_it_matters", "caveat", "takeaway", "intro", "conclusion",
}
ALLOWED_VISUAL_INTENTS = {
    "story_title", "source_proof", "entity_intro", "product_demo",
    "metric_explainer", "process_explainer", "comparison", "context_media",
    "transition", "takeaway",
}


def run(input_json: dict) -> dict:
    request = ChatGPTScriptParserRequest.model_validate(input_json)
    packet = request.input.video_packaging.data.video_packet
    config = request.config.model_dump(mode="json")
    generated_at = iso_now()
    errors: list[str] = []
    warnings: list[str] = []

    require_matching_run_id(
        request.run.run_id,
        request.input.video_packaging.data.run_id,
        "video_packaging",
    )

    parsed_response = _parse_response(request.input.response_text)
    section_plan = _build_section_plan(packet)
    sections = _build_sections(parsed_response, section_plan, packet, config, warnings)
    full_script = "\n\n".join(section["narration_text"] for section in sections).strip()
    total_words = _word_count(full_script)
    estimated_seconds = _estimated_seconds(total_words, int(config["diagnostic_words_per_minute"]))

    if len(sections) != len(section_plan):
        errors.append(f"Expected {len(section_plan)} script sections, found {len(sections)}")
    if not full_script:
        errors.append("Parsed script is empty")

    checks = {"passed": not errors, "errors": errors, "warnings": warnings}
    script_package = {
        "package_type": "roundup_script",
        "selected_format": "roundup",
        "generation_source": "chatgpt_handoff",
        "script_source": request.input.script_source or "manual_chatgpt_response",
        "duration_policy": _duration_policy(packet),
        "story_count": len(packet.get("stories", [])),
        "selected_story_ids": list(packet.get("selected_story_ids", [])),
        "section_plan": section_plan,
        "generation_strategy": "manual_story_sections_normalized_to_audiovisual_beats",
        "episode_direction": {
            "episode_thesis": clean_text(parsed_response.get("notes", "")),
            "viewer_promise": "",
            "hook_strategy": "manual_chatgpt_handoff",
            "pacing_strategy": "content_driven_story_sections",
            "ordered_story_ids": list(packet.get("selected_story_ids", [])),
            "story_briefs": [],
        },
        "story_segments": [_manual_story_segment(section) for section in sections if section["section_type"] == "story"],
        "story_asset_hints": [_story_asset_hints(story) for story in packet.get("stories", [])],
        "bookends": {
            "source": "manual_chatgpt_handoff",
            "intro_section_id": "section_00_intro",
            "closing_section_id": "section_99_closing",
        },
        "review": {
            "enabled": False,
            "story_reviews": [],
            "bookend_reviews": [],
            "revision_count": 0,
            "note": "Authored and reviewed through the manual ChatGPT handoff.",
        },
        "sections": sections,
        "full_script": full_script,
        "full_script_stats": {
            "total_word_count": total_words,
            "estimated_duration_seconds": estimated_seconds,
            "section_order": [section["section_id"] for section in sections],
            "beat_count": sum(len(section.get("beats", [])) for section in sections),
        },
        "audio_plan": {
            "unit_strategy": "one_audio_unit_per_section_with_beat_anchors",
            "units": [_audio_unit(section) for section in sections],
        },
        "manual_handoff": {
            "response_version": parsed_response["response_version"],
            "notes": parsed_response.get("notes", ""),
            "metadata_text": parsed_response.get("metadata", ""),
            "section_parse_mode": parsed_response.get("section_parse_mode", "plain_script"),
        },
        "checks": checks,
    }
    script_package["provenance"] = build_script_provenance(
        script_package,
        run_id=request.run.run_id,
        script_source=request.input.script_source or "manual_chatgpt_response",
    )
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
        "handoff": {
            "ready_for_metadata_creation": status == "ok",
            "ready_for_voiceover": status == "ok",
            "ready_for_visual_planning": status == "ok",
        },
        "llm_calls": [],
    }


def _parse_response(text: str) -> dict[str, Any]:
    raw = text.strip()
    if not raw or raw.startswith("Paste the full CHATGPT_PIPELINE_RESPONSE_V1 response here"):
        raise ValueError("ChatGPT response is empty or still contains the placeholder")
    response_marker = re.search(rf"^{re.escape(RESPONSE_MARKER)}\s*$", raw, flags=re.MULTILINE)
    if response_marker is None:
        raise ValueError(f"ChatGPT response must contain {RESPONSE_MARKER} as a standalone line")
    raw = raw[response_marker.start() :]

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
    packet: dict[str, Any],
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
        aliases = _section_id_aliases(packet, section_plan)
        narration_by_id: dict[str, str] = {}
        supplied_beats_by_id: dict[str, list[dict[str, Any]]] = {}
        normalized_count = 0
        for item in provided:
            supplied_id = clean_text(item.get("section_id"))
            if not supplied_id:
                raise ValueError("ChatGPT response contains a script section without section_id")
            canonical_id = aliases.get(supplied_id, aliases.get(supplied_id.lower(), supplied_id))
            if canonical_id in narration_by_id:
                raise ValueError(
                    f"ChatGPT response maps more than one script section to {canonical_id}; "
                    "return each required marker exactly once"
                )
            supplied_beats = item.get("beats") if isinstance(item.get("beats"), list) else []
            narration = _clean_script(item.get("narration_text", ""))
            if not narration and supplied_beats:
                narration = " ".join(_clean_script(beat.get("narration_text", "")) for beat in supplied_beats).strip()
            narration_by_id[canonical_id] = narration
            if supplied_beats:
                supplied_beats_by_id[canonical_id] = [dict(beat) for beat in supplied_beats if isinstance(beat, dict)]
            normalized_count += int(canonical_id != supplied_id)
        if normalized_count:
            warnings.append(
                f"Normalized {normalized_count} packet script markers to canonical section IDs."
            )
    expected_ids = {plan["section_id"] for plan in section_plan}
    unexpected = sorted(set(narration_by_id) - expected_ids)
    if unexpected:
        warnings.append(f"Ignored unexpected script section IDs: {unexpected}")

    if provided is None:
        supplied_beats_by_id = {}
    output: list[dict[str, Any]] = []
    words_per_minute = int(config["diagnostic_words_per_minute"])
    for plan in section_plan:
        narration = narration_by_id.get(plan["section_id"], "").strip()
        if not narration:
            raise ValueError(f"ChatGPT response is missing narration for {plan['section_id']}")
        used_story_ids = [plan["story_id"]] if plan["section_type"] == "story" else list(plan["allowed_story_ids"])
        used_source_keys = list(plan["allowed_source_record_keys"]) if plan["section_type"] == "story" else []
        beats = _build_beats(
            narration=narration,
            plan=plan,
            words_per_minute=words_per_minute,
            supplied_beats=supplied_beats_by_id.get(plan["section_id"], []),
        )
        normalized_narration = " ".join(beat["narration_text"] for beat in beats).strip()
        normalized_words = _word_count(normalized_narration)
        title_card = None
        if plan["section_type"] == "story":
            title_card = {
                "display_title": plan["story_title"],
                "subtitle": "",
                "duration_seconds": round(float(config["title_card_seconds"]), 2),
                "voice_behavior": "continue",
                "anchor_beat_id": beats[0]["beat_id"],
            }
        output.append(
            {
                "section_id": plan["section_id"],
                "section_type": plan["section_type"],
                "section_order": plan["section_order"],
                "story_id": plan["story_id"],
                "story_title": plan["story_title"],
                "role": plan["role"],
                "writing_guidance": plan.get("writing_guidance", {}),
                "title_card": title_card,
                "beats": beats,
                "narration_text": normalized_narration,
                "word_count": normalized_words,
                "estimated_seconds": _estimated_seconds(normalized_words, words_per_minute),
                "used_story_ids": used_story_ids,
                "used_source_record_keys": used_source_keys,
                "analysis_sentences": [],
            }
        )
    return output


def _build_beats(
    *,
    narration: str,
    plan: dict[str, Any],
    words_per_minute: int,
    supplied_beats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if supplied_beats:
        drafts = supplied_beats
    else:
        target_count = _suggested_beat_count(plan)
        drafts = _draft_beats_from_prose(narration, target_count=target_count, section_type=plan["section_type"])
    allowed_keys = set(plan.get("allowed_source_record_keys", []))
    output: list[dict[str, Any]] = []
    for order, draft in enumerate(drafts, start=1):
        text = _clean_script(draft.get("narration_text", ""))
        if not text:
            continue
        raw_keys = draft.get("source_record_keys") if isinstance(draft.get("source_record_keys"), list) else []
        source_keys = _dedupe(raw_keys or (list(allowed_keys) if plan["section_type"] == "story" else []))
        unknown = sorted(set(source_keys) - allowed_keys)
        if unknown:
            raise ValueError(f"{plan['section_id']} beat uses unknown source keys: {unknown}")
        beat_type = clean_text(draft.get("beat_type")) or _default_beat_type(plan["section_type"], order, len(drafts))
        if beat_type not in ALLOWED_BEAT_TYPES:
            raise ValueError(f"{plan['section_id']} returned unsupported beat_type: {beat_type}")
        visual_brief = draft.get("visual_brief") if isinstance(draft.get("visual_brief"), dict) else {}
        output.append(
            {
                "beat_id": f"{plan['section_id']}_beat_{order:02d}",
                "beat_order": order,
                "beat_type": beat_type,
                "story_id": plan.get("story_id", ""),
                "narration_text": text,
                "word_count": _word_count(text),
                "estimated_seconds": _estimated_seconds(_word_count(text), words_per_minute),
                "source_record_keys": source_keys,
                "visual_brief": _normalize_visual_brief(visual_brief, plan, order),
            }
        )
    if not output:
        raise ValueError(f"{plan['section_id']} produced no usable beats")
    return output


def _suggested_beat_count(plan: dict[str, Any]) -> int:
    if plan["section_type"] == "intro":
        return 2
    if plan["section_type"] == "closing":
        return 1
    return {
        "lead": 6,
        "major": 5,
        "brief": 3,
    }.get(clean_text(plan.get("role")), 4)


def _draft_beats_from_prose(narration: str, *, target_count: int, section_type: str) -> list[dict[str, Any]]:
    sentences = [part.strip() for part in SENTENCE_RE.split(clean_text(narration)) if part.strip()]
    if not sentences:
        sentences = [clean_text(narration)]
    count = min(max(1, target_count), len(sentences))
    groups: list[list[str]] = []
    for index in range(count):
        start = round(index * len(sentences) / count)
        end = round((index + 1) * len(sentences) / count)
        groups.append(sentences[start:end])
    return [
        {
            "beat_type": _default_beat_type(section_type, index, len(groups)),
            "narration_text": " ".join(group),
        }
        for index, group in enumerate(groups, start=1)
        if group
    ]


def _default_beat_type(section_type: str, order: int, count: int) -> str:
    if section_type == "intro":
        return "hook" if order == 1 else "intro"
    if section_type == "closing":
        return "conclusion"
    if order == 1:
        return "transition"
    if order == count:
        return "takeaway"
    return "explanation"


def _normalize_visual_brief(raw: dict[str, Any], plan: dict[str, Any], order: int) -> dict[str, Any]:
    story = plan["section_type"] == "story"
    default_intent = "story_title" if story and order == 1 else ("source_proof" if story else "transition")
    preferred = raw.get("preferred_asset_types") if isinstance(raw.get("preferred_asset_types"), list) else []
    if not preferred:
        preferred = ["source_page", "logo"] if story else ["kinetic_text"]
    visual_intent = clean_text(raw.get("visual_intent")) or default_intent
    if visual_intent not in ALLOWED_VISUAL_INTENTS:
        raise ValueError(f"{plan['section_id']} returned unsupported visual_intent: {visual_intent}")
    return {
        "purpose": clean_text(raw.get("purpose")) or "Visually reinforce this exact narration beat.",
        "visual_intent": visual_intent,
        "preferred_asset_types": _dedupe(preferred),
        "must_show": _dedupe(raw.get("must_show", []) if isinstance(raw.get("must_show"), list) else []),
        "on_screen_text": clean_text(raw.get("on_screen_text"))[:90],
        "avoid": _dedupe(raw.get("avoid", []) if isinstance(raw.get("avoid"), list) else []),
    }


def _audio_unit(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "audio_unit_id": f"audio_{section['section_id']}",
        "section_id": section["section_id"],
        "section_type": section["section_type"],
        "story_id": section.get("story_id", ""),
        "story_title": section.get("story_title", ""),
        "narration_text": section["narration_text"],
        "beat_ids": [beat["beat_id"] for beat in section.get("beats", [])],
    }


def _manual_story_segment(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "story_id": section.get("story_id", ""),
        "display_title": section.get("story_title", ""),
        "story_thesis": "",
        "viewer_takeaway": "",
        "beats": section.get("beats", []),
    }


def _story_asset_hints(story: dict[str, Any]) -> dict[str, Any]:
    identity = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
    source_pages = []
    for record in story.get("records", []):
        if not isinstance(record, dict):
            continue
        url = next(
            (
                clean_text(record.get(key))
                for key in ("url", "source_url", "canonical_url", "resolved_url")
                if clean_text(record.get(key)).startswith(("http://", "https://"))
            ),
            "",
        )
        record_key = clean_text(record.get("record_key"))
        if url and record_key:
            source_pages.append(
                {
                    "record_key": record_key,
                    "url": url,
                    "title": clean_text(record.get("title")),
                    "source": clean_text(record.get("source_name") or record.get("source")),
                }
            )
    entities = _dedupe(
        [
            identity.get("primary_entity", ""),
            identity.get("owning_org", ""),
            identity.get("product_or_project", ""),
        ]
    )
    return {
        "story_id": _story_id(story),
        "source_pages": source_pages,
        "logo_entities": entities,
        "product_surfaces": [clean_text(identity.get("product_or_project"))] if clean_text(identity.get("product_or_project")) else [],
        "metric_candidates": [],
        "available_asset_types": _dedupe(
            [
                *("source_page" for _ in source_pages[:1]),
                *("logo" for _ in entities[:1]),
                "diagram",
                "photo",
                "video",
                "kinetic_text",
            ]
        ),
    }


def _section_id_aliases(
    packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
) -> dict[str, str]:
    aliases = {plan["section_id"]: plan["section_id"] for plan in section_plan}
    aliases.update(
        {
            "intro": "section_00_intro",
            "closing": "section_99_closing",
        }
    )
    canonical_by_story = {
        plan["story_id"]: plan["section_id"]
        for plan in section_plan
        if plan["section_type"] == "story"
    }
    for story in packet.get("stories", []):
        story_id = _story_id(story)
        canonical_id = canonical_by_story.get(story_id)
        if canonical_id is None:
            continue
        segment = story.get("video_segment") or {}
        segment_id = clean_text(segment.get("segment_id"))
        if segment_id:
            existing = aliases.get(segment_id)
            if existing is not None and existing != canonical_id:
                raise ValueError(f"Duplicate video segment marker maps to multiple stories: {segment_id}")
            aliases[segment_id] = canonical_id
    return aliases


def _build_section_plan(packet: dict[str, Any]) -> list[dict[str, Any]]:
    stories = sorted(
        packet["stories"],
        key=lambda story: int((story.get("video_segment") or {}).get("segment_order", 999999)),
    )
    all_story_ids = [_story_id(story) for story in stories]
    all_source_keys = _dedupe(key for story in stories for key in _source_keys(story))
    plan = [
        _plan_item(
            section_id="section_00_intro",
            section_type="intro",
            order=0,
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
        "writing_guidance": _manual_writing_guidance(section_type, role),
        "allowed_story_ids": allowed_story_ids,
        "allowed_source_record_keys": allowed_source_keys,
    }


def _manual_writing_guidance(section_type: str, role: str) -> dict[str, Any]:
    key = section_type if section_type != "story" else (clean_text(role) or "major")
    defaults = {
        "intro": (70, "Hook the viewer and preview the episode without listing every headline."),
        "lead": (240, "Explain the strongest story fully, clearly, and without padding."),
        "major": (180, "Cover what changed, why it matters, and the useful caveat."),
        "brief": (120, "Deliver the essential update without stretching limited material."),
        "closing": (45, "Synthesize the episode and end naturally without repeating every story."),
    }
    suggested_words, editorial_goal = defaults.get(key, defaults["major"])
    return {
        "suggested_words": suggested_words,
        "editorial_goal": editorial_goal,
        "enforcement": "soft_editorial_guidance_only",
    }


def _partition_script(script: str, section_plan: list[dict[str, Any]]) -> dict[str, str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", script) if part.strip()]
    if len(paragraphs) < len(section_plan):
        paragraphs = [part.strip() for part in re.split(r"(?<=[.!?])\s+", script) if part.strip()]
    if len(paragraphs) < len(section_plan):
        raise ValueError(
            f"Legacy [SCRIPT] response has {len(paragraphs)} usable blocks but {len(section_plan)} sections are required"
        )

    output = {
        section_plan[0]["section_id"]: paragraphs[0],
        section_plan[-1]["section_id"]: paragraphs[-1],
    }
    story_plans = section_plan[1:-1]
    middle = paragraphs[1:-1]
    base, remainder = divmod(len(middle), len(story_plans))
    cursor = 0
    for index, plan in enumerate(story_plans):
        take = base + (1 if index < remainder else 0)
        chosen = middle[cursor : cursor + take]
        cursor += take
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


def _word_count(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def _duration_policy(packet: dict[str, Any]) -> dict[str, Any]:
    policy = dict(packet.get("duration_policy") or {})
    if not policy:
        policy = {
            "mode": "content_driven",
            "configured_ceiling_seconds": packet.get("target_duration_seconds"),
            "timing_source_of_truth": "voiceover",
        }
    policy.setdefault("mode", "content_driven")
    policy.setdefault("timing_source_of_truth", "voiceover")
    return policy
