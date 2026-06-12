from __future__ import annotations

from collections import Counter
import json
import math
import re
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..common import (
    clean_text,
    count_words,
    counter_dict,
    dedupe,
    first_url,
    format_timestamp,
    iso_now,
    meaningful_words,
    normalize_voiceover_package,
    record_text,
    safe_float,
    safe_int,
    screenshot_target_candidates,
    short_text,
    split_script_units,
    voiceover_chunks,
)
from .config import (
    EPISODE_DIRECTOR_PROMPT_MODULE,
    NEXT_MODULE,
    OLD_CARD_RENDER_KINDS,
    PACKAGE_TYPE,
    STORY_VISUAL_PLANNER_PROMPT_MODULE,
    SUPPORTED_FORMAT,
)
from .contract import VisualPlannerRequest, VisualPlannerResponse
from .llm_client import make_llm
from .llm_logging import build_llm_call_log
from .prompt_loader import load_prompt_bundle


TASK_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\n"
    "{user_preamble}\n\n"
    "Task payload:\n"
    "{task_payload}"
)

RenderKind = Literal["source_article_scene", "logo_reveal_scene", "kinetic_type_scene"]
CropStrategy = Literal["article_viewport", "headline_then_body", "target_text_focus"]
SourceMotionStyle = Literal["slow_push", "highlight_scan", "browser_zoom"]
LogoMotionStyle = Literal["pop_reveal", "slide_stack", "spotlight"]
KineticAnimationStyle = Literal["typewriter", "word_snap", "highlight_sweep"]
BackgroundMotif = Literal["newsroom_grid", "device_glow", "abstract_ai"]

CLOSING_RE = re.compile(r"\b(today'?s roundup|so today|the ai race is no longer|thanks for watching|that is the bigger shift)\b", re.IGNORECASE)


class EpisodeDirectorDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual_language: str
    pacing_notes: str
    recurring_motifs: list[str] = Field(default_factory=list)
    typography_notes: str
    color_notes: str
    scene_mix_notes: str
    transition_notes: str
    avoid_patterns: list[str] = Field(default_factory=list)


class SceneDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int
    start_unit_order: int
    end_unit_order: int
    render_kind: RenderKind
    script_excerpt: str
    visual_intent: str
    source_record_key: str = ""
    url: str = ""
    target_text: str = ""
    highlight_phrases: list[str] = Field(default_factory=list)
    crop_strategy: CropStrategy = "target_text_focus"
    overlay_headline: str = ""
    source_motion_style: SourceMotionStyle = "slow_push"
    entities: list[str] = Field(default_factory=list)
    primary_entity: str = ""
    logo_strategy: str = "simple_icons_then_favicon_then_text"
    companion_text: str = ""
    logo_motion_style: LogoMotionStyle = "pop_reveal"
    phrases: list[str] = Field(default_factory=list)
    emphasis_words: list[str] = Field(default_factory=list)
    animation_style: KineticAnimationStyle = "typewriter"
    background_motif: BackgroundMotif = "newsroom_grid"
    reason: str

    @field_validator("order", "start_unit_order", "end_unit_order")
    @classmethod
    def order_fields_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("scene order and unit orders must be positive")
        return value


class StoryVisualPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    visual_strategy: str
    key_entities: list[str] = Field(default_factory=list)
    scene_timeline: list[SceneDraft]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("story_id", "visual_strategy")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("story_id and visual_strategy must not be empty")
        return value


