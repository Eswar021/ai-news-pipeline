from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any

from src.pipeline.contracts import (
    build_artifact_provenance,
    require_matching_run_id,
    require_parent_fingerprint,
    validate_artifact_provenance,
    validate_script_provenance,
    visual_plan_artifact_payload,
    voiceover_artifact_payload,
)
from src.pipeline.handoffs.common import clean_text, iso_now
from src.pipeline.visuals.asset_catalog.identity import catalog_identity_payload
from src.pipeline.visuals.payload_validation import (
    validate_scene_payload,
)
from src.pipeline.visuals.recipes import ACTIVE_RENDER_KINDS

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
DEFAULT_RENDER_KINDS = set(ACTIVE_RENDER_KINDS)
SOURCE_BACKED_RENDER_KINDS = {"source_article_scene", "quote_or_claim_highlight_scene", "browser_walkthrough_scene"}
EVIDENCE_BOUND_RENDER_KINDS = {
    "simple_explainer_scene",
    "document_stack_scene",
    "interface_transform_scene",
}
LOGO_RENDER_KINDS = {"logo_reveal_scene"}
MEDIA_RENDER_KINDS = {"context_image_scene", "broll_video_scene"}
GRAPHIC_RENDER_KINDS = DEFAULT_RENDER_KINDS - SOURCE_BACKED_RENDER_KINDS


