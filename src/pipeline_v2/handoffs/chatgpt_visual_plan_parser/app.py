from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any

from src.pipeline_v2.handoffs.common import clean_text, iso_now

from .contract import ChatGPTVisualPlanParserRequest


PACKAGE_TYPE = "visual_scene_plan"
SUPPORTED_FORMAT = "roundup"
NEXT_MODULE = "visuals.media_discovery"
RESPONSE_MARKER = "CHATGPT_VISUAL_PLAN_RESPONSE_V1"
JSON_SECTION = "[VISUAL_SCENE_PLAN_JSON]"
OLD_CARD_RENDER_KINDS = {
    "title_card",
    "timeline_card",
    "entity_card",
    "recap_card",
    "fallback_card",
    "quote_card",
    "data_card",
}
DEFAULT_RENDER_KINDS = {
    "source_article_scene",
    "context_image_scene",
    "broll_video_scene",
    "logo_reveal_scene",
    "kinetic_type_scene",
    "bullet_build_scene",
    "quote_or_claim_highlight_scene",
    "entity_compare_scene",
    "recap_sequence_scene",
    "data_counter_scene",
    "trend_line_scene",
    "bar_chart_scene",
    "bar_race_scene",
    "ranked_list_scene",
    "benchmark_delta_scene",
    "ecosystem_map_scene",
    "architecture_flow_scene",
    "process_zoom_scene",
    "browser_walkthrough_scene",
    "decision_tree_scene",
    "capability_matrix_scene",
    "timeline_zoom_scene",
    "document_stack_scene",
    "signal_radar_scene",
    "interface_transform_scene",
    "transition_stinger_scene",
}
SOURCE_BACKED_RENDER_KINDS = {"source_article_scene", "quote_or_claim_highlight_scene"}
LOGO_RENDER_KINDS = {"logo_reveal_scene"}
MEDIA_RENDER_KINDS = {"context_image_scene", "broll_video_scene"}
TEXT_LIKE_RENDER_KINDS = {"kinetic_type_scene", "bullet_build_scene", "recap_sequence_scene", "transition_stinger_scene"}
GRAPHIC_RENDER_KINDS = DEFAULT_RENDER_KINDS - SOURCE_BACKED_RENDER_KINDS
GENERIC_PLACEHOLDER_PHRASES = {
    "manual process",
    "old systems",
    "slow handoffs",
    "faster workflow",
    "new ai signal",
    "process change",
    "watch next",
    "decision point",
    "best fit",
    "momentum shift",
    "biggest delta",
}


def run(input_json: dict) -> dict:
    request = ChatGPTVisualPlanParserRequest.model_validate(input_json)
    generated_at = iso_now()
    run_id = request.run.run_id
    video_packet = request.input.video_packaging.data.video_packet
    selected_format = clean_text(request.input.video_packaging.data.selected_format or video_packet.get("selected_format", ""))

    errors: list[str] = []
    warnings: list[str] = []
    if selected_format and selected_format != SUPPORTED_FORMAT:
        errors.append(f"selected_format={selected_format!r} is not supported; only {SUPPORTED_FORMAT!r} is implemented")

    if RESPONSE_MARKER not in request.input.response_text:
        warnings.append(f"Response marker {RESPONSE_MARKER!r} was not found; parsing best-effort JSON anyway.")

    parsed = _parse_response_json(request.input.response_text, errors)
    scenes_raw = parsed.get("scene_timeline", []) if isinstance(parsed, dict) else []
    if not isinstance(scenes_raw, list):
        errors.append("VISUAL_SCENE_PLAN_JSON.scene_timeline must be a list")
        scenes_raw = []
    story_sections = _normalize_story_sections(parsed.get("story_sections", []))

    source_index = _build_source_index(video_packet)
    allowed_render_kinds = _allowed_render_kinds(request.config.scene_policy, request.config.visual_capabilities)
    scene_timeline = _normalize_scenes(
        scenes=scenes_raw,
        allowed_render_kinds=allowed_render_kinds,
        source_index=source_index,
        errors=errors,
        warnings=warnings,
    )
    scene_timeline = _reconcile_scene_sections(scene_timeline, story_sections, warnings)
    expected_duration = _expected_duration_seconds(request.input.voiceover, request.input.script_text)
    scene_timeline = _close_timeline_gaps(
        scenes=scene_timeline,
        expected_duration=expected_duration,
        scene_policy=request.config.scene_policy,
        allowed_render_kinds=allowed_render_kinds,
        warnings=warnings,
    )
    scene_timeline = _compact_semantic_scenes(
        scenes=scene_timeline,
        scene_policy=request.config.scene_policy,
        warnings=warnings,
    )
    scene_timeline = _attach_scene_beats(
        scenes=scene_timeline,
        voiceover=request.input.voiceover,
        warnings=warnings,
    )
    coverage = _coverage_report(
        scenes=scene_timeline,
        expected_duration=expected_duration,
        scene_policy=request.config.scene_policy,
        require_complete=request.config.require_complete_timeline,
        tolerance=request.config.gap_tolerance_seconds,
        errors=errors,
        warnings=warnings,
    )
    placeholder_scenes = _generic_placeholder_scenes(scene_timeline)
    if placeholder_scenes:
        warnings.append(f"Visual payloads contain generic placeholder labels that may feel disconnected: {placeholder_scenes[:8]}")
    visual_scene_plan = {
        "package_type": PACKAGE_TYPE,
        "selected_format": SUPPORTED_FORMAT,
        "planning_strategy": "chatgpt_visual_scene_plan_handoff",
        "run_id": run_id,
        "generated_at": generated_at,
        "episode_style": parsed.get("episode_style", {}) if isinstance(parsed.get("episode_style"), dict) else {},
        "story_plans": parsed.get("story_plans", []) if isinstance(parsed.get("story_plans"), list) else [],
        "story_sections": story_sections,
        "visual_beat_map": _visual_beat_map(scene_timeline),
        "scene_timeline": scene_timeline,
        "asset_manifest": _build_asset_manifest(scene_timeline),
        "coverage": coverage,
        "planning_calls": [
            {
                "module_name": "chatgpt_visual_scene_plan_handoff",
                "provider": "chatgpt_manual",
                "model": "external_chatgpt",
                "metadata": {
                    "response_marker_found": RESPONSE_MARKER in request.input.response_text,
                    "scene_count": len(scene_timeline),
                },
            }
        ],
        "source_script": {
            "script_source": clean_text(request.input.script_source or "manual_chatgpt_script"),
            "word_count": len(request.input.script_text.split()),
        },
        "audio_timeline": _audio_timeline(request.input.voiceover, expected_duration),
        "scene_policy": request.config.scene_policy,
        "visual_capabilities": request.config.visual_capabilities,
        "source_context": {
            "selected_story_ids": sorted(source_index["story_ids"]),
            "source_url_count": len(source_index["source_urls"]),
            "source_urls": sorted(source_index["source_urls"]),
        },
        "planner_warnings": warnings,
    }
    checks = {"passed": not errors, "errors": errors, "warnings": warnings}
    visual_scene_plan["checks"] = checks
    status = "ok" if checks["passed"] else "failed"
    summary = _build_summary(
        visual_scene_plan=visual_scene_plan,
        status=status,
        errors=errors,
        warnings=warnings,
    )
    return {
        "status": status,
        "data": {
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": SUPPORTED_FORMAT,
            "visual_scene_plan": visual_scene_plan,
        },
        "summary": summary,
        "handoff": {
            "ready_for_visual_asset_resolution": status == "ok",
            "ready_for_visual_media_discovery": status == "ok",
            "next_module": NEXT_MODULE,
            "selected_format": SUPPORTED_FORMAT,
        },
    }