def run(input_json: dict) -> dict:
    request = VisualPlannerRequest.model_validate(input_json)
    generated_at = iso_now()
    run_id = request.run.run_id
    config = request.config.model_dump(mode="json")
    video_packaging = request.input.video_packaging
    video_packet = video_packaging.data.video_packet
    selected_format = clean_text(video_packaging.data.selected_format)
    llm_calls: list[dict[str, Any]] = []

    failure_reason = _upstream_failure_reason(video_packaging, selected_format, video_packet)
    script_text = _extract_script_text(request)
    script_source = clean_text(request.input.script_source or "")
    if not failure_reason and not script_text:
        failure_reason = "Script text is missing or empty."
    if failure_reason:
        return _failed_response(
            run_id=run_id,
            generated_at=generated_at,
            selected_format=selected_format or SUPPORTED_FORMAT,
            reason=failure_reason,
            llm_calls=llm_calls,
        )

    voiceover_package = normalize_voiceover_package(request.input.voiceover)
    script_units = _build_script_units(
        script_text=script_text,
        voiceover_package=voiceover_package,
        video_packet=video_packet,
        words_per_minute=int(config["words_per_minute"]),
    )
    stories = _selected_stories(video_packet)
    source_index = _build_source_index(stories)
    story_ranges = _story_time_ranges(video_packet, stories)
    story_sections = _build_story_sections(
        request=request,
        script_text=script_text,
        script_units=script_units,
        video_packet=video_packet,
        stories=stories,
    )

    episode_prompt_bundle = load_prompt_bundle(EPISODE_DIRECTOR_PROMPT_MODULE, config["prompt_version"])
    story_prompt_bundle = load_prompt_bundle(STORY_VISUAL_PLANNER_PROMPT_MODULE, config["prompt_version"])
    llm = make_llm(
        provider=config["provider"],
        model=config["model"],
        temperature=float(config["temperature"]),
        base_url=config.get("base_url"),
    )

    episode_direction = _generate_episode_direction(
        script_units=script_units,
        video_packet=video_packet,
        voiceover_package=voiceover_package,
        stories=stories,
        story_sections=story_sections,
        config=config,
        prompt_bundle=episode_prompt_bundle,
        llm=llm,
        llm_calls=llm_calls,
    )
    story_drafts = _generate_story_visual_plans(
        story_sections=story_sections,
        stories=stories,
        source_index=source_index,
        episode_direction=episode_direction,
        config=config,
        prompt_bundle=story_prompt_bundle,
        llm=llm,
        llm_calls=llm_calls,
    )
    visual_scene_plan = _build_visual_scene_plan(
        run_id=run_id,
        generated_at=generated_at,
        script_text=script_text,
        script_source=script_source,
        script_units=script_units,
        video_packet=video_packet,
        voiceover_package=voiceover_package,
        stories=stories,
        story_ranges=story_ranges,
        story_sections=story_sections,
        source_index=source_index,
        episode_direction=episode_direction,
        story_drafts=story_drafts,
        config=config,
        llm_calls=llm_calls,
    )
    checks = _check_scene_plan(visual_scene_plan, config)
    visual_scene_plan["checks"] = checks
    status = "ok" if checks["passed"] else "failed"
    failure_reason = "" if status == "ok" else "; ".join(checks["errors"])

    response = VisualPlannerResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": SUPPORTED_FORMAT,
            "visual_scene_plan": visual_scene_plan,
        },
        summary=_build_summary(visual_scene_plan, llm_calls, failure_reason),
        handoff={
            "ready_for_visual_asset_resolution": status == "ok",
            "next_module": NEXT_MODULE,
            "selected_format": SUPPORTED_FORMAT,
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _generate_episode_direction(
    *,
    script_units: list[dict[str, Any]],
    video_packet: dict[str, Any],
    voiceover_package: dict[str, Any] | None,
    stories: list[dict[str, Any]],
    story_sections: list[dict[str, Any]],
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    structured_llm = llm.with_structured_output(EpisodeDirectorDraft, include_raw=True)
    chain = TASK_PROMPT | structured_llm
    total_duration = _total_duration(script_units, voiceover_package, video_packet)
    payload = {
        "task": "Create the global motion direction for an AI news roundup visual plan.",
        "selected_format": SUPPORTED_FORMAT,
        "style": config["style"],
        "scene_policy": config["scene_policy"],
        "visual_capabilities": _visual_capabilities_for_prompt(config),
        "audio_context": _audio_context(voiceover_package, total_duration),
        "video_packet_summary": _video_packet_summary(video_packet),
        "story_section_summary": _story_section_summary(story_sections),
        "selected_stories": _story_summaries_for_prompt(stories),
        "banned_visual_language": sorted(OLD_CARD_RENDER_KINDS),
        "required_behavior": {
            "do_not_plan_individual_scene_timeline": True,
            "give_global_direction_only": True,
            "optimize_for_youtube_motion_not_presentation_cards": True,
        },
    }
    return _invoke_chain(
        module_name=EPISODE_DIRECTOR_PROMPT_MODULE,
        output_model=EpisodeDirectorDraft,
        chain=chain,
        prompt_bundle=prompt_bundle,
        task_payload=json.dumps(payload, ensure_ascii=False, indent=2),
        config=config,
        metadata={
            "story_count": len(stories),
            "script_unit_count": len(script_units),
            "total_duration_seconds": round(total_duration, 2),
        },
        llm_calls=llm_calls,
    )


def _generate_story_visual_plans(
    *,
    story_sections: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    source_index: dict[str, Any],
    episode_direction: dict[str, Any],
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    structured_llm = llm.with_structured_output(StoryVisualPlanDraft, include_raw=True)
    chain = TASK_PROMPT | structured_llm
    stories_by_id = {clean_text(story.get("story_id", "")): story for story in stories}
    drafts: dict[str, dict[str, Any]] = {}
    for section in story_sections:
        if section.get("section_type") != "story":
            continue
        story_id = clean_text(section.get("story_id", ""))
        story = stories_by_id.get(story_id)
        if not story:
            continue
        payload = {
            "task": "Create renderable visual scenes for exactly one story in a finished AI news roundup.",
            "selected_format": SUPPORTED_FORMAT,
            "episode_direction": episode_direction,
            "scene_policy": config["scene_policy"],
            "visual_capabilities": _visual_capabilities_for_prompt(config),
            "story": _story_for_prompt(story, source_index, config),
            "story_section": _section_for_prompt(section),
            "script_units": _script_units_for_story_prompt(section.get("script_units", [])),
            "allowed_render_kinds": config["scene_policy"]["allowed_render_kinds"],
            "banned_visual_language": sorted(OLD_CARD_RENDER_KINDS),
            "required_behavior": {
                "plan_only_this_story": True,
                "use_only_this_story_records": True,
                "use_absolute_start_unit_order_values_from_script_units": True,
                "do_not_create_title_timeline_entity_recap_or_fallback_cards": True,
                "prefer_source_article_scene_for_source_specific_claims": True,
                "prefer_logo_reveal_scene_for_entity_introductions": True,
                "prefer_kinetic_type_scene_for_punchy_or_transitional_phrases": True,
            },
        }
        metadata = {
            "story_id": story_id,
            "story_title": clean_text(story.get("story_title", "")),
            "script_unit_count": len(section.get("script_units", [])),
            "source_record_count": len(source_index["record_keys_by_story"].get(story_id, [])),
        }
        try:
            draft = _invoke_chain(
                module_name=STORY_VISUAL_PLANNER_PROMPT_MODULE,
                output_model=StoryVisualPlanDraft,
                chain=chain,
                prompt_bundle=prompt_bundle,
                task_payload=json.dumps(payload, ensure_ascii=False, indent=2),
                config=config,
                metadata=metadata,
                llm_calls=llm_calls,
            )
        except Exception as exc:
            llm_calls.append(
                build_llm_call_log(
                    module_name=STORY_VISUAL_PLANNER_PROMPT_MODULE,
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt="",
                    raw_response=None,
                    parsed_output=None,
                    metadata={**metadata, "fallback_used": True},
                    duration_seconds=0.0,
                    parse_error=str(exc),
                )
            )
            drafts[story_id] = {
                "story_id": story_id,
                "visual_strategy": "Deterministic fallback scenes were used because the story-level LLM call failed.",
                "key_entities": [],
                "scene_timeline": [],
                "warnings": [f"Story visual planner fallback used: {type(exc).__name__}: {exc}"],
            }
            continue
        returned_story_id = clean_text(draft.get("story_id", ""))
        if returned_story_id != story_id:
            if not _story_ids_equivalent(returned_story_id, story_id):
                drafts[story_id] = {
                    "story_id": story_id,
                    "visual_strategy": "Deterministic fallback scenes were used because the story-level LLM returned the wrong story id.",
                    "key_entities": [],
                    "scene_timeline": [],
                    "warnings": [f"Story visual planner returned story_id {returned_story_id!r}; expected {story_id!r}"],
                }
                continue
            draft["story_id"] = story_id
            draft.setdefault("warnings", []).append(f"Planner returned punctuation-equivalent story_id {returned_story_id!r}; canonicalized to {story_id!r}.")
        drafts[story_id] = draft
    return drafts


def _invoke_chain(
    *,
    module_name: str,
    output_model,
    chain,
    prompt_bundle: dict[str, str],
    task_payload: str,
    config: dict[str, Any],
    metadata: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": task_payload,
    }
    rendered_prompt = TASK_PROMPT.format(**prompt_inputs)
    started = time.time()
    result = chain.invoke(prompt_inputs)
    duration = time.time() - started

    raw = result.get("raw") if isinstance(result, dict) else None
    parsed = result.get("parsed") if isinstance(result, dict) else result
    parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
    if parsing_error is not None or parsed is None:
        llm_calls.append(
            build_llm_call_log(
                module_name=module_name,
                provider=config["provider"],
                model=config["model"],
                rendered_prompt=rendered_prompt,
                raw_response=raw,
                parsed_output=None,
                metadata=metadata,
                duration_seconds=duration,
                parse_error=str(parsing_error),
            )
        )
        error = ValueError(f"LLM structured output failed for {module_name}")
        if isinstance(parsing_error, BaseException):
            raise error from parsing_error
        raise error

    parsed_model = parsed if isinstance(parsed, output_model) else output_model.model_validate(parsed)
    parsed_output = parsed_model.model_dump(mode="json")
    llm_calls.append(
        build_llm_call_log(
            module_name=module_name,
            provider=config["provider"],
            model=config["model"],
            rendered_prompt=rendered_prompt,
            raw_response=raw,
            parsed_output=parsed_output,
            metadata=metadata,
            duration_seconds=duration,
        )
    )
    return parsed_output


def _build_visual_scene_plan(
    *,
    run_id: str,
    generated_at: str,
    script_text: str,
    script_source: str,
    script_units: list[dict[str, Any]],
    video_packet: dict[str, Any],
    voiceover_package: dict[str, Any] | None,
    stories: list[dict[str, Any]],
    story_ranges: list[dict[str, Any]],
    story_sections: list[dict[str, Any]],
    source_index: dict[str, Any],
    episode_direction: dict[str, Any],
    story_drafts: dict[str, dict[str, Any]],
    config: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    scene_timeline = _build_scene_timeline(
        story_sections=story_sections,
        script_units=script_units,
        stories=stories,
        source_index=source_index,
        story_drafts=story_drafts,
        config=config,
    )
    asset_manifest = _build_asset_manifest(scene_timeline)
    total_duration = _total_duration(script_units, voiceover_package, video_packet)
    coverage = _coverage_report(scene_timeline, script_units, total_duration, config)
    return {
        "package_type": PACKAGE_TYPE,
        "selected_format": SUPPORTED_FORMAT,
        "planning_strategy": "episode_director_plus_per_story",
        "run_id": run_id,
        "generated_at": generated_at,
        "episode_style": _episode_style(episode_direction, config),
        "story_plans": _story_plans(stories, story_drafts, scene_timeline),
        "story_sections": _sections_for_output(story_sections),
        "scene_timeline": scene_timeline,
        "asset_manifest": asset_manifest,
        "coverage": coverage,
        "planning_calls": _planning_calls_from_llm_calls(llm_calls),
        "source_script": {
            "script_source": script_source or "script_generation",
            "word_count": count_words(script_text),
        },
        "audio_timeline": _audio_context(voiceover_package, total_duration),
        "scene_policy": config["scene_policy"],
        "visual_capabilities": _visual_capabilities_for_prompt(config),
        "source_context": {
            "selected_story_ids": [story.get("story_id") for story in stories if story.get("story_id")],
            "source_url_count": len(source_index["source_urls"]),
            "source_urls": sorted(source_index["source_urls"]),
        },
        "story_time_ranges": story_ranges,
        "planner_warnings": _planner_warnings(story_drafts),
    }


def _build_scene_timeline(
    *,
    story_sections: list[dict[str, Any]],
    script_units: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    source_index: dict[str, Any],
    story_drafts: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    stories_by_id = {clean_text(story.get("story_id", "")): story for story in stories}
    policy = config["scene_policy"]
    counts: Counter[str] = Counter()
    stitched: list[dict[str, Any]] = []
    for section in story_sections:
        story_id = clean_text(section.get("story_id", ""))
        story = stories_by_id.get(story_id, {})
        candidates = []
        if section.get("section_type") == "story":
            candidates = _normalize_story_candidate_scenes(
                story=story,
                section=section,
                source_index=source_index,
                story_draft=story_drafts.get(story_id, {}),
                counts=counts,
                config=config,
            )
        stitched.extend(
            _stitch_section(
                section=section,
                candidates=candidates,
                script_units=script_units,
                story=story,
                source_index=source_index,
                counts=counts,
                policy=policy,
            )
        )
    return _finalize_scene_order(stitched, policy)


def _normalize_story_candidate_scenes(
    *,
    story: dict[str, Any],
    section: dict[str, Any],
    source_index: dict[str, Any],
    story_draft: dict[str, Any],
    counts: Counter[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    policy = config["scene_policy"]
    story_id = clean_text(section.get("story_id", ""))
    section_start = safe_int(section.get("start_unit_order"), 1)
    section_end = safe_int(section.get("end_unit_order"), section_start)
    candidates: list[dict[str, Any]] = []
    draft_scenes = [
        scene
        for scene in story_draft.get("scene_timeline", [])
        if isinstance(scene, dict)
    ]
    for draft in sorted(draft_scenes, key=lambda scene: safe_int(scene.get("order"), 999999)):
        start_unit = min(section_end, max(section_start, safe_int(draft.get("start_unit_order"), section_start)))
        end_unit = min(section_end, max(start_unit, safe_int(draft.get("end_unit_order"), start_unit)))
        render_kind = _normalize_render_kind(draft, policy, counts, story_id, source_index)
        source_record_key, url = _source_for_scene(draft, story_id, render_kind, source_index)
        if render_kind == "source_article_scene" and not url:
            render_kind = "logo_reveal_scene" if _primary_entity_for_story(story_id, source_index) else "kinetic_type_scene"
            source_record_key, url = "", ""
        script_excerpt = clean_text(draft.get("script_excerpt")) or _section_unit_excerpt(section, start_unit, end_unit)
        payload = _payload_for_scene(
            draft=draft,
            render_kind=render_kind,
            story_id=story_id,
            source_record_key=source_record_key,
            url=url,
            script_excerpt=script_excerpt,
            source_index=source_index,
        )
        candidates.append(
            {
                "story_id": story_id,
                "story_title": clean_text(story.get("story_title", "")),
                "section_type": "story",
                "start_unit_order": start_unit,
                "end_unit_order": end_unit,
                "render_kind": render_kind,
                "script_excerpt": script_excerpt,
                "visual_intent": clean_text(draft.get("visual_intent", "")) or _default_visual_intent(render_kind),
                "payload": payload,
                "source_record_keys": [source_record_key] if source_record_key else [],
                "source_urls": [url] if url else [],
                "reason": clean_text(draft.get("reason", "")),
            }
        )
    return candidates


def _stitch_section(
    *,
    section: dict[str, Any],
    candidates: list[dict[str, Any]],
    script_units: list[dict[str, Any]],
    story: dict[str, Any],
    source_index: dict[str, Any],
    counts: Counter[str],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    start_unit = safe_int(section.get("start_unit_order"), 1)
    end_unit = safe_int(section.get("end_unit_order"), start_unit)
    if start_unit < 1 or end_unit < start_unit:
        return []
    scenes: list[dict[str, Any]] = []
    cursor = start_unit
    usable_candidates = sorted(candidates, key=lambda scene: (safe_int(scene.get("start_unit_order"), 999999), safe_int(scene.get("end_unit_order"), 999999)))
    for candidate in usable_candidates:
        candidate_start = min(end_unit, max(cursor, safe_int(candidate.get("start_unit_order"), cursor)))
        candidate_end = min(end_unit, max(candidate_start, safe_int(candidate.get("end_unit_order"), candidate_start)))
        if candidate_start > cursor:
            scenes.extend(
                _deterministic_scenes_for_range(
                    section=section,
                    story=story,
                    start_unit=cursor,
                    end_unit=candidate_start - 1,
                    script_units=script_units,
                    source_index=source_index,
                    counts=counts,
                    policy=policy,
                )
            )
        if candidate_end >= candidate_start:
            candidate_scenes = _split_candidate_by_duration(
                candidate=candidate,
                start_unit=candidate_start,
                end_unit=candidate_end,
                script_units=script_units,
                policy=policy,
            )
            scenes.extend(candidate_scenes)
            counts[clean_text(candidate.get("render_kind", ""))] += len(candidate_scenes)
        cursor = candidate_end + 1
        if cursor > end_unit:
            break
    if cursor <= end_unit:
        scenes.extend(
            _deterministic_scenes_for_range(
                section=section,
                story=story,
                start_unit=cursor,
                end_unit=end_unit,
                script_units=script_units,
                source_index=source_index,
                counts=counts,
                policy=policy,
            )
        )
    return scenes


def _deterministic_scenes_for_range(
    *,
    section: dict[str, Any],
    story: dict[str, Any],
    start_unit: int,
    end_unit: int,
    script_units: list[dict[str, Any]],
    source_index: dict[str, Any],
    counts: Counter[str],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    if end_unit < start_unit:
        return []
    scenes: list[dict[str, Any]] = []
    for group_index, unit_slice in enumerate(_unit_time_slices(start_unit, end_unit, script_units, policy), start=1):
        candidate = _fallback_candidate_for_slice(
            section=section,
            story=story,
            unit_slice=unit_slice,
            script_units=script_units,
            source_index=source_index,
            counts=counts,
            group_index=group_index,
        )
        scenes.append(_scene_from_candidate_slice(candidate, unit_slice, script_units))
        counts[clean_text(candidate.get("render_kind", ""))] += 1
    return scenes


def _split_candidate_by_duration(
    *,
    candidate: dict[str, Any],
    start_unit: int,
    end_unit: int,
    script_units: list[dict[str, Any]],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    scenes = []
    for unit_slice in _unit_time_slices(start_unit, end_unit, script_units, policy):
        scenes.append(_scene_from_candidate_slice(candidate, unit_slice, script_units))
    return scenes


def _unit_time_slices(
    start_unit: int,
    end_unit: int,
    script_units: list[dict[str, Any]],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    max_seconds = max(1.0, safe_float(policy.get("max_scene_seconds"), 14.0))
    range_units = script_units[start_unit - 1 : end_unit]
    if not range_units:
        return []
    section_start = safe_float(range_units[0].get("start_seconds"), 0.0)
    section_end = safe_float(range_units[-1].get("end_seconds"), section_start)
    slices: list[dict[str, Any]] = []
    cursor = section_start
    while cursor < section_end:
        slice_end = min(section_end, cursor + max_seconds)
        unit_orders = []
        for unit in range_units:
            unit_order = safe_int(unit.get("order"), 0)
            unit_start = safe_float(unit.get("start_seconds"), 0.0)
            unit_end = safe_float(unit.get("end_seconds"), unit_start)
            if unit_end > cursor and unit_start < slice_end:
                unit_orders.append(unit_order)
        if not unit_orders:
            unit_orders = [start_unit]
        slices.append(
            {
                "start_unit_order": min(unit_orders),
                "end_unit_order": max(unit_orders),
                "unit_orders": unit_orders,
                "start_seconds": round(cursor, 2),
                "end_seconds": round(slice_end, 2),
            }
        )
        cursor = slice_end
    return slices


def _fallback_candidate_for_slice(
    *,
    section: dict[str, Any],
    story: dict[str, Any],
    unit_slice: dict[str, Any],
    script_units: list[dict[str, Any]],
    source_index: dict[str, Any],
    counts: Counter[str],
    group_index: int,
) -> dict[str, Any]:
    del counts
    story_id = clean_text(section.get("story_id", ""))
    section_type = clean_text(section.get("section_type", ""))
    excerpt = _script_excerpt(script_units, unit_slice["start_unit_order"], unit_slice["end_unit_order"])
    first_key = (source_index["record_keys_by_story"].get(story_id) or [""])[0]
    record = source_index["records_by_key"].get(first_key, {})
    url = clean_text(record.get("url", ""))
    primary_entity = _primary_entity_for_story(story_id, source_index)
    if section_type != "story":
        render_kind = "kinetic_type_scene"
    elif group_index == 1 and primary_entity:
        render_kind = "logo_reveal_scene"
    elif url and group_index % 3 == 2:
        render_kind = "source_article_scene"
    elif primary_entity and group_index % 3 == 0:
        render_kind = "logo_reveal_scene"
    else:
        render_kind = "kinetic_type_scene"
    draft = {
        "render_kind": render_kind,
        "source_record_key": first_key,
        "url": url,
        "target_text": (record.get("screenshot_target_candidates") or [record.get("title", "")])[0] if record else "",
        "overlay_headline": clean_text(story.get("story_title", "")) or short_text(excerpt, 70),
        "highlight_phrases": [_short_phrase(excerpt)],
        "primary_entity": primary_entity,
        "entities": [primary_entity] if primary_entity else [],
        "companion_text": clean_text(story.get("story_title", "")) or _short_phrase(excerpt),
        "phrases": [_short_phrase(excerpt)],
        "emphasis_words": meaningful_words(excerpt)[:4],
    }
    source_record_key, source_url = _source_for_scene(draft, story_id, render_kind, source_index)
    payload = _payload_for_scene(
        draft=draft,
        render_kind=render_kind,
        story_id=story_id,
        source_record_key=source_record_key,
        url=source_url,
        script_excerpt=excerpt,
        source_index=source_index,
    )
    return {
        "story_id": story_id,
        "story_title": clean_text(story.get("story_title", "")),
        "section_type": section_type,
        "render_kind": render_kind,
        "script_excerpt": excerpt,
        "visual_intent": _default_visual_intent(render_kind),
        "payload": payload,
        "source_record_keys": [source_record_key] if source_record_key else [],
        "source_urls": [source_url] if source_url else [],
        "reason": "Deterministic stitcher fallback for uncovered narration chunk.",
    }


def _scene_from_candidate_slice(candidate: dict[str, Any], unit_slice: dict[str, Any], script_units: list[dict[str, Any]]) -> dict[str, Any]:
    start_seconds = safe_float(unit_slice.get("start_seconds"), 0.0)
    end_seconds = safe_float(unit_slice.get("end_seconds"), start_seconds)
    return {
        "story_id": clean_text(candidate.get("story_id", "")),
        "story_title": clean_text(candidate.get("story_title", "")),
        "section_type": clean_text(candidate.get("section_type", "")),
        "start_seconds": round(start_seconds, 2),
        "end_seconds": round(end_seconds, 2),
        "duration_seconds": round(max(0.0, end_seconds - start_seconds), 2),
        "start_timestamp": format_timestamp(start_seconds),
        "end_timestamp": format_timestamp(end_seconds),
        "script_unit_start": safe_int(unit_slice.get("start_unit_order"), 1),
        "script_unit_end": safe_int(unit_slice.get("end_unit_order"), 1),
        "covered_unit_orders": unit_slice.get("unit_orders", []),
        "render_kind": clean_text(candidate.get("render_kind", "")),
        "script_excerpt": _script_excerpt(script_units, safe_int(unit_slice.get("start_unit_order"), 1), safe_int(unit_slice.get("end_unit_order"), 1)),
        "visual_intent": clean_text(candidate.get("visual_intent", "")),
        "payload": candidate.get("payload", {}),
        "source_record_keys": candidate.get("source_record_keys", []),
        "source_urls": candidate.get("source_urls", []),
        "reason": clean_text(candidate.get("reason", "")),
    }


def _finalize_scene_order(scenes: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = sorted(scenes, key=lambda scene: (safe_float(scene.get("start_seconds"), 0.0), safe_int(scene.get("script_unit_start"), 0)))
    max_scene_seconds = safe_float(policy.get("max_scene_seconds"), 14.0)
    _close_timeline_gaps(ordered, max_scene_seconds)
    ordered = _compact_scene_timeline(ordered, policy)
    _close_timeline_gaps(ordered, max_scene_seconds)
    finalized: list[dict[str, Any]] = []
    for index, scene in enumerate(ordered, start=1):
        finalized.append(
            {
                "scene_id": f"scene_{index:03d}",
                "scene_order": index,
                **scene,
            }
        )
    return finalized


def _compact_scene_timeline(scenes: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    max_scenes = safe_int(policy.get("max_scenes"), len(scenes))
    max_scene_seconds = safe_float(policy.get("max_scene_seconds"), 14.0)
    min_scene_seconds = safe_float(policy.get("min_scene_seconds"), 3.0)
    compacted = list(scenes)

    def merge_at(index: int) -> None:
        merged = _merge_adjacent_scenes(compacted[index], compacted[index + 1])
        compacted[index : index + 2] = [merged]

    changed = True
    while changed:
        changed = False
        for index in range(len(compacted) - 1):
            first = compacted[index]
            second = compacted[index + 1]
            combined = safe_float(second.get("end_seconds"), 0.0) - safe_float(first.get("start_seconds"), 0.0)
            if combined <= max_scene_seconds + 0.01 and (
                safe_float(first.get("duration_seconds"), 0.0) < min_scene_seconds
                or safe_float(second.get("duration_seconds"), 0.0) < min_scene_seconds
            ):
                merge_at(index)
                changed = True
                break

    while len(compacted) > max_scenes:
        best_index: int | None = None
        best_score: tuple[int, float] | None = None
        for index in range(len(compacted) - 1):
            first = compacted[index]
            second = compacted[index + 1]
            combined = safe_float(second.get("end_seconds"), 0.0) - safe_float(first.get("start_seconds"), 0.0)
            if combined > max_scene_seconds + 0.01:
                continue
            same_story = clean_text(first.get("story_id", "")) == clean_text(second.get("story_id", ""))
            same_section = clean_text(first.get("section_type", "")) == clean_text(second.get("section_type", ""))
            same_kind = clean_text(first.get("render_kind", "")) == clean_text(second.get("render_kind", ""))
            score = (
                0 if same_story and same_section and same_kind else 1 if same_story and same_section else 2,
                combined,
            )
            if best_score is None or score < best_score:
                best_score = score
                best_index = index
        if best_index is None:
            break
        merge_at(best_index)
    return compacted


def _merge_adjacent_scenes(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    preferred = _preferred_scene_for_merge(first, second)
    start = safe_float(first.get("start_seconds"), 0.0)
    end = safe_float(second.get("end_seconds"), start)
    return {
        **preferred,
        "start_seconds": round(start, 2),
        "end_seconds": round(end, 2),
        "duration_seconds": round(max(0.0, end - start), 2),
        "start_timestamp": format_timestamp(start),
        "end_timestamp": format_timestamp(end),
        "script_unit_start": safe_int(first.get("script_unit_start"), safe_int(preferred.get("script_unit_start"), 1)),
        "script_unit_end": safe_int(second.get("script_unit_end"), safe_int(preferred.get("script_unit_end"), 1)),
        "covered_unit_orders": sorted(set(first.get("covered_unit_orders", [])) | set(second.get("covered_unit_orders", []))),
        "script_excerpt": short_text(" ".join([clean_text(first.get("script_excerpt", "")), clean_text(second.get("script_excerpt", ""))]), 420),
        "source_record_keys": dedupe([*first.get("source_record_keys", []), *second.get("source_record_keys", [])]),
        "source_urls": dedupe([*first.get("source_urls", []), *second.get("source_urls", [])]),
        "reason": clean_text(preferred.get("reason", "")) or "Merged adjacent short scenes during deterministic compaction.",
    }


def _preferred_scene_for_merge(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    priority = {"source_article_scene": 0, "logo_reveal_scene": 1, "kinetic_type_scene": 2}
    first_kind = clean_text(first.get("render_kind", ""))
    second_kind = clean_text(second.get("render_kind", ""))
    if priority.get(second_kind, 99) < priority.get(first_kind, 99):
        return dict(second)
    return dict(first)


def _close_timeline_gaps(scenes: list[dict[str, Any]], max_scene_seconds: float) -> None:
    if not scenes:
        return
    scenes[0]["start_seconds"] = 0.0
    scenes[0]["start_timestamp"] = "0:00"
    scenes[0]["duration_seconds"] = round(max(0.0, safe_float(scenes[0].get("end_seconds"), 0.0)), 2)
    for index in range(len(scenes) - 1):
        current = scenes[index]
        next_scene = scenes[index + 1]
        current_end = safe_float(current.get("end_seconds"), 0.0)
        next_start = safe_float(next_scene.get("start_seconds"), current_end)
        gap = next_start - current_end
        if gap <= 0.01:
            continue
        current_duration = safe_float(current.get("duration_seconds"), 0.0)
        if current_duration + gap <= max_scene_seconds + 0.01:
            current["end_seconds"] = round(next_start, 2)
            current["duration_seconds"] = round(max(0.0, next_start - safe_float(current.get("start_seconds"), 0.0)), 2)
            current["end_timestamp"] = format_timestamp(next_start)
            continue
        next_scene["start_seconds"] = round(current_end, 2)
        next_scene["duration_seconds"] = round(max(0.0, safe_float(next_scene.get("end_seconds"), current_end) - current_end), 2)
        next_scene["start_timestamp"] = format_timestamp(current_end)


def _build_story_sections(
    *,
    request: VisualPlannerRequest,
    script_text: str,
    script_units: list[dict[str, Any]],
    video_packet: dict[str, Any],
    stories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    explicit_sections = _script_generation_sections(request)
    if explicit_sections:
        sections = _sections_from_script_generation_sections(explicit_sections, script_units, stories)
    else:
        sections = _sections_from_manual_script(script_text, script_units, stories)
    story_ids_with_units = {section.get("story_id") for section in sections if section.get("section_type") == "story"}
    expected_story_ids = {clean_text(story.get("story_id", "")) for story in stories}
    if expected_story_ids - story_ids_with_units:
        sections = _sections_from_target_proportions(script_units, video_packet, stories)
    return sections


def _script_generation_sections(request: VisualPlannerRequest) -> list[dict[str, Any]]:
    script_generation = request.input.script_generation
    if script_generation is None:
        return []
    package = script_generation.data.script_package
    sections = package.get("sections")
    if not isinstance(sections, list):
        return []
    return [section for section in sections if isinstance(section, dict) and clean_text(section.get("narration_text", ""))]


def _sections_from_script_generation_sections(
    explicit_sections: list[dict[str, Any]],
    script_units: list[dict[str, Any]],
    stories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    story_lookup = {clean_text(story.get("story_id", "")): story for story in stories}
    cursor = 1
    sections: list[dict[str, Any]] = []
    for index, section in enumerate(explicit_sections, start=1):
        target_words = max(1, count_words(clean_text(section.get("narration_text", ""))))
        start = cursor
        consumed = 0
        while cursor <= len(script_units) and (consumed < target_words or index == len(explicit_sections)):
            consumed += safe_int(script_units[cursor - 1].get("word_count"), count_words(script_units[cursor - 1].get("text", "")))
            cursor += 1
            if index != len(explicit_sections) and consumed >= target_words:
                break
        end = max(start, min(len(script_units), cursor - 1))
        section_type = clean_text(section.get("section_type", "story")) or "story"
        story_id = clean_text(section.get("story_id", ""))
        sections.append(
            _section_from_unit_range(
                section_type=section_type if section_type in {"intro", "story", "closing"} else "story",
                story=story_lookup.get(story_id, {}),
                start_unit=start,
                end_unit=end,
                script_units=script_units,
                assignment_method="script_generation_sections",
            )
        )
    return [section for section in sections if section]


def _sections_from_manual_script(script_text: str, script_units: list[dict[str, Any]], stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paragraphs = _script_paragraphs(script_text)
    if not paragraphs:
        return _sections_from_target_proportions(script_units, {"intro_seconds": 0, "closing_seconds": 0}, stories)
    labels = _assign_paragraphs_to_sections(paragraphs, stories)
    unit_labels = _assign_units_to_paragraph_labels(script_units, paragraphs, labels)
    return _sections_from_unit_labels(unit_labels, script_units, stories, assignment_method="manual_script_inference")


def _script_paragraphs(script_text: str) -> list[dict[str, Any]]:
    raw_paragraphs = [clean_text(part) for part in re.split(r"\n\s*\n+", script_text or "") if clean_text(part)]
    if not raw_paragraphs:
        raw_paragraphs = [clean_text(script_text)]
    paragraphs: list[dict[str, Any]] = []
    cursor = 0
    for index, text in enumerate(raw_paragraphs, start=1):
        words = count_words(text)
        start = cursor
        end = cursor + words
        paragraphs.append(
            {
                "paragraph_order": index,
                "text": text,
                "word_count": words,
                "start_word": start,
                "end_word": end,
            }
        )
        cursor = end
    return paragraphs


def _assign_paragraphs_to_sections(paragraphs: list[dict[str, Any]], stories: list[dict[str, Any]]) -> list[dict[str, str]]:
    signatures = [_story_signature(story) for story in stories]
    labels: list[dict[str, str]] = []
    current_story_index: int | None = None
    for index, paragraph in enumerate(paragraphs):
        text = clean_text(paragraph.get("text", ""))
        lower = text.lower()
        if CLOSING_RE.search(lower) and index >= max(1, len(paragraphs) - 4):
            labels.append({"section_type": "closing", "story_id": ""})
            continue
        scores = [_signature_score(lower, signature) for signature in signatures]
        best_index = max(range(len(scores)), key=lambda item: scores[item]) if scores else 0
        best_score = scores[best_index] if scores else 0
        if best_score >= 2:
            if current_story_index is None:
                current_story_index = best_index
            elif best_index == current_story_index:
                current_story_index = best_index
            elif best_index > current_story_index and (_is_story_transition(text) or _has_strong_story_match(lower, signatures[best_index], best_score)):
                current_story_index = best_index
        if current_story_index is None:
            labels.append({"section_type": "intro", "story_id": ""})
        else:
            labels.append(
                {
                    "section_type": "story",
                    "story_id": clean_text(stories[current_story_index].get("story_id", "")),
                }
            )
    return labels


def _assign_units_to_paragraph_labels(
    script_units: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    labels: list[dict[str, str]],
) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    word_cursor = 0
    paragraph_index = 0
    for unit in script_units:
        words = max(1, safe_int(unit.get("word_count"), count_words(unit.get("text", ""))))
        midpoint = word_cursor + words / 2
        while paragraph_index < len(paragraphs) - 1 and midpoint >= safe_float(paragraphs[paragraph_index].get("end_word"), 0.0):
            paragraph_index += 1
        label = labels[min(paragraph_index, len(labels) - 1)] if labels else {"section_type": "story", "story_id": ""}
        assignments.append({"unit_order": safe_int(unit.get("order"), len(assignments) + 1), **label})
        word_cursor += words
    return assignments


def _sections_from_unit_labels(
    unit_labels: list[dict[str, Any]],
    script_units: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    *,
    assignment_method: str,
) -> list[dict[str, Any]]:
    story_lookup = {clean_text(story.get("story_id", "")): story for story in stories}
    sections: list[dict[str, Any]] = []
    if not unit_labels:
        return sections
    current = dict(unit_labels[0])
    start = safe_int(current.get("unit_order"), 1)
    previous = start
    for label in unit_labels[1:]:
        unit_order = safe_int(label.get("unit_order"), previous + 1)
        same = clean_text(label.get("section_type", "")) == clean_text(current.get("section_type", "")) and clean_text(label.get("story_id", "")) == clean_text(current.get("story_id", ""))
        if not same:
            sections.append(
                _section_from_unit_range(
                    section_type=clean_text(current.get("section_type", "")),
                    story=story_lookup.get(clean_text(current.get("story_id", "")), {}),
                    start_unit=start,
                    end_unit=previous,
                    script_units=script_units,
                    assignment_method=assignment_method,
                )
            )
            current = dict(label)
            start = unit_order
        previous = unit_order
    sections.append(
        _section_from_unit_range(
            section_type=clean_text(current.get("section_type", "")),
            story=story_lookup.get(clean_text(current.get("story_id", "")), {}),
            start_unit=start,
            end_unit=previous,
            script_units=script_units,
            assignment_method=assignment_method,
        )
    )
    return [section for section in sections if section]


def _sections_from_target_proportions(
    script_units: list[dict[str, Any]],
    video_packet: dict[str, Any],
    stories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    total_duration = safe_float(script_units[-1].get("end_seconds"), 0.0) if script_units else 0.0
    target_duration = safe_float(video_packet.get("target_duration_seconds"), total_duration) or total_duration or 1.0
    scale = total_duration / target_duration if target_duration else 1.0
    ranges: list[dict[str, Any]] = []
    intro_end = safe_float(video_packet.get("intro_seconds"), 0.0) * scale
    if intro_end > 0:
        ranges.append({"section_type": "intro", "story": {}, "start": 0.0, "end": intro_end})
    cursor = intro_end
    for story in stories:
        segment = story.get("video_segment") if isinstance(story.get("video_segment"), dict) else {}
        duration = safe_float(segment.get("target_seconds"), 0.0) * scale
        ranges.append({"section_type": "story", "story": story, "start": cursor, "end": cursor + duration})
        cursor += duration
    if cursor < total_duration:
        ranges.append({"section_type": "closing", "story": {}, "start": cursor, "end": total_duration})

    labels: list[dict[str, Any]] = []
    for unit in script_units:
        midpoint = _unit_midpoint(unit)
        selected = ranges[-1] if ranges else {"section_type": "story", "story": stories[0] if stories else {}}
        for item in ranges:
            if safe_float(item.get("start"), 0.0) <= midpoint <= safe_float(item.get("end"), 0.0):
                selected = item
                break
        story = selected.get("story") if isinstance(selected.get("story"), dict) else {}
        labels.append(
            {
                "unit_order": safe_int(unit.get("order"), len(labels) + 1),
                "section_type": clean_text(selected.get("section_type", "story")),
                "story_id": clean_text(story.get("story_id", "")),
            }
        )
    return _sections_from_unit_labels(labels, script_units, stories, assignment_method="target_proportion_fallback")


def _section_from_unit_range(
    *,
    section_type: str,
    story: dict[str, Any],
    start_unit: int,
    end_unit: int,
    script_units: list[dict[str, Any]],
    assignment_method: str,
) -> dict[str, Any]:
    if not script_units:
        return {}
    start_unit = min(len(script_units), max(1, start_unit))
    end_unit = min(len(script_units), max(start_unit, end_unit))
    units = script_units[start_unit - 1 : end_unit]
    start_seconds = safe_float(units[0].get("start_seconds"), 0.0)
    end_seconds = safe_float(units[-1].get("end_seconds"), start_seconds)
    story_id = clean_text(story.get("story_id", ""))
    section_id = f"{section_type}_{story_id or start_unit}_{start_unit:03d}_{end_unit:03d}"
    return {
        "section_id": section_id,
        "section_type": section_type or "story",
        "story_id": story_id,
        "story_title": clean_text(story.get("story_title", "")),
        "start_unit_order": start_unit,
        "end_unit_order": end_unit,
        "unit_orders": [safe_int(unit.get("order"), index) for index, unit in enumerate(units, start=start_unit)],
        "start_seconds": round(start_seconds, 2),
        "end_seconds": round(end_seconds, 2),
        "duration_seconds": round(max(0.0, end_seconds - start_seconds), 2),
        "start_timestamp": format_timestamp(start_seconds),
        "end_timestamp": format_timestamp(end_seconds),
        "text": _script_excerpt(script_units, start_unit, end_unit),
        "word_count": sum(safe_int(unit.get("word_count"), count_words(unit.get("text", ""))) for unit in units),
        "assignment_method": assignment_method,
        "script_units": [
            {
                "unit_id": unit["unit_id"],
                "order": unit["order"],
                "start_seconds": unit["start_seconds"],
                "end_seconds": unit["end_seconds"],
                "duration_seconds": unit["duration_seconds"],
                "text": unit["text"],
            }
            for unit in units
        ],
    }


def _normalize_render_kind(
    draft: dict[str, Any],
    policy: dict[str, Any],
    counts: Counter[str],
    story_id: str,
    source_index: dict[str, Any],
) -> str:
    allowed = set(policy["allowed_render_kinds"])
    render_kind = clean_text(draft.get("render_kind", ""))
    if render_kind in OLD_CARD_RENDER_KINDS or render_kind not in allowed:
        render_kind = _best_render_kind_for_draft(draft, story_id, source_index, allowed)
    caps = {
        "source_article_scene": int(policy["max_source_article_scenes"]),
        "logo_reveal_scene": int(policy["max_logo_reveal_scenes"]),
        "kinetic_type_scene": int(policy["max_kinetic_type_scenes"]),
    }
    if counts.get(render_kind, 0) >= caps[render_kind]:
        render_kind = "kinetic_type_scene" if "kinetic_type_scene" in allowed else next(iter(allowed))
    return render_kind


def _best_render_kind_for_draft(
    draft: dict[str, Any],
    story_id: str,
    source_index: dict[str, Any],
    allowed: set[str],
) -> str:
    if "source_article_scene" in allowed and _source_for_scene(draft, story_id, "source_article_scene", source_index)[1]:
        return "source_article_scene"
    if "logo_reveal_scene" in allowed and (_primary_entity_for_story(story_id, source_index) or clean_text(draft.get("primary_entity", ""))):
        return "logo_reveal_scene"
    return "kinetic_type_scene" if "kinetic_type_scene" in allowed else next(iter(allowed))


def _payload_for_scene(
    *,
    draft: dict[str, Any],
    render_kind: str,
    story_id: str,
    source_record_key: str,
    url: str,
    script_excerpt: str,
    source_index: dict[str, Any],
) -> dict[str, Any]:
    if render_kind == "source_article_scene":
        target_text = clean_text(draft.get("target_text", ""))
        if not target_text and source_record_key:
            record = source_index["records_by_key"].get(source_record_key, {})
            candidates = record.get("screenshot_target_candidates", [])
            target_text = candidates[0] if candidates else clean_text(record.get("title", ""))
        return {
            "url": url,
            "source_record_key": source_record_key,
            "target_text": short_text(target_text or script_excerpt, 260),
            "highlight_phrases": dedupe([clean_text(item) for item in draft.get("highlight_phrases", [])])[:4],
            "crop_strategy": clean_text(draft.get("crop_strategy", "")) or "target_text_focus",
            "overlay_headline": short_text(clean_text(draft.get("overlay_headline", "")) or script_excerpt, 70),
            "motion_style": clean_text(draft.get("source_motion_style", "")) or "slow_push",
        }
    if render_kind == "logo_reveal_scene":
        primary_entity = clean_text(draft.get("primary_entity", "")) or _primary_entity_for_story(story_id, source_index)
        entities = dedupe([primary_entity, *[clean_text(item) for item in draft.get("entities", [])]])[:4]
        return {
            "entities": entities,
            "primary_entity": primary_entity or "AI",
            "logo_strategy": clean_text(draft.get("logo_strategy", "")) or "simple_icons_then_favicon_then_text",
            "companion_text": short_text(clean_text(draft.get("companion_text", "")) or script_excerpt, 72),
            "motion_style": clean_text(draft.get("logo_motion_style", "")) or "pop_reveal",
        }
    phrases = dedupe([clean_text(item) for item in draft.get("phrases", [])])
    if not phrases:
        phrases = [_short_phrase(script_excerpt)]
    return {
        "phrases": [short_text(phrase, 54) for phrase in phrases[:3]],
        "emphasis_words": dedupe([clean_text(item) for item in draft.get("emphasis_words", [])])[:6],
        "animation_style": clean_text(draft.get("animation_style", "")) or "typewriter",
        "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
    }


def _build_asset_manifest(scene_timeline: list[dict[str, Any]]) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    for scene in scene_timeline:
        render_kind = scene["render_kind"]
        asset_type = {
            "source_article_scene": "source_screenshot",
            "logo_reveal_scene": "logo_asset",
            "kinetic_type_scene": "none",
        }[render_kind]
        requests.append(
            {
                "asset_request_id": f"asset_{scene['scene_order']:03d}",
                "scene_id": scene["scene_id"],
                "render_kind": render_kind,
                "asset_type": asset_type,
                "required": render_kind in {"source_article_scene", "logo_reveal_scene"},
                "payload": scene["payload"],
            }
        )
    return {
        "asset_request_count": len(requests),
        "asset_type_counts": counter_dict([request["asset_type"] for request in requests]),
        "requests": requests,
    }


def _selected_stories(video_packet: dict[str, Any]) -> list[dict[str, Any]]:
    stories = video_packet.get("stories")
    if not isinstance(stories, list):
        stories = video_packet.get("selected_stories")
    usable = [story for story in stories if isinstance(story, dict)] if isinstance(stories, list) else []
    return sorted(
        usable,
        key=lambda story: safe_int((story.get("video_segment") or {}).get("segment_order"), safe_int(story.get("rank"), 999999)),
    )


def _story_time_ranges(video_packet: dict[str, Any], stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = safe_float(video_packet.get("intro_seconds"), 0.0)
    ranges: list[dict[str, Any]] = []
    for story in stories:
        story_id = clean_text(story.get("story_id", ""))
        segment = story.get("video_segment") if isinstance(story.get("video_segment"), dict) else {}
        duration = safe_float(segment.get("target_seconds"), 0.0)
        if duration <= 0:
            duration = safe_float(video_packet.get("segment_seconds"), 60.0)
        ranges.append(
            {
                "story_id": story_id,
                "story_title": clean_text(story.get("story_title", "")),
                "start_seconds": round(cursor, 2),
                "end_seconds": round(cursor + duration, 2),
                "duration_seconds": round(duration, 2),
            }
        )
        cursor += duration
    return ranges


def _build_source_index(stories: list[dict[str, Any]]) -> dict[str, Any]:
    records_by_key: dict[str, dict[str, Any]] = {}
    record_keys_by_story: dict[str, list[str]] = {}
    source_urls: set[str] = set()
    story_identity_by_id: dict[str, dict[str, Any]] = {}

    for story in stories:
        story_id = clean_text(story.get("story_id", ""))
        if not story_id:
            continue
        story_identity_by_id[story_id] = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
        record_keys_by_story[story_id] = []
        for record in story.get("records", []):
            if not isinstance(record, dict):
                continue
            key = clean_text(record.get("record_key", ""))
            if not key:
                continue
            url = first_url(record)
            records_by_key[key] = {
                "record_key": key,
                "story_id": story_id,
                "url": url,
                "title": clean_text(record.get("title", "")),
                "source_name": clean_text(record.get("source_name") or record.get("source", "")),
                "source_group": clean_text(record.get("source_group", "")),
                "published_at": clean_text(record.get("published_at", "")),
                "summary_or_description": clean_text(record.get("summary") or record.get("description") or ""),
                "content_excerpt": record_text(record, max_chars=1600),
                "screenshot_target_candidates": screenshot_target_candidates(record),
            }
            record_keys_by_story[story_id].append(key)
            if url:
                source_urls.add(url)
    return {
        "records_by_key": records_by_key,
        "record_keys_by_story": record_keys_by_story,
        "source_urls": source_urls,
        "story_identity_by_id": story_identity_by_id,
    }


def _story_for_prompt(story: dict[str, Any], source_index: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    story_id = clean_text(story.get("story_id", ""))
    source_policy = config["source_policy"]
    max_records = int(source_policy["max_records_per_story_for_prompt"])
    max_record_chars = int(source_policy["max_record_chars_for_prompt"])
    records: list[dict[str, Any]] = []
    for key in source_index["record_keys_by_story"].get(story_id, [])[:max_records]:
        record = source_index["records_by_key"].get(key, {})
        records.append(
            {
                "record_key": key,
                "title": record.get("title", ""),
                "source_name": record.get("source_name", ""),
                "source_group": record.get("source_group", ""),
                "url": record.get("url", ""),
                "published_at": record.get("published_at", ""),
                "summary_or_description": short_text(record.get("summary_or_description", ""), 700),
                "content_excerpt": short_text(record.get("content_excerpt", ""), max_record_chars),
                "screenshot_target_candidates": record.get("screenshot_target_candidates", [])[:4],
            }
        )
    return {
        "story_id": story_id,
        "rank": story.get("rank"),
        "priority_bucket": clean_text(story.get("priority_bucket", "")),
        "story_title": clean_text(story.get("story_title", "")),
        "story_identity": story.get("story_identity", {}),
        "video_segment": story.get("video_segment", {}),
        "source_groups": story.get("source_groups", []),
        "records": records,
    }


def _story_summaries_for_prompt(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "story_id": clean_text(story.get("story_id", "")),
            "rank": story.get("rank"),
            "story_title": clean_text(story.get("story_title", "")),
            "story_identity": story.get("story_identity", {}),
            "video_segment": story.get("video_segment", {}),
            "record_count": len(story.get("records", [])),
        }
        for story in stories
    ]


def _visual_capabilities_for_prompt(config: dict[str, Any]) -> dict[str, Any]:
    allowed = set(config["scene_policy"]["allowed_render_kinds"])
    capabilities = config.get("visual_capabilities", {})
    return {
        key: value
        for key, value in capabilities.items()
        if key in allowed and isinstance(value, dict)
    }


def _source_for_scene(
    draft: dict[str, Any],
    story_id: str,
    render_kind: str,
    source_index: dict[str, Any],
) -> tuple[str, str]:
    if render_kind != "source_article_scene":
        return "", ""
    requested_key = clean_text(draft.get("source_record_key", ""))
    requested_url = clean_text(draft.get("url", ""))
    story_keys = source_index["record_keys_by_story"].get(story_id, [])
    if requested_key in story_keys:
        record = source_index["records_by_key"].get(requested_key, {})
        return requested_key, clean_text(record.get("url") or requested_url)
    if requested_url:
        for key in story_keys:
            record = source_index["records_by_key"].get(key, {})
            if clean_text(record.get("url")) == requested_url:
                return key, requested_url
    for key in story_keys:
        url = clean_text(source_index["records_by_key"].get(key, {}).get("url", ""))
        if url:
            return key, url
    return "", ""


def _episode_style(episode_direction: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "visual_language": clean_text(episode_direction.get("visual_language")) or config["style"]["visual_language"],
        "pacing_notes": clean_text(episode_direction.get("pacing_notes")) or config["style"]["motion_style"],
        "recurring_motifs": [clean_text(item) for item in episode_direction.get("recurring_motifs", []) if clean_text(item)],
        "typography_notes": clean_text(episode_direction.get("typography_notes")) or config["style"]["typography"],
        "color_notes": clean_text(episode_direction.get("color_notes")) or config["style"]["color_system"],
        "scene_mix_notes": clean_text(episode_direction.get("scene_mix_notes", "")),
        "transition_notes": clean_text(episode_direction.get("transition_notes", "")),
        "avoid_patterns": [clean_text(item) for item in episode_direction.get("avoid_patterns", []) if clean_text(item)],
    }


def _story_plans(stories: list[dict[str, Any]], story_drafts: dict[str, dict[str, Any]], scene_timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scene_counts = Counter(clean_text(scene.get("story_id", "")) for scene in scene_timeline)
    plans: list[dict[str, Any]] = []
    for story in stories:
        story_id = clean_text(story.get("story_id", ""))
        draft = story_drafts.get(story_id, {})
        identity = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
        plans.append(
            {
                "story_id": story_id,
                "story_title": clean_text(story.get("story_title", "")),
                "visual_strategy": clean_text(draft.get("visual_strategy", "")) or "Use source screenshots, logo moments, and kinetic type rather than cards.",
                "key_entities": dedupe([clean_text(identity.get("primary_entity", "")), *[clean_text(item) for item in draft.get("key_entities", [])]]),
                "planned_scene_count": scene_counts.get(story_id, 0),
            }
        )
    return plans


def _coverage_report(
    scene_timeline: list[dict[str, Any]],
    script_units: list[dict[str, Any]],
    total_duration: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    expected_units = {safe_int(unit.get("order"), index) for index, unit in enumerate(script_units, start=1)}
    covered_units: set[int] = set()
    durations = []
    gap_count = 0
    overlap_count = 0
    sorted_scenes = sorted(scene_timeline, key=lambda scene: safe_float(scene.get("start_seconds"), 0.0))
    previous_end: float | None = None
    for scene in sorted_scenes:
        covered_units.update(safe_int(unit, 0) for unit in scene.get("covered_unit_orders", []))
        duration = safe_float(scene.get("duration_seconds"), 0.0)
        durations.append(duration)
        start = safe_float(scene.get("start_seconds"), 0.0)
        end = safe_float(scene.get("end_seconds"), start)
        if previous_end is not None:
            if start - previous_end > 0.25:
                gap_count += 1
            if previous_end - start > 0.25:
                overlap_count += 1
        previous_end = end
    max_allowed = safe_float(config["scene_policy"].get("max_scene_seconds"), 14.0)
    long_scenes = [
        {"scene_id": scene.get("scene_id"), "duration_seconds": scene.get("duration_seconds")}
        for scene in scene_timeline
        if safe_float(scene.get("duration_seconds"), 0.0) > max_allowed + 0.01
    ]
    return {
        "total_duration_seconds": round(total_duration, 2),
        "expected_unit_count": len(expected_units),
        "covered_unit_count": len(covered_units & expected_units),
        "uncovered_unit_orders": sorted(expected_units - covered_units),
        "max_scene_duration_seconds": round(max(durations), 2) if durations else 0.0,
        "max_allowed_scene_seconds": max_allowed,
        "long_scenes": long_scenes,
        "gap_count": gap_count,
        "overlap_count": overlap_count,
        "timeline_start_seconds": round(safe_float(sorted_scenes[0].get("start_seconds"), 0.0), 2) if sorted_scenes else 0.0,
        "timeline_end_seconds": round(safe_float(sorted_scenes[-1].get("end_seconds"), 0.0), 2) if sorted_scenes else 0.0,
    }


def _check_scene_plan(visual_scene_plan: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    scenes = visual_scene_plan.get("scene_timeline", [])
    allowed = set(config["scene_policy"]["allowed_render_kinds"])
    if not scenes:
        errors.append("visual_scene_plan.scene_timeline is empty")
    if len(scenes) > int(config["scene_policy"]["max_scenes"]):
        errors.append("scene count exceeds scene_policy.max_scenes")
    old_kinds = [scene.get("render_kind") for scene in scenes if scene.get("render_kind") in OLD_CARD_RENDER_KINDS]
    if old_kinds:
        errors.append(f"old card render kinds are not allowed: {sorted(set(old_kinds))}")
    unsupported = [scene.get("render_kind") for scene in scenes if scene.get("render_kind") not in allowed]
    if unsupported:
        errors.append(f"unsupported render kinds: {sorted(set(unsupported))}")
    coverage = visual_scene_plan.get("coverage", {})
    if coverage.get("uncovered_unit_orders"):
        errors.append(f"scene timeline does not cover script units: {coverage['uncovered_unit_orders'][:20]}")
    if coverage.get("long_scenes"):
        errors.append(f"scene timeline has scenes over max_scene_seconds: {coverage['long_scenes'][:10]}")
    if safe_int(coverage.get("gap_count"), 0) > 0:
        errors.append(f"scene timeline has {coverage.get('gap_count')} time gaps")
    if safe_int(coverage.get("overlap_count"), 0) > 0:
        errors.append(f"scene timeline has {coverage.get('overlap_count')} time overlaps")
    source_scenes = [scene for scene in scenes if scene.get("render_kind") == "source_article_scene"]
    for scene in source_scenes:
        payload = scene.get("payload", {})
        if not clean_text(payload.get("url", "")).startswith(("http://", "https://")):
            errors.append(f"{scene.get('scene_id')} source_article_scene is missing a valid url")
        if not clean_text(payload.get("source_record_key", "")):
            errors.append(f"{scene.get('scene_id')} source_article_scene is missing source_record_key")
    kind_counts = Counter(scene.get("render_kind", "") for scene in scenes)
    if scenes:
        dominant_kind, dominant_count = kind_counts.most_common(1)[0]
        if dominant_count / len(scenes) > 0.72:
            warnings.append(f"Visual mix may be repetitive: {dominant_kind} is {dominant_count}/{len(scenes)} scenes.")
    if not any(scene.get("render_kind") == "logo_reveal_scene" for scene in scenes):
        warnings.append("No logo_reveal_scene was planned.")
    if not any(scene.get("render_kind") == "kinetic_type_scene" for scene in scenes):
        warnings.append("No kinetic_type_scene was planned.")
    return {"passed": not errors, "errors": errors, "warnings": warnings}


def _build_summary(visual_scene_plan: dict[str, Any], llm_calls: list[dict[str, Any]], failure_reason: str) -> dict[str, Any]:
    scenes = visual_scene_plan.get("scene_timeline", [])
    kinds = [scene.get("render_kind", "") for scene in scenes]
    coverage = visual_scene_plan.get("coverage", {})
    return {
        "script_word_count": safe_int(visual_scene_plan.get("source_script", {}).get("word_count"), 0),
        "voiceover_duration_seconds": safe_float(visual_scene_plan.get("audio_timeline", {}).get("duration_seconds"), 0.0),
        "story_count": len(visual_scene_plan.get("story_plans", [])),
        "story_section_count": len([section for section in visual_scene_plan.get("story_sections", []) if section.get("section_type") == "story"]),
        "scene_count": len(scenes),
        "source_article_scene_count": kinds.count("source_article_scene"),
        "logo_reveal_scene_count": kinds.count("logo_reveal_scene"),
        "kinetic_type_scene_count": kinds.count("kinetic_type_scene"),
        "llm_call_count": len(llm_calls),
        "render_kind_counts": counter_dict(kinds),
        "coverage": coverage,
        "failure_reason": failure_reason,
    }


def _failed_response(
    *,
    run_id: str,
    generated_at: str,
    selected_format: str,
    reason: str,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    visual_scene_plan = {
        "package_type": PACKAGE_TYPE,
        "selected_format": selected_format,
        "planning_strategy": "episode_director_plus_per_story",
        "run_id": run_id,
        "generated_at": generated_at,
        "episode_style": {},
        "story_plans": [],
        "story_sections": [],
        "scene_timeline": [],
        "asset_manifest": {"asset_request_count": 0, "asset_type_counts": {}, "requests": []},
        "coverage": {},
        "planning_calls": [],
        "checks": {"passed": False, "errors": [reason], "warnings": []},
    }
    response = VisualPlannerResponse(
        status="failed",
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": selected_format,
            "visual_scene_plan": visual_scene_plan,
        },
        summary=_build_summary(visual_scene_plan, llm_calls, reason),
        handoff={
            "ready_for_visual_asset_resolution": False,
            "next_module": NEXT_MODULE,
            "selected_format": selected_format,
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _upstream_failure_reason(video_packaging, selected_format: str, video_packet: dict[str, Any]) -> str:
    if video_packaging.status and video_packaging.status != "ok":
        return "input.video_packaging.status must be ok"
    if selected_format != SUPPORTED_FORMAT:
        return f"visual planning currently supports only selected_format={SUPPORTED_FORMAT}"
    if not isinstance(video_packet, dict) or not video_packet:
        return "input.video_packaging.data.video_packet is missing"
    if not _selected_stories(video_packet):
        return "video_packet.stories is missing or empty"
    return ""


def _extract_script_text(request: VisualPlannerRequest) -> str:
    if request.input.script_generation is not None:
        package = request.input.script_generation.data.script_package
        return str(package.get("full_script", "") or "").strip()
    return str(request.input.script_text or "").strip()


def _build_script_units(
    *,
    script_text: str,
    voiceover_package: dict[str, Any] | None,
    video_packet: dict[str, Any],
    words_per_minute: int,
) -> list[dict[str, Any]]:
    chunks = voiceover_chunks(voiceover_package)
    if chunks:
        return chunks
    return split_script_units(
        script_text,
        words_per_minute=words_per_minute,
        target_duration_seconds=safe_float(video_packet.get("target_duration_seconds"), None),
    )


def _audio_context(voiceover_package: dict[str, Any] | None, total_duration: float) -> dict[str, Any]:
    package = normalize_voiceover_package(voiceover_package)
    if not package:
        return {
            "timing_source": "estimated_from_script",
            "duration_seconds": round(total_duration, 2),
            "chunk_count": 0,
            "audio_path": "",
        }
    audio = package.get("audio") if isinstance(package.get("audio"), dict) else {}
    chunks = voiceover_chunks(package)
    return {
        "timing_source": "voiceover_chunks" if chunks else "voiceover_package",
        "duration_seconds": round(safe_float(audio.get("duration_seconds"), total_duration), 2),
        "chunk_count": len(chunks),
        "audio_path": clean_text(audio.get("full_audio_path") or audio.get("audio_path", "")),
    }


def _total_duration(script_units: list[dict[str, Any]], voiceover_package: dict[str, Any] | None, video_packet: dict[str, Any]) -> float:
    package = normalize_voiceover_package(voiceover_package)
    if package and isinstance(package.get("audio"), dict):
        duration = safe_float(package["audio"].get("duration_seconds"), 0.0)
        if duration > 0:
            return duration
    if script_units:
        return safe_float(script_units[-1].get("end_seconds"), 0.0)
    return safe_float(video_packet.get("target_duration_seconds"), 0.0)


def _video_packet_summary(video_packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_type": clean_text(video_packet.get("packet_type", "")),
        "target_duration_seconds": video_packet.get("target_duration_seconds"),
        "intro_seconds": video_packet.get("intro_seconds"),
        "closing_seconds": video_packet.get("closing_seconds"),
        "story_count": len(video_packet.get("stories", [])),
        "selected_story_ids": video_packet.get("selected_story_ids", []),
    }


def _story_section_summary(story_sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "section_id": section.get("section_id"),
            "section_type": section.get("section_type"),
            "story_id": section.get("story_id"),
            "story_title": section.get("story_title"),
            "start_unit_order": section.get("start_unit_order"),
            "end_unit_order": section.get("end_unit_order"),
            "duration_seconds": section.get("duration_seconds"),
            "assignment_method": section.get("assignment_method"),
        }
        for section in story_sections
    ]


def _section_for_prompt(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "section_id": section.get("section_id"),
        "section_type": section.get("section_type"),
        "story_id": section.get("story_id"),
        "story_title": section.get("story_title"),
        "start_unit_order": section.get("start_unit_order"),
        "end_unit_order": section.get("end_unit_order"),
        "unit_orders": section.get("unit_orders", []),
        "start_seconds": section.get("start_seconds"),
        "end_seconds": section.get("end_seconds"),
        "duration_seconds": section.get("duration_seconds"),
        "text": short_text(section.get("text", ""), 900),
        "assignment_method": section.get("assignment_method"),
    }


def _script_units_for_story_prompt(script_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "unit_id": unit.get("unit_id"),
            "order": unit.get("order"),
            "start_seconds": unit.get("start_seconds"),
            "end_seconds": unit.get("end_seconds"),
            "duration_seconds": unit.get("duration_seconds"),
            "text": short_text(unit.get("text", ""), 320),
        }
        for unit in script_units
    ]


def _sections_for_output(story_sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for section in story_sections:
        item = {key: value for key, value in section.items() if key != "script_units"}
        item["script_unit_count"] = len(section.get("script_units", []))
        output.append(item)
    return output


def _planner_warnings(story_drafts: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for story_id, draft in story_drafts.items():
        for item in draft.get("warnings", []):
            cleaned = clean_text(item)
            if cleaned:
                warnings.append(f"{story_id}: {cleaned}")
    return warnings


def _planning_calls_from_llm_calls(llm_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls = []
    for index, call in enumerate(llm_calls, start=1):
        calls.append(
            {
                "call_order": index,
                "module_name": call.get("module_name"),
                "model": call.get("model"),
                "metadata": call.get("metadata", {}),
                "duration_seconds": call.get("duration_seconds"),
                "parse_error": call.get("parse_error", ""),
            }
        )
    return calls


def _script_excerpt(script_units: list[dict[str, Any]], start_unit: int, end_unit: int) -> str:
    parts = [unit["text"] for unit in script_units[start_unit - 1 : end_unit] if clean_text(unit.get("text", ""))]
    return short_text(" ".join(parts), 420)


def _section_unit_excerpt(section: dict[str, Any], start_unit: int, end_unit: int) -> str:
    units = section.get("script_units", [])
    parts = [
        unit.get("text", "")
        for unit in units
        if start_unit <= safe_int(unit.get("order"), 0) <= end_unit
    ]
    return short_text(" ".join(parts), 420)


def _unit_midpoint(unit: dict[str, Any]) -> float:
    start = safe_float(unit.get("start_seconds"), 0.0)
    end = safe_float(unit.get("end_seconds"), start)
    return start + (end - start) / 2


def _primary_entity_for_story(story_id: str, source_index: dict[str, Any]) -> str:
    identity = source_index["story_identity_by_id"].get(story_id, {})
    return clean_text(identity.get("primary_entity") or identity.get("owning_org") or identity.get("product_or_project", ""))


def _story_signature(story: dict[str, Any]) -> dict[str, Any]:
    identity = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
    strong_phrases = [
        clean_text(story.get("story_title", "")),
        clean_text(identity.get("primary_entity", "")),
        clean_text(identity.get("product_or_project", "")),
    ]
    phrases = [
        *strong_phrases,
        clean_text(identity.get("owning_org", "")),
        clean_text(identity.get("canonical_story_key", "")),
    ]
    for record in story.get("records", []):
        if isinstance(record, dict):
            phrases.append(clean_text(record.get("title", "")))
    words = set()
    phrase_values = []
    for phrase in phrases:
        if not phrase:
            continue
        phrase_values.append(phrase.lower())
        words.update(meaningful_words(phrase))
    strong_values = [phrase.lower() for phrase in strong_phrases if phrase]
    return {"phrases": phrase_values, "strong_phrases": strong_values, "words": words}


def _signature_score(text_lower: str, signature: dict[str, Any]) -> int:
    score = 0
    for phrase in signature.get("phrases", []):
        if phrase and phrase in text_lower:
            score += 3
    words = set(meaningful_words(text_lower))
    score += len(words & set(signature.get("words", set())))
    return score


def _story_ids_equivalent(left: str, right: str) -> bool:
    normalize = lambda value: re.sub(r"[^a-z0-9]+", "_", clean_text(value).lower()).strip("_")
    return normalize(left) == normalize(right)


def _is_story_transition(text: str) -> bool:
    lower = clean_text(text).lower()
    return lower.startswith(
        (
            "next,",
            "next ",
            "now to",
            "now,",
            "staying with",
            "finally,",
            "finally ",
            "anthropic also",
            "google also",
        )
    )


def _has_strong_story_match(text_lower: str, signature: dict[str, Any], score: int) -> bool:
    del score
    for phrase in signature.get("strong_phrases", []):
        phrase_words = meaningful_words(phrase)
        if phrase and phrase in text_lower and len(phrase_words) >= 2:
            return True
    return False


def _short_phrase(text: str) -> str:
    words = clean_text(text).replace(":", " ").split()
    if not words:
        return "AI NEWS SHIFT"
    return " ".join(words[:7]).strip(" ,.;:") or "AI NEWS SHIFT"


def _default_visual_intent(render_kind: str) -> str:
    if render_kind == "source_article_scene":
        return "Show the source article as visual proof for the narration beat."
    if render_kind == "logo_reveal_scene":
        return "Introduce or contrast the entity with a logo-driven motion moment."
    return "Turn the key narration phrase into kinetic on-screen text."