def run(input_json: dict) -> dict:
    request = ChatGPTVisualPlanParserRequest.model_validate(input_json)
    generated_at = iso_now()
    run_id = request.run.run_id
    video_packet = request.input.video_packaging.data.video_packet
    selected_format = clean_text(request.input.video_packaging.data.selected_format or video_packet.get("selected_format", ""))
    script_result = request.input.script_generation
    script_data = script_result.get("data") or {}
    script_package = script_data.get("script_package") or {}
    script_text = clean_text(script_package.get("full_script"))
    require_matching_run_id(run_id, request.input.video_packaging.data.run_id, "video_packaging")
    require_matching_run_id(run_id, script_data.get("run_id"), "script_generation")
    script_provenance = validate_script_provenance(
        script_package,
        run_id=run_id,
        upstream_run_id=script_data.get("run_id"),
    )
    asset_catalog_result = request.input.asset_catalog or {}
    asset_catalog_data = asset_catalog_result.get("data") or {}
    asset_catalog = asset_catalog_data.get("visual_asset_catalog") or {}
    asset_catalog_provenance = None
    if asset_catalog:
        require_matching_run_id(run_id, asset_catalog_data.get("run_id"), "asset_catalog")
        require_matching_run_id(run_id, asset_catalog.get("run_id"), "visual_asset_catalog")
        asset_catalog_provenance = validate_artifact_provenance(
            asset_catalog.get("provenance"),
            artifact_type="visual_asset_catalog",
            run_id=run_id,
            payload=catalog_identity_payload(asset_catalog),
            label="visual_asset_catalog",
        )
        require_parent_fingerprint(
            asset_catalog_provenance,
            parent_name="script",
            expected=script_provenance["script_fingerprint"],
            label="visual_asset_catalog",
        )
    asset_catalog_index = _asset_catalog_index(asset_catalog)
    voiceover_package = _voiceover_package(request.input.voiceover)
    voiceover_provenance = _validate_voiceover_for_script(
        voiceover_package,
        run_id=run_id,
        script_provenance=script_provenance,
        script_package=script_package,
    )

    errors: list[str] = []
    warnings: list[str] = []
    substantial_repairs: list[dict[str, Any]] = []
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

    source_index = _build_source_index(video_packet, script_package)
    allowed_render_kinds = _allowed_render_kinds(request.config.scene_policy, request.config.visual_capabilities)
    scene_timeline = _normalize_scenes(
        scenes=scenes_raw,
        allowed_render_kinds=allowed_render_kinds,
        source_index=source_index,
        asset_catalog_index=asset_catalog_index,
        errors=errors,
        warnings=warnings,
    )
    scene_timeline = _retime_scenes_from_aligned_units(
        scenes=scene_timeline,
        voiceover=request.input.voiceover,
        warnings=warnings,
        errors=errors,
    )
    scene_timeline = _insert_story_title_interstitials(
        scenes=scene_timeline,
        video_packet=video_packet,
        voiceover=request.input.voiceover,
        allowed_render_kinds=allowed_render_kinds,
        errors=errors,
        warnings=warnings,
    )
    scene_timeline = _split_overlong_scenes(
        scenes=scene_timeline,
        voiceover=request.input.voiceover,
        scene_policy=request.config.scene_policy,
        warnings=warnings,
    )
    scene_timeline = _reconcile_scene_sections(
        scene_timeline,
        story_sections,
        warnings,
        substantial_repairs,
    )
    expected_duration = _expected_duration_seconds(request.input.voiceover, script_text)
    scene_timeline = _close_timeline_gaps(
        scenes=scene_timeline,
        expected_duration=expected_duration,
        scene_policy=request.config.scene_policy,
        allowed_render_kinds=allowed_render_kinds,
        warnings=warnings,
        substantial_repairs=substantial_repairs,
        max_automatic_repair_seconds=request.config.max_automatic_timing_repair_seconds,
    )
    scene_timeline = _attach_scene_beats(
        scenes=scene_timeline,
        voiceover=request.input.voiceover,
        warnings=warnings,
    )
    _validate_story_title_interstitials(scene_timeline, video_packet, errors)
    coverage = _coverage_report(
        scenes=scene_timeline,
        expected_duration=expected_duration,
        scene_policy=request.config.scene_policy,
        require_complete=request.config.require_complete_timeline,
        tolerance=request.config.gap_tolerance_seconds,
        errors=errors,
        warnings=warnings,
    )
    if request.config.require_real_anchor_per_story:
        _validate_catalog_story_anchors(
            scene_timeline,
            asset_catalog_index=asset_catalog_index,
            selected_story_ids=source_index["story_ids"],
            errors=errors,
        )
    visual_scene_plan = {
        "package_type": PACKAGE_TYPE,
        "selected_format": SUPPORTED_FORMAT,
        "planning_strategy": "chatgpt_visual_scene_plan_handoff",
        "run_id": run_id,
        "generated_at": generated_at,
        "episode_style": {
            **(parsed.get("episode_style", {}) if isinstance(parsed.get("episode_style"), dict) else {}),
            **request.config.style,
        },
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
            "word_count": len(script_text.split()),
            "script_fingerprint": script_provenance["script_fingerprint"],
        },
        "audio_timeline": _audio_timeline(request.input.voiceover, expected_duration),
        "scene_policy": request.config.scene_policy,
        "visual_capabilities": request.config.visual_capabilities,
        "asset_catalog": asset_catalog,
        "source_context": {
            "selected_story_ids": sorted(source_index["story_ids"]),
            "source_url_count": len(source_index["source_urls"]),
            "source_urls": sorted(source_index["source_urls"]),
        },
        "planner_warnings": warnings,
        "repair_status": "needs_repair" if substantial_repairs else "clean",
        "substantial_repairs": substantial_repairs,
    }
    parents = {"script": script_provenance["script_fingerprint"]}
    if voiceover_provenance:
        parents["voiceover"] = voiceover_provenance["voiceover_fingerprint"]
    if asset_catalog_provenance:
        parents["asset_catalog"] = asset_catalog_provenance["artifact_fingerprint"]
    visual_scene_plan["provenance"] = build_artifact_provenance(
        artifact_type="visual_plan",
        run_id=run_id,
        parents=parents,
        script_source=script_provenance.get("script_source", ""),
        payload=visual_plan_artifact_payload(visual_scene_plan),
    )
    checks = {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "requires_repair": bool(substantial_repairs),
        "substantial_repairs": substantial_repairs,
    }
    visual_scene_plan["checks"] = checks
    status = "failed" if errors else ("needs_repair" if substantial_repairs else "ok")
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
    asset_catalog_index: dict[str, Any],
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
        catalog_asset = _catalog_asset_for_payload(
            scene_id=scene_id,
            story_id=clean_text(scene_obj.get("story_id", "")),
            render_kind=render_kind,
            payload=payload,
            asset_catalog_index=asset_catalog_index,
            errors=errors,
        )
        if catalog_asset:
            _apply_catalog_asset(payload, catalog_asset)
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
        if render_kind in MEDIA_RENDER_KINDS and not clean_text(payload.get("asset_id")):
            search_queries = payload.get("search_queries") if isinstance(payload.get("search_queries"), list) else []
            if not any(clean_text(query) for query in search_queries):
                errors.append(f"{scene_id}: {render_kind} requires payload.search_queries")
        evidence_keys = [
            clean_text(key)
            for key in scene_obj.get("evidence_record_keys", [])
            if clean_text(key)
        ] if isinstance(scene_obj.get("evidence_record_keys"), list) else []
        if source_record_key:
            evidence_keys.append(source_record_key)
        evidence_keys = list(dict.fromkeys(evidence_keys))
        evidence_truth_ids = [
            clean_text(truth_id)
            for truth_id in scene_obj.get("evidence_truth_ids", [])
            if clean_text(truth_id)
        ] if isinstance(scene_obj.get("evidence_truth_ids"), list) else []
        evidence_truth_ids = list(dict.fromkeys(evidence_truth_ids))
        allowed_story_keys = source_index["record_keys_by_story"].get(story_id, set())
        invalid_evidence_keys = [key for key in evidence_keys if key not in allowed_story_keys]
        truth_items_by_id = source_index["truth_items_by_id"]
        valid_truth_items = [
            truth_items_by_id[truth_id]
            for truth_id in evidence_truth_ids
            if truth_id in truth_items_by_id
            and clean_text(truth_items_by_id[truth_id].get("story_id")) == story_id
        ]
        invalid_truth_ids = [
            truth_id
            for truth_id in evidence_truth_ids
            if truth_id not in truth_items_by_id
            or clean_text(truth_items_by_id[truth_id].get("story_id")) != story_id
        ]
        evidence_text = clean_text(scene_obj.get("evidence_text", ""))
        grounding_basis = clean_text(scene_obj.get("grounding_basis", "")) or "script_beat"
        grounding_errors: list[str] = []
        if invalid_evidence_keys:
            grounding_errors.append(f"evidence_record_keys are not owned by story_id {story_id}: {invalid_evidence_keys}")
        if invalid_truth_ids:
            grounding_errors.append(f"evidence_truth_ids are not owned by story_id {story_id}: {invalid_truth_ids}")
        if render_kind in EVIDENCE_BOUND_RENDER_KINDS:
            if not evidence_keys and grounding_basis != "script_beat":
                grounding_errors.append(
                    "semantic graphic requires evidence_record_keys or grounding_basis='script_beat'"
                )
            if not evidence_text:
                grounding_errors.append("semantic graphic requires evidence_text")
        grounding_errors.extend(_payload_grounding_errors(render_kind, payload))
        for grounding_error in grounding_errors:
            errors.append(f"{scene_id}: {grounding_error}")
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
                "evidence_truth_ids": [clean_text(item.get("truth_id")) for item in valid_truth_items],
                "source_urls": [source_url] if source_url else [],
                "semantic_grounding": {
                    "status": "grounded" if not grounding_errors else "invalid",
                    "basis": grounding_basis,
                    "evidence_record_keys": evidence_keys,
                    "evidence_truth_ids": [clean_text(item.get("truth_id")) for item in valid_truth_items],
                    "evidence_text": evidence_text,
                    "errors": grounding_errors,
                },
                "covered_unit_orders": scene_obj.get("covered_unit_orders", []) if isinstance(scene_obj.get("covered_unit_orders"), list) else [],
            }
        )
        previous_end = end
    return sorted(normalized, key=lambda scene: (_safe_float(scene.get("start_seconds"), 0), _safe_int(scene.get("scene_order"), 999999)))