def _parse_response_json(response_text: str, errors: list[str]) -> dict[str, Any]:
    section = response_text.split(JSON_SECTION, 1)[1] if JSON_SECTION in response_text else response_text
    section = _strip_json_fence(section)
    json_text = _first_json_object(section)
    if not json_text:
        errors.append("Could not find a JSON object after [VISUAL_SCENE_PLAN_JSON].")
        return {}
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        errors.append(f"Visual scene plan JSON is invalid: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append("Visual scene plan JSON must be an object.")
        return {}
    return data


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    return fence.group(1).strip() if fence else stripped


def _first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _allowed_render_kinds(scene_policy: dict[str, Any], visual_capabilities: dict[str, Any]) -> set[str]:
    allowed = scene_policy.get("allowed_render_kinds")
    if isinstance(allowed, list) and allowed:
        return {clean_text(kind) for kind in allowed if clean_text(kind)}
    if visual_capabilities:
        return {clean_text(kind) for kind in visual_capabilities.keys() if clean_text(kind)}
    return set(DEFAULT_RENDER_KINDS)


def _normalize_scenes(
    *,
    scenes: list[Any],
    allowed_render_kinds: set[str],
    source_index: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    previous_end = 0.0
    for index, scene_obj in enumerate(scenes, start=1):
        if not isinstance(scene_obj, dict):
            errors.append(f"scene #{index} must be an object")
            continue
        render_kind = clean_text(scene_obj.get("render_kind", ""))
        scene_id = clean_text(scene_obj.get("scene_id", "")) or f"scene_{index:03d}"
        if render_kind in OLD_CARD_RENDER_KINDS:
            errors.append(f"{scene_id}: old card render kind is not allowed: {render_kind}")
        if render_kind not in allowed_render_kinds:
            errors.append(f"{scene_id}: unsupported render_kind: {render_kind}")
        payload = dict(scene_obj.get("payload")) if isinstance(scene_obj.get("payload"), dict) else {}
        start = _safe_float(scene_obj.get("start_seconds"), previous_end)
        end = _safe_float(scene_obj.get("end_seconds"), start)
        if end <= start:
            errors.append(f"{scene_id}: end_seconds must be greater than start_seconds")
            end = start + 1.0
        story_id = clean_text(scene_obj.get("story_id", ""))
        source_record_key = clean_text(payload.get("source_record_key", ""))
        source_url = _extract_url(payload.get("url", ""))
        if render_kind in SOURCE_BACKED_RENDER_KINDS:
            source_record_key, source_url = _repair_source_reference(
                scene_id=scene_id,
                story_id=story_id,
                source_record_key=source_record_key,
                source_url=source_url,
                source_index=source_index,
                errors=errors,
                warnings=warnings,
            )
            if source_record_key:
                payload["source_record_key"] = source_record_key
            if source_url:
                payload["url"] = source_url
        elif source_record_key or source_url:
            warnings.append(f"{scene_id}: source fields are ignored for non-source scene {render_kind}.")
        if render_kind in MEDIA_RENDER_KINDS:
            search_queries = payload.get("search_queries") if isinstance(payload.get("search_queries"), list) else []
            if not any(clean_text(query) for query in search_queries):
                errors.append(f"{scene_id}: {render_kind} requires payload.search_queries")
        normalized.append(
            {
                "scene_id": scene_id,
                "scene_order": _safe_int(scene_obj.get("scene_order"), index),
                "story_id": story_id,
                "section_type": clean_text(scene_obj.get("section_type", "")) or ("story" if story_id else "transition"),
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "duration_seconds": round(end - start, 2),
                "render_kind": render_kind,
                "script_excerpt": clean_text(scene_obj.get("script_excerpt", "")),
                "visual_intent": clean_text(scene_obj.get("visual_intent", "")),
                "payload": payload,
                "source_record_keys": [source_record_key] if source_record_key else [],
                "source_urls": [source_url] if source_url else [],
                "covered_unit_orders": scene_obj.get("covered_unit_orders", []) if isinstance(scene_obj.get("covered_unit_orders"), list) else [],
            }
        )
        previous_end = end
    return sorted(normalized, key=lambda scene: (_safe_float(scene.get("start_seconds"), 0), _safe_int(scene.get("scene_order"), 999999)))


def _normalize_story_sections(raw_sections: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_sections, list):
        return []
    sections: list[dict[str, Any]] = []
    for index, section in enumerate(raw_sections, start=1):
        if not isinstance(section, dict):
            continue
        start = _safe_float(section.get("start_seconds"), 0.0)
        end = _safe_float(section.get("end_seconds"), start)
        if end <= start:
            continue
        section_type = clean_text(section.get("section_type", "")) or ("story" if clean_text(section.get("story_id", "")) else "transition")
        sections.append(
            {
                **section,
                "section_id": clean_text(section.get("section_id", "")) or f"section_{index:02d}",
                "section_type": section_type,
                "story_id": clean_text(section.get("story_id", "")),
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
            }
        )
    return sorted(sections, key=lambda item: _safe_float(item.get("start_seconds"), 0.0))


def _reconcile_scene_sections(scenes: list[dict[str, Any]], story_sections: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
    if not scenes or not story_sections:
        return scenes
    reconciled: list[dict[str, Any]] = []
    changed = 0
    for scene in scenes:
        current = dict(scene)
        midpoint = (_safe_float(scene.get("start_seconds"), 0.0) + _safe_float(scene.get("end_seconds"), 0.0)) / 2
        section = _section_for_time(midpoint, story_sections)
        if section:
            section_type = clean_text(section.get("section_type", ""))
            story_id = clean_text(section.get("story_id", ""))
            if current.get("section_type") != section_type or current.get("story_id") != story_id:
                changed += 1
            current["section_type"] = section_type
            current["story_id"] = story_id
        reconciled.append(current)
    if changed:
        warnings.append(f"Reconciled section_type/story_id for {changed} scene(s) using story_sections timing.")
    return reconciled


def _section_for_time(seconds: float, story_sections: list[dict[str, Any]]) -> dict[str, Any] | None:
    for section in story_sections:
        start = _safe_float(section.get("start_seconds"), 0.0)
        end = _safe_float(section.get("end_seconds"), start)
        if start - 0.01 <= seconds <= end + 0.01:
            return section
    return None


def _close_timeline_gaps(
    *,
    scenes: list[dict[str, Any]],
    expected_duration: float,
    scene_policy: dict[str, Any],
    allowed_render_kinds: set[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    if not scenes:
        return []
    max_scene_seconds = _safe_float(scene_policy.get("max_scene_seconds"), 14.0)
    sorted_scenes = [dict(scene) for scene in sorted(scenes, key=lambda item: (_safe_float(item.get("start_seconds"), 0.0), _safe_int(item.get("scene_order"), 999999)))]
    adjusted_gap_count = 0
    filler_count = 0
    output: list[dict[str, Any]] = []

    first = sorted_scenes[0]
    first_start = _safe_float(first.get("start_seconds"), 0.0)
    if first_start > 0.01:
        if _scene_duration(first) + first_start <= max_scene_seconds + 0.01:
            first["start_seconds"] = 0.0
            _refresh_scene_duration(first)
            adjusted_gap_count += 1
        else:
            fillers = _gap_filler_scenes(
                start=0.0,
                end=first_start,
                allowed_render_kinds=allowed_render_kinds,
                index_start=1,
            )
            filler_count += len(fillers)
            output.extend(fillers)

    for scene in sorted_scenes:
        start = _safe_float(scene.get("start_seconds"), 0.0)
        if output:
            prev = output[-1]
            prev_end = _safe_float(prev.get("end_seconds"), start)
            gap = start - prev_end
            if gap > 0.01:
                if _scene_duration(prev) + gap <= max_scene_seconds + 0.01:
                    prev["end_seconds"] = round(start, 2)
                    _refresh_scene_duration(prev)
                    adjusted_gap_count += 1
                elif _scene_duration(scene) + gap <= max_scene_seconds + 0.01:
                    scene["start_seconds"] = round(prev_end, 2)
                    _refresh_scene_duration(scene)
                    adjusted_gap_count += 1
                else:
                    fillers = _gap_filler_scenes(
                        start=prev_end,
                        end=start,
                        allowed_render_kinds=allowed_render_kinds,
                        index_start=filler_count + 1,
                    )
                    filler_count += len(fillers)
                    output.extend(fillers)
        output.append(scene)

    if expected_duration > 0 and output:
        last = output[-1]
        last_end = _safe_float(last.get("end_seconds"), 0.0)
        gap = expected_duration - last_end
        if gap > 0.01:
            if _scene_duration(last) + gap <= max_scene_seconds + 0.01:
                last["end_seconds"] = round(expected_duration, 2)
                _refresh_scene_duration(last)
                adjusted_gap_count += 1
            else:
                fillers = _gap_filler_scenes(
                    start=last_end,
                    end=expected_duration,
                    allowed_render_kinds=allowed_render_kinds,
                    index_start=filler_count + 1,
                )
                filler_count += len(fillers)
                output.extend(fillers)

    if adjusted_gap_count:
        warnings.append(f"Closed {adjusted_gap_count} visual timeline gap(s) by extending adjacent scenes.")
    if filler_count:
        warnings.append(f"Inserted {filler_count} transition filler scene(s) to cover larger visual timeline gaps.")
    return _renumber_scenes(output)


def _compact_semantic_scenes(
    *,
    scenes: list[dict[str, Any]],
    scene_policy: dict[str, Any],
    warnings: list[str],
) -> list[dict[str, Any]]:
    if not scene_policy.get("compact_per_chunk_scenes", True) or len(scenes) < 2:
        return _renumber_scenes(scenes)
    compacted = [dict(scene) for scene in sorted(scenes, key=lambda item: (_safe_float(item.get("start_seconds"), 0.0), _safe_int(item.get("scene_order"), 999999)))]
    merge_count = 0
    changed = True
    while changed:
        changed = False
        for index in range(len(compacted) - 1):
            if _should_merge_semantic_neighbors(compacted[index], compacted[index + 1], scene_policy):
                compacted[index : index + 2] = [_merge_adjacent_scenes(compacted[index], compacted[index + 1])]
                merge_count += 1
                changed = True
                break
    if merge_count:
        warnings.append(f"Compacted {merge_count} tiny/per-chunk scene pair(s) into semantic visual scenes.")
    return _renumber_scenes(compacted)


def _should_merge_semantic_neighbors(first: dict[str, Any], second: dict[str, Any], scene_policy: dict[str, Any]) -> bool:
    if clean_text(first.get("story_id", "")) != clean_text(second.get("story_id", "")):
        return False
    if clean_text(first.get("section_type", "")) != clean_text(second.get("section_type", "")):
        return False
    first_kind = clean_text(first.get("render_kind", ""))
    second_kind = clean_text(second.get("render_kind", ""))
    if first_kind in SOURCE_BACKED_RENDER_KINDS or second_kind in SOURCE_BACKED_RENDER_KINDS:
        return False
    start = _safe_float(first.get("start_seconds"), 0.0)
    end = _safe_float(second.get("end_seconds"), start)
    combined = max(0.0, end - start)
    max_seconds = _safe_float(scene_policy.get("max_scene_seconds"), 14.0)
    min_seconds = _safe_float(scene_policy.get("semantic_min_scene_seconds"), max(5.0, _safe_float(scene_policy.get("min_scene_seconds"), 3.0)))
    target_seconds = min(max_seconds, max(min_seconds, _safe_float(scene_policy.get("semantic_target_scene_seconds"), 9.0)))
    if combined > target_seconds + 0.01:
        return False
    if first_kind == second_kind and first_kind in TEXT_LIKE_RENDER_KINDS:
        return True
    if _scene_headline(first) and _scene_headline(first) == _scene_headline(second):
        return True
    if _scene_duration(first) < min_seconds or _scene_duration(second) < min_seconds:
        return True
    first_units = [unit for unit in first.get("covered_unit_orders", []) if _safe_int(unit, 0)]
    second_units = [unit for unit in second.get("covered_unit_orders", []) if _safe_int(unit, 0)]
    if len(first_units) <= 1 and len(second_units) <= 1 and first_kind in GRAPHIC_RENDER_KINDS and second_kind in GRAPHIC_RENDER_KINDS:
        return True
    return False


def _merge_adjacent_scenes(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    preferred = _preferred_scene_for_merge(first, second)
    start = _safe_float(first.get("start_seconds"), 0.0)
    end = _safe_float(second.get("end_seconds"), start)
    script_excerpt = _short_text(" ".join([clean_text(first.get("script_excerpt", "")), clean_text(second.get("script_excerpt", ""))]), 420)
    payload = _merged_payload_for_scene(preferred, first, second, script_excerpt, start)
    return {
        **preferred,
        "start_seconds": round(start, 2),
        "end_seconds": round(end, 2),
        "duration_seconds": round(max(0.0, end - start), 2),
        "script_excerpt": script_excerpt,
        "payload": payload,
        "covered_unit_orders": sorted(set(_safe_int(unit, 0) for unit in first.get("covered_unit_orders", [])) | set(_safe_int(unit, 0) for unit in second.get("covered_unit_orders", []))),
        "source_record_keys": list(dict.fromkeys([*first.get("source_record_keys", []), *second.get("source_record_keys", [])])),
        "source_urls": list(dict.fromkeys([*first.get("source_urls", []), *second.get("source_urls", [])])),
    }


def _preferred_scene_for_merge(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    priority = {
        "benchmark_delta_scene": 0,
        "broll_video_scene": 1,
        "context_image_scene": 2,
        "bar_chart_scene": 3,
        "bar_race_scene": 4,
        "browser_walkthrough_scene": 5,
        "decision_tree_scene": 6,
        "capability_matrix_scene": 7,
        "timeline_zoom_scene": 8,
        "document_stack_scene": 9,
        "signal_radar_scene": 10,
        "interface_transform_scene": 11,
        "process_zoom_scene": 12,
        "architecture_flow_scene": 13,
        "ecosystem_map_scene": 14,
        "entity_compare_scene": 15,
        "data_counter_scene": 16,
        "trend_line_scene": 17,
        "logo_reveal_scene": 18,
        "ranked_list_scene": 19,
        "bullet_build_scene": 20,
        "kinetic_type_scene": 21,
        "recap_sequence_scene": 22,
        "transition_stinger_scene": 23,
    }
    first_kind = clean_text(first.get("render_kind", ""))
    second_kind = clean_text(second.get("render_kind", ""))
    if priority.get(second_kind, 99) < priority.get(first_kind, 99):
        return dict(second)
    return dict(first)


def _merged_payload_for_scene(preferred: dict[str, Any], first: dict[str, Any], second: dict[str, Any], script_excerpt: str, scene_start_seconds: float) -> dict[str, Any]:
    payload = dict(preferred.get("payload", {})) if isinstance(preferred.get("payload"), dict) else {}
    beats = _merge_scene_beats(first, second, scene_start_seconds)
    if beats:
        payload["beats"] = beats
        payload["beat_count"] = len(beats)
        payload["covered_text"] = _short_text(" ".join(beat["text"] for beat in beats if beat.get("text")), 320)
    kind = clean_text(preferred.get("render_kind", ""))
    if kind == "kinetic_type_scene":
        payload["phrases"] = [_short_phrase(script_excerpt)]
    elif kind == "bullet_build_scene":
        payload["points"] = _points_from_text(script_excerpt, max_points=4, max_chars=64)
    elif kind == "recap_sequence_scene":
        payload["recap_items"] = _points_from_text(script_excerpt, max_points=6, max_chars=58)
        payload["final_takeaway"] = payload.get("final_takeaway") or _short_phrase(script_excerpt)
    return payload


def _merge_scene_beats(first: dict[str, Any], second: dict[str, Any], scene_start_seconds: float) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for scene in (first, second):
        payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
        beats = payload.get("beats") if isinstance(payload.get("beats"), list) else []
        for beat in beats:
            if not isinstance(beat, dict):
                continue
            start = _safe_float(beat.get("start_seconds"), _safe_float(scene.get("start_seconds"), scene_start_seconds))
            end = _safe_float(beat.get("end_seconds"), start)
            merged.append(
                {
                    **beat,
                    "start_seconds": round(start, 2),
                    "end_seconds": round(end, 2),
                    "relative_start_seconds": round(max(0.0, start - scene_start_seconds), 2),
                    "relative_end_seconds": round(max(0.0, end - scene_start_seconds), 2),
                }
            )
    return sorted(merged, key=lambda beat: (_safe_float(beat.get("start_seconds"), 0.0), _safe_int(beat.get("unit_order"), 0)))


def _attach_scene_beats(
    *,
    scenes: list[dict[str, Any]],
    voiceover: dict[str, Any] | None,
    warnings: list[str],
) -> list[dict[str, Any]]:
    chunks = _voiceover_chunks(voiceover)
    if not chunks:
        return scenes
    by_order = {_safe_int(chunk.get("order"), index): chunk for index, chunk in enumerate(chunks, start=1)}
    attached_count = 0
    output: list[dict[str, Any]] = []
    for scene in scenes:
        current = dict(scene)
        payload = dict(current.get("payload", {})) if isinstance(current.get("payload"), dict) else {}
        unit_orders = [_safe_int(order, 0) for order in current.get("covered_unit_orders", []) if _safe_int(order, 0)]
        if not unit_orders:
            unit_orders = [
                _safe_int(chunk.get("order"), index)
                for index, chunk in enumerate(chunks, start=1)
                if _chunk_overlaps_scene(chunk, current)
            ]
        scene_start = _safe_float(current.get("start_seconds"), 0.0)
        beats = []
        for order in unit_orders:
            chunk = by_order.get(order)
            if not chunk:
                continue
            start = _safe_float(chunk.get("start_seconds"), scene_start)
            end = _safe_float(chunk.get("end_seconds"), start)
            text = clean_text(chunk.get("text", ""))
            if not text:
                continue
            beats.append(
                {
                    "unit_order": order,
                    "start_seconds": round(start, 2),
                    "end_seconds": round(end, 2),
                    "relative_start_seconds": round(max(0.0, start - scene_start), 2),
                    "relative_end_seconds": round(max(0.0, end - scene_start), 2),
                    "text": text,
                    "visual_action": _visual_action_for_beat(text),
                    "emphasis_words": _meaningful_words(text)[:4],
                }
            )
        if beats:
            payload["beats"] = beats
            payload["beat_count"] = len(beats)
            payload["covered_text"] = _short_text(" ".join(beat["text"] for beat in beats), 320)
            current["payload"] = payload
            current["covered_unit_orders"] = sorted(set(unit_orders))
            attached_count += 1
        output.append(current)
    if attached_count:
        warnings.append(f"Attached voiceover beat timing to {attached_count} visual scene(s).")
    return output


def _chunk_overlaps_scene(chunk: dict[str, Any], scene: dict[str, Any]) -> bool:
    chunk_start = _safe_float(chunk.get("start_seconds"), 0.0)
    chunk_end = _safe_float(chunk.get("end_seconds"), chunk_start)
    scene_start = _safe_float(scene.get("start_seconds"), 0.0)
    scene_end = _safe_float(scene.get("end_seconds"), scene_start)
    return chunk_end > scene_start and chunk_start < scene_end


def _voiceover_chunks(voiceover: dict[str, Any] | None) -> list[dict[str, Any]]:
    package = _voiceover_package(voiceover)
    chunks = package.get("chunks") if isinstance(package.get("chunks"), list) else []
    normalized: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            continue
        text = clean_text(chunk.get("text", ""))
        start = _safe_float(chunk.get("start_seconds"), 0.0)
        end = _safe_float(chunk.get("end_seconds"), start)
        normalized.append(
            {
                "order": _safe_int(chunk.get("order"), index),
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": _safe_float(chunk.get("duration_seconds"), max(0.0, end - start)),
                "text": text,
            }
        )
    return normalized


def _scene_headline(scene: dict[str, Any]) -> str:
    payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
    for key in ("headline", "overlay_headline", "companion_text", "transition_label"):
        value = clean_text(payload.get(key, "")).lower()
        if value:
            return value
    return ""


def _short_text(text: str, max_chars: int) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 1)].rstrip(" ,.;:") + "…"


def _short_phrase(text: str) -> str:
    words = clean_text(text).replace(":", " ").split()
    return " ".join(words[:7]).strip(" ,.;:") or "AI news shift"


def _points_from_text(text: str, *, max_points: int, max_chars: int) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return []
    sentences = [clean_text(item) for item in re.split(r"(?<=[.!?])\s+", normalized) if clean_text(item)]
    points = [_short_text(sentence, max_chars).strip(" ,.;:") for sentence in sentences if len(sentence.split()) >= 3]
    if len(points) < max_points:
        parts = re.split(r"\b(?:and|but|while|because|with|where)\b|[,;:]", normalized)
        points.extend(_short_text(clean_text(part), max_chars).strip(" ,.;:") for part in parts if len(clean_text(part).split()) >= 3)
    return list(dict.fromkeys(point for point in points if point))[:max_points] or [_short_phrase(normalized)]


def _meaningful_words(text: str) -> list[str]:
    stop = {
        "about",
        "after",
        "again",
        "because",
        "before",
        "being",
        "between",
        "could",
        "from",
        "have",
        "into",
        "more",
        "over",
        "that",
        "their",
        "there",
        "they",
        "this",
        "what",
        "when",
        "where",
        "which",
        "with",
        "would",
        "your",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", clean_text(text).lower())
    return [word for word in words if word not in stop][:12]


def _visual_action_for_beat(text: str) -> str:
    lowered = clean_text(text).lower()
    if re.search(r"\$?\d", lowered):
        return "emphasize_metric"
    if re.search(r"\b(api|sdk|workflow|pipeline|agent|model|cloud|deploy|integration|system|service)\b", lowered):
        return "advance_diagram_step"
    if re.search(r"\b(decide|approval|rules|policy|risk|trust|safety|blocked|preview|access)\b", lowered):
        return "highlight_decision_path"
    if re.search(r"\b(signal|watch|trend|pressure|concern|warning|risk)\b", lowered):
        return "scan_signal"
    return "reveal_point"


def _visual_beat_map(scene_timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    beat_map: list[dict[str, Any]] = []
    for scene in scene_timeline:
        payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
        beats = payload.get("beats") if isinstance(payload.get("beats"), list) else []
        for beat in beats:
            if not isinstance(beat, dict):
                continue
            beat_map.append(
                {
                    "scene_id": scene.get("scene_id", ""),
                    "scene_order": scene.get("scene_order"),
                    "story_id": scene.get("story_id", ""),
                    "section_type": scene.get("section_type", ""),
                    "render_kind": scene.get("render_kind", ""),
                    "unit_order": beat.get("unit_order"),
                    "start_seconds": beat.get("start_seconds"),
                    "end_seconds": beat.get("end_seconds"),
                    "relative_start_seconds": beat.get("relative_start_seconds"),
                    "relative_end_seconds": beat.get("relative_end_seconds"),
                    "text": beat.get("text", ""),
                    "visual_action": beat.get("visual_action", ""),
                    "emphasis_words": beat.get("emphasis_words", []),
                }
            )
    return sorted(beat_map, key=lambda item: (_safe_float(item.get("start_seconds"), 0.0), _safe_int(item.get("unit_order"), 0)))


def _generic_placeholder_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flagged: list[dict[str, Any]] = []
    for scene in scenes:
        payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
        text_blob = json.dumps(payload, ensure_ascii=False).lower()
        hits = sorted(phrase for phrase in GENERIC_PLACEHOLDER_PHRASES if phrase in text_blob)
        if hits:
            flagged.append(
                {
                    "scene_id": scene.get("scene_id", ""),
                    "render_kind": scene.get("render_kind", ""),
                    "placeholders": hits[:4],
                }
            )
    return flagged


def _gap_filler_scenes(
    *,
    start: float,
    end: float,
    allowed_render_kinds: set[str],
    index_start: int,
) -> list[dict[str, Any]]:
    if end <= start:
        return []
    render_kind = "transition_stinger_scene" if "transition_stinger_scene" in allowed_render_kinds else "kinetic_type_scene"
    duration = round(end - start, 2)
    if render_kind == "transition_stinger_scene":
        payload = {
            "transition_label": "signal shift",
            "subtitle": "next beat",
            "motion_style": "signal_wipe",
            "background_motif": "abstract_ai",
        }
    else:
        payload = {
            "phrases": ["next beat"],
            "emphasis_words": ["next"],
            "animation_style": "word_snap",
            "background_motif": "abstract_ai",
        }
    return [
        {
            "scene_id": f"scene_gap_{index_start:03d}",
            "scene_order": 0,
            "story_id": "",
            "section_type": "transition",
            "start_seconds": round(start, 2),
            "end_seconds": round(end, 2),
            "duration_seconds": duration,
            "render_kind": render_kind,
            "script_excerpt": "",
            "visual_intent": "Fill a timing gap so rendered visuals remain synchronized with the voiceover.",
            "payload": payload,
            "source_record_keys": [],
            "source_urls": [],
            "covered_unit_orders": [],
        }
    ]


def _scene_duration(scene: dict[str, Any]) -> float:
    start = _safe_float(scene.get("start_seconds"), 0.0)
    end = _safe_float(scene.get("end_seconds"), start)
    return max(0.0, end - start)


def _refresh_scene_duration(scene: dict[str, Any]) -> None:
    start = _safe_float(scene.get("start_seconds"), 0.0)
    end = _safe_float(scene.get("end_seconds"), start)
    scene["start_seconds"] = round(start, 2)
    scene["end_seconds"] = round(end, 2)
    scene["duration_seconds"] = round(max(0.0, end - start), 2)


def _renumber_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(scenes, key=lambda scene: (_safe_float(scene.get("start_seconds"), 0.0), _safe_int(scene.get("scene_order"), 999999)))
    for index, scene in enumerate(ordered, start=1):
        scene["scene_order"] = index
        scene["scene_id"] = f"scene_{index:03d}"
    return ordered


def _extract_url(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    markdown_match = re.search(r"\[[^\]]*\]\((https?://[^)\s]+)\)", text)
    if markdown_match:
        return markdown_match.group(1).strip()
    url_match = re.search(r"https?://[^\s<>\]\)]+", text)
    if url_match:
        return url_match.group(0).strip().rstrip(".,;")
    return text.strip("<>")


def _repair_source_reference(
    scene_id: str,
    story_id: str,
    source_record_key: str,
    source_url: str,
    source_index: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> tuple[str, str]:
    if not source_record_key and source_url:
        inferred_key = _record_key_for_url(source_url, story_id, source_index)
        if inferred_key:
            source_record_key = inferred_key
            warnings.append(f"{scene_id}: filled source_record_key from selected record URL.")

    if source_record_key and source_record_key not in source_index["records_by_key"] and source_url:
        inferred_key = _record_key_for_url(source_url, story_id, source_index)
        if inferred_key:
            warnings.append(f"{scene_id}: corrected unknown source_record_key {source_record_key!r} from selected record URL.")
            source_record_key = inferred_key

    if not source_record_key:
        errors.append(f"{scene_id}: source-backed scenes require payload.source_record_key")
    if source_record_key and source_record_key not in source_index["records_by_key"]:
        errors.append(f"{scene_id}: source_record_key is not in selected story records: {source_record_key}")
        return source_record_key, source_url

    if source_record_key and story_id:
        allowed_keys = source_index["record_keys_by_story"].get(story_id, set())
        if source_record_key not in allowed_keys:
            errors.append(f"{scene_id}: source_record_key {source_record_key} does not belong to story_id {story_id}")

    record_url = clean_text(source_index["records_by_key"].get(source_record_key, {}).get("url", "")) if source_record_key else ""
    if source_record_key and record_url:
        if not source_url:
            source_url = record_url
            warnings.append(f"{scene_id}: filled missing payload.url from selected record {source_record_key}.")
        elif source_url != record_url:
            warnings.append(f"{scene_id}: corrected payload.url to selected record URL for {source_record_key}.")
            source_url = record_url

    if not source_url.startswith(("http://", "https://")):
        errors.append(f"{scene_id}: source-backed scenes require a valid payload.url")
    return source_record_key, source_url


def _record_key_for_url(source_url: str, story_id: str, source_index: dict[str, Any]) -> str:
    normalized_url = clean_text(source_url)
    if not normalized_url:
        return ""
    allowed = source_index["record_keys_by_story"].get(story_id, set()) if story_id else set()
    for key, record in source_index["records_by_key"].items():
        if allowed and key not in allowed:
            continue
        if clean_text(record.get("url", "")) == normalized_url:
            return key
    return ""


def _coverage_report(
    *,
    scenes: list[dict[str, Any]],
    expected_duration: float,
    scene_policy: dict[str, Any],
    require_complete: bool,
    tolerance: float,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    sorted_scenes = sorted(scenes, key=lambda scene: _safe_float(scene.get("start_seconds"), 0.0))
    gap_count = 0
    overlap_count = 0
    gaps: list[dict[str, float]] = []
    overlaps: list[dict[str, float]] = []
    previous_end: float | None = None
    durations = []
    max_scene = _safe_float(scene_policy.get("max_scene_seconds"), 14.0)
    long_scenes = []
    for scene in sorted_scenes:
        start = _safe_float(scene.get("start_seconds"), 0.0)
        end = _safe_float(scene.get("end_seconds"), start)
        duration = max(0.0, end - start)
        durations.append(duration)
        if duration > max_scene + 0.01:
            long_scenes.append({"scene_id": scene.get("scene_id"), "duration_seconds": round(duration, 2)})
        if previous_end is not None:
            if start - previous_end > tolerance:
                gap_count += 1
                gaps.append({"start_seconds": round(previous_end, 2), "end_seconds": round(start, 2)})
            if previous_end - start > tolerance:
                overlap_count += 1
                overlaps.append({"start_seconds": round(start, 2), "end_seconds": round(previous_end, 2)})
        previous_end = max(previous_end or 0.0, end)
    if long_scenes:
        errors.append(f"scene timeline has scenes over max_scene_seconds: {long_scenes[:10]}")
    timeline_start = _safe_float(sorted_scenes[0].get("start_seconds"), 0.0) if sorted_scenes else 0.0
    timeline_end = _safe_float(sorted_scenes[-1].get("end_seconds"), 0.0) if sorted_scenes else 0.0
    if require_complete and expected_duration > 0:
        if abs(timeline_start) > tolerance:
            errors.append(f"scene timeline should start at 0.0 seconds, got {timeline_start:.2f}")
        if expected_duration - timeline_end > tolerance:
            errors.append(f"scene timeline ends too early: {timeline_end:.2f}s vs expected {expected_duration:.2f}s")
        if timeline_end - expected_duration > max(tolerance, max_scene):
            warnings.append(f"scene timeline extends beyond expected duration: {timeline_end:.2f}s vs {expected_duration:.2f}s")
    if gap_count:
        errors.append(f"scene timeline has {gap_count} time gaps")
    if overlap_count:
        errors.append(f"scene timeline has {overlap_count} time overlaps")
    return {
        "total_duration_seconds": round(expected_duration or timeline_end, 2),
        "timeline_start_seconds": round(timeline_start, 2),
        "timeline_end_seconds": round(timeline_end, 2),
        "max_scene_duration_seconds": round(max(durations), 2) if durations else 0.0,
        "max_allowed_scene_seconds": max_scene,
        "long_scenes": long_scenes,
        "gap_count": gap_count,
        "overlap_count": overlap_count,
        "gaps": gaps[:20],
        "overlaps": overlaps[:20],
    }


def _build_asset_manifest(scene_timeline: list[dict[str, Any]]) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    for scene in scene_timeline:
        render_kind = clean_text(scene.get("render_kind", ""))
        asset_type = "none"
        if render_kind in SOURCE_BACKED_RENDER_KINDS:
            asset_type = "source_screenshot"
        elif render_kind in LOGO_RENDER_KINDS:
            asset_type = "logo_asset"
        elif render_kind == "context_image_scene":
            asset_type = "context_image"
        elif render_kind == "broll_video_scene":
            asset_type = "broll_video"
        requests.append(
            {
                "asset_request_id": f"asset_{_safe_int(scene.get('scene_order'), len(requests) + 1):03d}",
                "scene_id": scene.get("scene_id", ""),
                "render_kind": render_kind,
                "asset_type": asset_type,
                "required": asset_type in {"source_screenshot", "logo_asset", "context_image", "broll_video"},
                "payload": scene.get("payload", {}),
            }
        )
    return {
        "asset_request_count": len(requests),
        "asset_type_counts": dict(Counter(request["asset_type"] for request in requests)),
        "requests": requests,
    }


def _build_source_index(video_packet: dict[str, Any]) -> dict[str, Any]:
    stories = video_packet.get("stories")
    if not isinstance(stories, list):
        stories = video_packet.get("selected_stories")
    records_by_key: dict[str, dict[str, Any]] = {}
    record_keys_by_story: dict[str, set[str]] = {}
    source_urls: set[str] = set()
    story_ids: set[str] = set()
    for story in stories if isinstance(stories, list) else []:
        if not isinstance(story, dict):
            continue
        story_id = clean_text(story.get("story_id", ""))
        if story_id:
            story_ids.add(story_id)
        record_keys_by_story.setdefault(story_id, set())
        records = story.get("records") if isinstance(story.get("records"), list) else []
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            record_key = clean_text(record.get("record_key") or record.get("source_record_key") or record.get("id") or f"{story_id}_record_{index}")
            if not record_key:
                continue
            records_by_key[record_key] = record
            record_keys_by_story.setdefault(story_id, set()).add(record_key)
            url = clean_text(record.get("url", ""))
            if url:
                source_urls.add(url)
    return {
        "records_by_key": records_by_key,
        "record_keys_by_story": record_keys_by_story,
        "source_urls": source_urls,
        "story_ids": story_ids,
    }


def _expected_duration_seconds(voiceover: dict[str, Any] | None, script_text: str) -> float:
    audio = _audio_timeline(voiceover, 0.0)
    duration = _safe_float(audio.get("duration_seconds"), 0.0)
    if duration > 0:
        return duration
    words = len(script_text.split())
    return round(words / 150 * 60, 2) if words else 0.0


def _audio_timeline(voiceover: dict[str, Any] | None, expected_duration: float) -> dict[str, Any]:
    package = _voiceover_package(voiceover)
    audio = package.get("audio") if isinstance(package.get("audio"), dict) else {}
    chunks = package.get("chunks") if isinstance(package.get("chunks"), list) else []
    duration = _safe_float(audio.get("duration_seconds") or package.get("duration_seconds") or expected_duration, 0.0)
    return {
        "duration_seconds": round(duration, 2),
        "chunk_count": len(chunks),
        "audio_path": clean_text(audio.get("full_audio_path") or audio.get("path") or audio.get("audio_path") or package.get("audio_path", "")),
    }


def _voiceover_package(voiceover: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(voiceover, dict):
        return {}
    if isinstance(voiceover.get("data"), dict) and isinstance(voiceover["data"].get("voiceover_package"), dict):
        return voiceover["data"]["voiceover_package"]
    if isinstance(voiceover.get("voiceover_package"), dict):
        return voiceover["voiceover_package"]
    return voiceover


def _build_summary(
    *,
    visual_scene_plan: dict[str, Any],
    status: str,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    scenes = visual_scene_plan.get("scene_timeline", [])
    kinds = [clean_text(scene.get("render_kind", "")) for scene in scenes if isinstance(scene, dict)]
    return {
        "status": status,
        "scene_count": len(scenes),
        "visual_beat_count": len(visual_scene_plan.get("visual_beat_map", [])),
        "render_kind_counts": dict(Counter(kinds)),
        "source_backed_scene_count": kinds.count("source_article_scene") + kinds.count("quote_or_claim_highlight_scene"),
        "logo_reveal_scene_count": kinds.count("logo_reveal_scene"),
        "context_image_scene_count": kinds.count("context_image_scene"),
        "broll_video_scene_count": kinds.count("broll_video_scene"),
        "transition_stinger_scene_count": kinds.count("transition_stinger_scene"),
        "asset_request_count": visual_scene_plan.get("asset_manifest", {}).get("asset_request_count", 0),
        "coverage": visual_scene_plan.get("coverage", {}),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "failure_reason": "; ".join(errors[:5]),
    }


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default