def _payload_grounding_errors(render_kind: str, payload: dict[str, Any]) -> list[str]:
    return validate_scene_payload(render_kind, payload)


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


def _reconcile_scene_sections(
    scenes: list[dict[str, Any]],
    story_sections: list[dict[str, Any]],
    warnings: list[str],
    substantial_repairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
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
        substantial_repairs.append(
            {
                "repair_type": "section_story_reconciliation",
                "scene_count": changed,
                "reason": "The submitted scene ownership disagreed with its submitted story-section timing.",
            }
        )
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
    substantial_repairs: list[dict[str, Any]],
    max_automatic_repair_seconds: float,
) -> list[dict[str, Any]]:
    if not scenes:
        return []
    max_scene_seconds = _safe_float(scene_policy.get("max_scene_seconds"), 14.0)
    sorted_scenes = [dict(scene) for scene in sorted(scenes, key=lambda item: (_safe_float(item.get("start_seconds"), 0.0), _safe_int(item.get("scene_order"), 999999)))]
    adjusted_gap_count = 0
    unresolved_gap_count = 0
    substantial_gap_sizes: list[float] = []
    output: list[dict[str, Any]] = []

    first = sorted_scenes[0]
    first_start = _safe_float(first.get("start_seconds"), 0.0)
    if first_start > 0.01:
        if _scene_duration(first) + first_start <= max_scene_seconds + 0.01:
            first["start_seconds"] = 0.0
            _refresh_scene_duration(first)
            adjusted_gap_count += 1
            if first_start > max_automatic_repair_seconds:
                substantial_gap_sizes.append(first_start)
        else:
            unresolved_gap_count += 1

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
                    if gap > max_automatic_repair_seconds:
                        substantial_gap_sizes.append(gap)
                elif _scene_duration(scene) + gap <= max_scene_seconds + 0.01:
                    scene["start_seconds"] = round(prev_end, 2)
                    _refresh_scene_duration(scene)
                    adjusted_gap_count += 1
                    if gap > max_automatic_repair_seconds:
                        substantial_gap_sizes.append(gap)
                else:
                    unresolved_gap_count += 1
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
                if gap > max_automatic_repair_seconds:
                    substantial_gap_sizes.append(gap)
            else:
                unresolved_gap_count += 1

    if adjusted_gap_count:
        warnings.append(f"Closed {adjusted_gap_count} visual timeline gap(s) by extending adjacent scenes.")
    if substantial_gap_sizes:
        substantial_repairs.append(
            {
                "repair_type": "semantic_timeline_extension",
                "gap_count": len(substantial_gap_sizes),
                "max_gap_seconds": round(max(substantial_gap_sizes), 2),
                "automatic_limit_seconds": round(max_automatic_repair_seconds, 2),
                "reason": "One or more scenes were stretched beyond the safe timing-normalization limit.",
            }
        )
    if unresolved_gap_count:
        warnings.append(
            f"Left {unresolved_gap_count} large visual timeline gap(s) unresolved rather than inventing filler content."
        )
    return _renumber_scenes(output)


def _insert_story_title_interstitials(
    *,
    scenes: list[dict[str, Any]],
    video_packet: dict[str, Any],
    voiceover: dict[str, Any] | None,
    allowed_render_kinds: set[str],
    errors: list[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    if "story_transition_scene" not in allowed_render_kinds:
        errors.append("story_transition_scene must be allowed for deterministic roundup story titles")
        return scenes
    title_render_kind = "story_transition_scene"
    chunks = _voiceover_chunks(voiceover)
    first_beat_by_story: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        story_id = clean_text(chunk.get("story_id", ""))
        if story_id and story_id not in first_beat_by_story:
            first_beat_by_story[story_id] = chunk

    output = [dict(scene) for scene in scenes]
    inserted = 0
    ordered_stories = sorted(
        (story for story in video_packet.get("stories", []) if isinstance(story, dict)),
        key=lambda story: _safe_int((story.get("video_segment") or {}).get("segment_order"), 999999),
    )
    for story in ordered_stories:
        story_id = clean_text(story.get("story_id", ""))
        beat = first_beat_by_story.get(story_id)
        if beat is None:
            errors.append(f"{story_id}: no aligned voiceover beat exists for deterministic story title")
            continue
        start = _safe_float(beat.get("start_seconds"), 0.0)
        speech_end = _safe_float(beat.get("end_seconds"), start)
        end = min(speech_end, start + 3.2)
        if end - start < 1.0:
            end = min(speech_end, start + 1.0)
        if end <= start:
            errors.append(f"{story_id}: first aligned beat has invalid timing for story title")
            continue

        trimmed: list[dict[str, Any]] = []
        for scene in output:
            scene_start = _safe_float(scene.get("start_seconds"), 0.0)
            scene_end = _safe_float(scene.get("end_seconds"), scene_start)
            if scene_end <= start + 0.01 or scene_start >= end - 0.01:
                trimmed.append(scene)
                continue
            if scene_start < start - 0.01:
                before = dict(scene)
                before["end_seconds"] = round(start, 2)
                _refresh_scene_duration(before)
                trimmed.append(before)
            if scene_end > end + 0.01:
                after = dict(scene)
                after["start_seconds"] = round(end, 2)
                _refresh_scene_duration(after)
                trimmed.append(after)
        output = trimmed

        identity = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
        segment = story.get("video_segment") if isinstance(story.get("video_segment"), dict) else {}
        story_number = _safe_int(segment.get("segment_order"), inserted + 1)
        if title_render_kind == "story_transition_scene":
            title_payload = {
                "story_number": str(story_number),
                "eyebrow": f"STORY {story_number}",
                "headline": _short_text(story.get("story_title") or story.get("title"), 140),
                "subtitle": _short_text(identity.get("why_it_matters", ""), 110),
                "accent_words": [],
                "motion_style": "editorial_wipe",
                "voice_behavior": "continue",
            }
        else:
            title_payload = {
                "transition_label": _short_text(story.get("story_title") or story.get("title"), 90),
                "subtitle": _short_text(identity.get("why_it_matters", ""), 110),
                "background_motif": "newsroom_grid",
                "motion_style": "signal_wipe",
                "eyebrow": f"STORY {story_number}",
                "voice_behavior": "continue",
            }
        output.append(
            {
                "scene_id": "",
                "scene_order": 0,
                "story_id": story_id,
                "section_type": "story",
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "duration_seconds": round(end - start, 2),
                "render_kind": title_render_kind,
                "script_excerpt": clean_text(beat.get("text", "")),
                "visual_intent": "Introduce the story while narration continues.",
                "payload": title_payload,
                "source_record_keys": [],
                "source_urls": [],
                "semantic_grounding": {
                    "status": "grounded",
                    "basis": "editorial_transition",
                    "evidence_record_keys": [],
                    "evidence_text": clean_text(beat.get("text", "")),
                    "errors": [],
                },
                "covered_unit_orders": [_safe_int(beat.get("order"), 0)],
            }
        )
        inserted += 1
    if inserted:
        warnings.append(f"Inserted {inserted} deterministic moving story-title interstitial(s).")
    return _renumber_scenes(output)


def _retime_scenes_from_aligned_units(
    *,
    scenes: list[dict[str, Any]],
    voiceover: dict[str, Any] | None,
    warnings: list[str],
    errors: list[str],
) -> list[dict[str, Any]]:
    chunks = _voiceover_chunks(voiceover)
    if not chunks:
        return scenes
    by_order = {_safe_int(chunk.get("order"), index): chunk for index, chunk in enumerate(chunks, start=1)}
    retimed = 0
    output: list[dict[str, Any]] = []
    for scene in scenes:
        current = dict(scene)
        orders = sorted({_safe_int(value, 0) for value in current.get("covered_unit_orders", []) if _safe_int(value, 0)})
        if not orders:
            output.append(current)
            continue
        unknown = [order for order in orders if order not in by_order]
        if unknown:
            errors.append(f"{current.get('scene_id')}: covered_unit_orders contains unknown aligned units: {unknown}")
            output.append(current)
            continue
        current["start_seconds"] = round(_safe_float(by_order[orders[0]].get("start_seconds"), 0.0), 2)
        current["end_seconds"] = round(_safe_float(by_order[orders[-1]].get("end_seconds"), current["start_seconds"]), 2)
        _refresh_scene_duration(current)
        output.append(current)
        retimed += 1
    if retimed:
        warnings.append(f"Retimed {retimed} ChatGPT scene(s) from authoritative aligned unit orders.")
    return _renumber_scenes(output)


def _split_overlong_scenes(
    *,
    scenes: list[dict[str, Any]],
    voiceover: dict[str, Any] | None,
    scene_policy: dict[str, Any],
    warnings: list[str],
) -> list[dict[str, Any]]:
    max_seconds = max(1.0, _safe_float(scene_policy.get("max_scene_seconds"), 14.0))
    chunks = _voiceover_chunks(voiceover)
    output: list[dict[str, Any]] = []
    split_count = 0
    for scene in scenes:
        start = _safe_float(scene.get("start_seconds"), 0.0)
        end = _safe_float(scene.get("end_seconds"), start)
        duration = max(0.0, end - start)
        if duration <= max_seconds + 0.01:
            output.append(scene)
            continue
        slice_count = max(2, int((duration + max_seconds - 0.0001) // max_seconds))
        balanced = duration / slice_count
        for slice_index in range(slice_count):
            slice_start = start + slice_index * balanced
            slice_end = end if slice_index == slice_count - 1 else start + (slice_index + 1) * balanced
            current = dict(scene)
            current["payload"] = dict(scene.get("payload", {})) if isinstance(scene.get("payload"), dict) else {}
            current["start_seconds"] = round(slice_start, 2)
            current["end_seconds"] = round(slice_end, 2)
            _refresh_scene_duration(current)
            overlapping_orders = [
                _safe_int(chunk.get("order"), index)
                for index, chunk in enumerate(chunks, start=1)
                if _safe_float(chunk.get("end_seconds"), 0.0) > slice_start + 0.01
                and _safe_float(chunk.get("start_seconds"), 0.0) < slice_end - 0.01
            ]
            if overlapping_orders:
                current["covered_unit_orders"] = sorted(set(overlapping_orders))
            output.append(current)
        split_count += 1
    if split_count:
        warnings.append(f"Split {split_count} overlong ChatGPT scene(s) into balanced render-safe slices.")
    return _renumber_scenes(output)


def _validate_story_title_interstitials(
    scenes: list[dict[str, Any]],
    video_packet: dict[str, Any],
    errors: list[str],
) -> None:
    for story in video_packet.get("stories", []):
        if not isinstance(story, dict):
            continue
        story_id = clean_text(story.get("story_id", ""))
        story_scenes = [scene for scene in scenes if clean_text(scene.get("story_id", "")) == story_id]
        title_scenes = [scene for scene in story_scenes if _is_story_title_interstitial(scene)]
        if len(title_scenes) != 1:
            errors.append(f"{story_id}: expected exactly one deterministic story title, found {len(title_scenes)}")
        elif story_scenes and title_scenes[0].get("scene_id") != story_scenes[0].get("scene_id"):
            errors.append(f"{story_id}: deterministic story title is not the first scene in its story")


def _is_story_title_interstitial(scene: dict[str, Any]) -> bool:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    return (
        clean_text(scene.get("render_kind", "")) == "story_transition_scene"
        and clean_text(payload.get("voice_behavior", "")) == "continue"
    )




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
        authored_beats = {
            _safe_int(beat.get("unit_order"), 0): beat
            for beat in payload.get("beats", [])
            if isinstance(beat, dict) and _safe_int(beat.get("unit_order"), 0)
        }
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
            authored = authored_beats.get(order, {})
            beats.append(
                {
                    "unit_order": order,
                    "beat_id": chunk.get("beat_id", ""),
                    "beat_type": chunk.get("beat_type", ""),
                    "start_seconds": round(start, 2),
                    "end_seconds": round(end, 2),
                    "relative_start_seconds": round(max(0.0, start - scene_start), 2),
                    "relative_end_seconds": round(max(0.0, end - scene_start), 2),
                    "text": text,
                    "visual_action": clean_text(authored.get("visual_action", "")) or "hold_scene",
                    "emphasis_words": list(
                        dict.fromkeys(
                            clean_text(value)
                            for value in authored.get("emphasis_words", [])
                            if clean_text(value)
                        )
                    )[:4],
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
    audio_units = package.get("audio_units") if isinstance(package.get("audio_units"), list) else []
    if audio_units:
        normalized_beats: list[dict[str, Any]] = []
        order = 0
        for unit in sorted(
            (item for item in audio_units if isinstance(item, dict)),
            key=lambda item: _safe_int(item.get("unit_order"), 999999),
        ):
            beats = unit.get("aligned_beats") if isinstance(unit.get("aligned_beats"), list) else []
            for beat in sorted(
                (item for item in beats if isinstance(item, dict)),
                key=lambda item: _safe_int(item.get("beat_order"), 999999),
            ):
                order += 1
                start = _safe_float(beat.get("start_seconds"), 0.0)
                end = _safe_float(beat.get("end_seconds"), start)
                normalized_beats.append(
                    {
                        "order": order,
                        "start_seconds": start,
                        "end_seconds": end,
                        "duration_seconds": max(0.0, end - start),
                        "text": clean_text(beat.get("text", "")),
                        "beat_id": clean_text(beat.get("beat_id", "")),
                        "beat_type": clean_text(beat.get("beat_type", "")),
                        "section_id": clean_text(beat.get("section_id") or unit.get("section_id")),
                        "story_id": clean_text(beat.get("story_id") or unit.get("story_id")),
                    }
                )
        if normalized_beats:
            return normalized_beats
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


def _asset_catalog_index(catalog: dict[str, Any]) -> dict[str, Any]:
    assets = {
        clean_text(asset.get("asset_id")): asset
        for asset in catalog.get("assets", [])
        if isinstance(asset, dict) and clean_text(asset.get("asset_id"))
    }
    by_story: dict[str, list[dict[str, Any]]] = {}
    for asset in assets.values():
        by_story.setdefault(clean_text(asset.get("story_id")), []).append(asset)
    return {"assets_by_id": assets, "assets_by_story": by_story}


def _catalog_asset_for_payload(
    *,
    scene_id: str,
    story_id: str,
    render_kind: str,
    payload: dict[str, Any],
    asset_catalog_index: dict[str, Any],
    errors: list[str],
) -> dict[str, Any] | None:
    asset_id = clean_text(payload.get("asset_id"))
    if not asset_id:
        return None
    asset = asset_catalog_index["assets_by_id"].get(asset_id)
    if not isinstance(asset, dict):
        errors.append(f"{scene_id}: unknown catalog asset_id {asset_id!r}")
        return None
    compatibility = {
        "source_article_scene": {"source_page"},
        "quote_or_claim_highlight_scene": {"source_page"},
        "browser_walkthrough_scene": {"source_page"},
        "context_image_scene": {"source_image", "official_product_interface", "source_figure"},
        "broll_video_scene": {"broll_video"},
        "logo_reveal_scene": {"logo"},
    }
    asset_type = clean_text(asset.get("asset_type"))
    scene_errors: list[str] = []
    if clean_text(asset.get("story_id")) != story_id:
        scene_errors.append("catalog asset belongs to another story")
    if clean_text(asset.get("status")) != "available":
        scene_errors.append("catalog asset is not available")
    if asset_type not in compatibility.get(render_kind, set()):
        scene_errors.append(f"catalog asset type {asset_type!r} is incompatible with {render_kind}")
    errors.extend(f"{scene_id}: {message}" for message in scene_errors)
    return asset if not scene_errors else None


def _apply_catalog_asset(payload: dict[str, Any], asset: dict[str, Any]) -> None:
    payload["asset_id"] = clean_text(asset.get("asset_id"))
    if clean_text(asset.get("asset_type")) == "source_page":
        payload["source_record_key"] = clean_text(asset.get("source_record_key"))
        payload["url"] = clean_text(asset.get("source_url") or asset.get("asset_url"))
    elif clean_text(asset.get("asset_type")) == "logo":
        payload["primary_entity"] = clean_text(asset.get("title"))


def _validate_catalog_story_anchors(
    scenes: list[dict[str, Any]],
    *,
    asset_catalog_index: dict[str, Any],
    selected_story_ids: set[str],
    errors: list[str],
) -> None:
    anchored = {
        clean_text(scene.get("story_id"))
        for scene in scenes
        if clean_text((scene.get("payload") or {}).get("asset_id"))
    }
    for story_id in sorted(selected_story_ids):
        available = asset_catalog_index["assets_by_story"].get(story_id, [])
        if available and story_id not in anchored:
            errors.append(f"{story_id}: visual plan must use at least one verified catalog asset_id")


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
                    "beat_id": beat.get("beat_id", ""),
                    "beat_type": beat.get("beat_type", ""),
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
        if timeline_end - expected_duration > tolerance:
            errors.append(f"scene timeline ends too late: {timeline_end:.2f}s vs expected {expected_duration:.2f}s")
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


def _build_source_index(
    video_packet: dict[str, Any],
    script_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stories = video_packet.get("stories")
    if not isinstance(stories, list):
        stories = video_packet.get("selected_stories")
    records_by_key: dict[str, dict[str, Any]] = {}
    record_keys_by_story: dict[str, set[str]] = {}
    source_urls: set[str] = set()
    story_ids: set[str] = set()
    truth_items_by_id: dict[str, dict[str, Any]] = {}
    for index in (script_package or {}).get("story_truth_indexes", []):
        if not isinstance(index, dict):
            continue
        indexed_story_id = clean_text(index.get("story_id"))
        for item in index.get("items", []):
            if not isinstance(item, dict):
                continue
            truth_id = clean_text(item.get("truth_id"))
            if truth_id and indexed_story_id:
                truth_items_by_id[truth_id] = {**item, "story_id": indexed_story_id}
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
        "truth_items_by_id": truth_items_by_id,
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


def _validate_voiceover_for_script(
    voiceover_package: dict[str, Any],
    *,
    run_id: str,
    script_provenance: dict[str, Any],
    script_package: dict[str, Any],
) -> dict[str, Any] | None:
    if not voiceover_package:
        return None
    require_matching_run_id(run_id, voiceover_package.get("run_id"), "voiceover")
    provenance = voiceover_package.get("provenance")
    validate_artifact_provenance(
        provenance,
        artifact_type="voiceover",
        run_id=run_id,
        payload=voiceover_artifact_payload(voiceover_package),
        label="voiceover",
    )
    require_parent_fingerprint(
        provenance,
        parent_name="script",
        expected=script_provenance["script_fingerprint"],
        label="voiceover",
    )
    if not clean_text((provenance or {}).get("voiceover_fingerprint")):
        raise ValueError("voiceover.provenance.voiceover_fingerprint is required")
    expected_beats = {
        clean_text(beat.get("beat_id")): clean_text(beat.get("narration_text"))
        for section in script_package.get("sections", [])
        if isinstance(section, dict)
        for beat in section.get("beats", [])
        if isinstance(beat, dict) and clean_text(beat.get("beat_id"))
    }
    actual_beats = {
        clean_text(beat.get("beat_id")): clean_text(beat.get("text"))
        for unit in voiceover_package.get("audio_units", [])
        if isinstance(unit, dict)
        for beat in unit.get("aligned_beats", [])
        if isinstance(beat, dict) and clean_text(beat.get("beat_id"))
    }
    if expected_beats and actual_beats != expected_beats:
        changed = sorted(
            beat_id
            for beat_id in set(expected_beats) | set(actual_beats)
            if expected_beats.get(beat_id) != actual_beats.get(beat_id)
        )
        raise ValueError(f"voiceover aligned beats do not match the selected script: {changed[:8]}")
    return provenance


def _build_summary(
    *,
    visual_scene_plan: dict[str, Any],
    status: str,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    scenes = visual_scene_plan.get("scene_timeline", [])
    kinds = [clean_text(scene.get("render_kind", "")) for scene in scenes if isinstance(scene, dict)]
    substantial_repairs = visual_scene_plan.get("substantial_repairs", [])
    failure_reason = "; ".join(errors[:5])
    if not failure_reason and substantial_repairs:
        repair_types = [clean_text(item.get("repair_type", "")) for item in substantial_repairs if isinstance(item, dict)]
        failure_reason = (
            "Manual visual plan needs targeted repair before production: "
            + ", ".join(repair_type for repair_type in repair_types if repair_type)
        )
    return {
        "status": status,
        "scene_count": len(scenes),
        "visual_beat_count": len(visual_scene_plan.get("visual_beat_map", [])),
        "render_kind_counts": dict(Counter(kinds)),
        "source_backed_scene_count": kinds.count("source_article_scene") + kinds.count("quote_or_claim_highlight_scene"),
        "logo_reveal_scene_count": kinds.count("logo_reveal_scene"),
        "editorial_text_scene_count": kinds.count("editorial_text_scene"),
        "simple_explainer_scene_count": kinds.count("simple_explainer_scene"),
        "story_transition_scene_count": kinds.count("story_transition_scene"),
        "context_image_scene_count": kinds.count("context_image_scene"),
        "broll_video_scene_count": kinds.count("broll_video_scene"),
        "asset_request_count": visual_scene_plan.get("asset_manifest", {}).get("asset_request_count", 0),
        "coverage": visual_scene_plan.get("coverage", {}),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "repair_status": visual_scene_plan.get("repair_status", "clean"),
        "substantial_repair_count": len(substantial_repairs),
        "substantial_repairs": substantial_repairs,
        "failure_reason": failure_reason,
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


def _short_text(value: Any, limit: int) -> str:
    cleaned = clean_text(value)
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 3:
        return "." * max(0, limit)
    candidate = cleaned[: limit - 3].rstrip(" ,.;:")
    if " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0].rstrip(" ,.;:")
    return (candidate or cleaned[: limit - 3].rstrip(" ,.;:")) + "..."
