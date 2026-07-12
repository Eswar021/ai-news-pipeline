from __future__ import annotations

from collections import Counter
import json
import math
import re
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.pipeline.contracts import (
    build_artifact_provenance,
    build_text_script_provenance,
    require_matching_run_id,
    require_parent_fingerprint,
    validate_artifact_provenance,
    validate_script_provenance,
    visual_plan_artifact_payload,
    voiceover_artifact_payload,
)

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

RenderKind = Literal[
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
]
CropStrategy = Literal["article_viewport", "headline_then_body", "target_text_focus"]
SourceMotionStyle = Literal["slow_push", "highlight_scan", "browser_zoom"]
LogoMotionStyle = Literal["pop_reveal", "slide_stack", "spotlight"]
KineticAnimationStyle = Literal["typewriter", "word_snap", "highlight_sweep"]
BulletBuildStyle = Literal["numbered_build", "stack_reveal", "pulse_checklist"]
EntityCompareStyle = Literal["versus", "matrix", "orbit_stack"]
RecapMotionStyle = Literal["story_rhythm", "rapid_stack", "final_takeaway"]
TrendDirection = Literal["rising", "falling", "volatile", "pressure_building", "flat_then_jump"]
FlowDirection = Literal["left_to_right", "top_to_bottom", "radial", "loop"]
BackgroundMotif = Literal["newsroom_grid", "device_glow", "abstract_ai"]
TransitionMotionStyle = Literal["signal_wipe", "radar_ping", "glitch_snap", "orbit_sweep"]

CLOSING_RE = re.compile(r"\b(today'?s roundup|so today|the ai race is no longer|thanks for watching|that is the bigger shift)\b", re.IGNORECASE)
METRIC_RE = re.compile(r"(\$?\d[\d,]*(?:\.\d+)?\s?(?:%|x|×|b|bn|billion|m|million|k|thousand|hours?|days?|weeks?|months?|years?|tokens?|parameters?|gb|tb|fp\d|bit|bits?)?)", re.IGNORECASE)
TREND_RE = re.compile(r"\b(skyrocket|surge|jump|rise|rising|increase|accelerat|momentum|pressure|race|heating up|fall|decline|drop|behind|volatile|boom|growth|faster|slower)\b", re.IGNORECASE)
FLOW_RE = re.compile(r"\b(sdk|api|pipeline|workflow|framework|integration|connect|route|through|from .+ to |model|agent|cloud|on-device|device|app|developer|training|deploy|layers?)\b", re.IGNORECASE)
TEXT_LIKE_RENDER_KINDS = {"kinetic_type_scene", "bullet_build_scene", "recap_sequence_scene"}
SOURCE_BACKED_RENDER_KINDS = {"source_article_scene", "quote_or_claim_highlight_scene"}
GRAPHIC_RENDER_KINDS = {
    "context_image_scene",
    "broll_video_scene",
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
    "entity_compare_scene",
    "logo_reveal_scene",
}
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


class MetricDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    value: str = ""
    unit: str = ""
    context: str = ""


class ChartItemDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = 0
    label: str = ""
    name: str = ""
    value: str = ""
    display_value: str = ""
    start_value: str = ""
    end_value: str = ""
    detail: str = ""
    context: str = ""


class BenchmarkDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    name: str = ""
    before: str = ""
    after: str = ""
    delta: str = ""
    unit: str = ""
    context: str = ""
    detail: str = ""


class MatrixRowDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    name: str = ""
    speed: str = ""
    cost: str = ""
    context_window: str = ""
    multimodal: str = ""
    tooling: str = ""
    detail: str = ""


class TimelineEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    date: str = ""
    detail: str = ""
    importance: str = ""


class DocumentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    source: str = ""
    document_type: str = ""
    detail: str = ""
    status: str = ""


class InterfacePanelDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    detail: str = ""
    items: list[str] = Field(default_factory=list)


class MapNodeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    label: str = ""
    name: str = ""
    role: str = ""


class MapEdgeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = ""
    target: str = ""
    label: str = ""


class FlowStepDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    name: str = ""
    detail: str = ""
    description: str = ""


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
    search_queries: list[str] = Field(default_factory=list)
    must_show: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    shot_style: str = "editorial_wide"
    media_overlay_headline: str = ""
    media_motion_style: str = "slow_push"
    show_media_overlay: bool = False
    entities: list[str] = Field(default_factory=list)
    primary_entity: str = ""
    logo_strategy: str = "simple_icons_then_favicon_then_text"
    companion_text: str = ""
    logo_motion_style: LogoMotionStyle = "pop_reveal"
    phrases: list[str] = Field(default_factory=list)
    emphasis_words: list[str] = Field(default_factory=list)
    animation_style: KineticAnimationStyle = "typewriter"
    background_motif: BackgroundMotif = "newsroom_grid"
    headline: str = ""
    points: list[str] = Field(default_factory=list)
    build_style: BulletBuildStyle = "numbered_build"
    claim_text: str = ""
    supporting_text: str = ""
    comparison_axis: str = ""
    entity_notes: list[str] = Field(default_factory=list)
    motion_style: str = ""
    comparison_motion_style: EntityCompareStyle = "versus"
    recap_items: list[str] = Field(default_factory=list)
    final_takeaway: str = ""
    recap_motion_style: RecapMotionStyle = "story_rhythm"
    metrics: list[MetricDraft] = Field(default_factory=list)
    metric_label: str = ""
    metric_value: str = ""
    metric_unit: str = ""
    metric_context: str = ""
    emphasis_label: str = ""
    data_motion_style: str = "count_up"
    trend_direction: TrendDirection = "rising"
    y_axis_label: str = ""
    x_axis_label: str = ""
    annotations: list[str] = Field(default_factory=list)
    trend_motion_style: str = "draw_line"
    bars: list[ChartItemDraft] = Field(default_factory=list)
    items: list[ChartItemDraft] = Field(default_factory=list)
    benchmarks: list[BenchmarkDraft] = Field(default_factory=list)
    unit: str = ""
    leader_label: str = ""
    winner_label: str = ""
    chart_motion_style: str = "grow_bars"
    race_motion_style: str = "rank_shift"
    ranked_motion_style: str = "staggered_rank"
    benchmark_motion_style: str = "delta_snap"
    nodes: list[MapNodeDraft] = Field(default_factory=list)
    edges: list[MapEdgeDraft] = Field(default_factory=list)
    focus_entity: str = ""
    map_motion_style: str = "pulse_connections"
    steps: list[FlowStepDraft] = Field(default_factory=list)
    flow_direction: FlowDirection = "left_to_right"
    active_step_label: str = ""
    flow_motion_style: str = "packet_flow"
    focus_step_label: str = ""
    zoom_note: str = ""
    zoom_motion_style: str = "focus_zoom"
    walkthrough_steps: list[FlowStepDraft] = Field(default_factory=list)
    focus_text: str = ""
    browser_motion_style: str = "guided_scroll"
    root_label: str = ""
    branches: list[FlowStepDraft] = Field(default_factory=list)
    selected_path_label: str = ""
    decision_motion_style: str = "branch_glow"
    columns: list[str] = Field(default_factory=list)
    rows: list[MatrixRowDraft] = Field(default_factory=list)
    highlight_cell: str = ""
    matrix_motion_style: str = "cell_scan"
    events: list[TimelineEventDraft] = Field(default_factory=list)
    focus_event_label: str = ""
    timeline_motion_style: str = "event_zoom"
    documents: list[DocumentDraft] = Field(default_factory=list)
    focus_document_label: str = ""
    document_motion_style: str = "parallax_stack"
    signals: list[ChartItemDraft] = Field(default_factory=list)
    scan_label: str = ""
    radar_motion_style: str = "radar_sweep"
    before: InterfacePanelDraft = Field(default_factory=InterfacePanelDraft)
    after: InterfacePanelDraft = Field(default_factory=InterfacePanelDraft)
    transformation_label: str = ""
    transform_motion_style: str = "panel_morph"
    transition_label: str = ""
    transition_subtitle: str = ""
    stinger_motion_style: TransitionMotionStyle = "signal_wipe"
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

    @field_validator("scene_timeline")
    @classmethod
    def scene_timeline_must_not_be_empty(cls, value: list[SceneDraft]) -> list[SceneDraft]:
        if not value:
            raise ValueError("scene_timeline must contain at least one scene")
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

    require_matching_run_id(run_id, video_packaging.data.run_id, "video_packaging")
    if request.input.script_generation is not None and request.input.script_generation.status != "ok":
        raise ValueError("input.script_generation.status must be ok")

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
    script_provenance = _resolve_script_provenance(request, script_text, script_source)
    voiceover_provenance = _validate_voiceover_for_script(
        voiceover_package,
        run_id=run_id,
        script_provenance=script_provenance,
        script_sections=_script_generation_sections(request),
    )
    script_units = _build_script_units(
        script_text=script_text,
        voiceover_package=voiceover_package,
        script_sections=_script_generation_sections(request),
        words_per_minute=int(config["diagnostic_words_per_minute"]),
    )
    script_units = _attach_script_beat_context(script_units, request)
    stories = _selected_stories(video_packet)
    source_index = _build_source_index(stories)
    script_asset_hints = _script_story_asset_hints(request)
    story_sections = _build_story_sections(
        request=request,
        script_text=script_text,
        script_units=script_units,
        stories=stories,
    )
    story_ranges = _story_time_ranges(story_sections, stories)

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
        script_asset_hints=script_asset_hints,
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
        script_provenance=script_provenance,
        voiceover_provenance=voiceover_provenance,
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
            "ready_for_visual_media_discovery": status == "ok",
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
    script_asset_hints: dict[str, dict[str, Any]],
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
            "available_story_assets": script_asset_hints.get(story_id, {}),
            "story_section": _section_for_prompt(section),
            "script_units": _script_units_for_story_prompt(section.get("script_units", [])),
            "allowed_render_kinds": config["scene_policy"]["allowed_render_kinds"],
            "banned_visual_language": sorted(OLD_CARD_RENDER_KINDS),
            "required_behavior": {
                "plan_only_this_story": True,
                "use_only_this_story_records": True,
                "use_absolute_start_unit_order_values_from_script_units": True,
                "treat_beat_id_and_visual_brief_as_authoritative_context": True,
                "do_not_author_seconds_or_retime_narration": True,
                "first_story_title_beat_is_inserted_deterministically": True,
                "do_not_create_title_timeline_entity_recap_or_fallback_cards": True,
                "prefer_source_article_scene_for_source_specific_claims": True,
                "prefer_context_image_scene_for_concrete_physical_subjects": True,
                "prefer_broll_video_scene_for_concrete_motion_or_environment": True,
                "prefer_logo_reveal_scene_for_entity_introductions": True,
                "prefer_kinetic_type_scene_for_punchy_or_transitional_phrases": True,
                "prefer_bar_chart_scene_for_numeric_comparisons": True,
                "prefer_bar_race_scene_for_competitive_momentum_or_before_after_rank_shifts": True,
                "prefer_ranked_list_scene_for_explicit_top_ranked_or_ordered_implications": True,
                "prefer_benchmark_delta_scene_for_before_after_speed_cost_quality_or_benchmark_changes": True,
                "prefer_process_zoom_scene_when_one_workflow_step_should_be_the_visual_hero": True,
                "prefer_transition_stinger_scene_for_short_story_to_story_bumpers": True,
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
                "fallback_used": True,
                "fallback_reason": f"{type(exc).__name__}: {exc}",
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
                    "fallback_used": True,
                    "fallback_reason": f"returned story_id {returned_story_id!r}; expected {story_id!r}",
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
    script_provenance: dict[str, Any],
    voiceover_provenance: dict[str, Any] | None,
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
    visual_scene_plan = {
        "package_type": PACKAGE_TYPE,
        "selected_format": SUPPORTED_FORMAT,
        "planning_strategy": "episode_director_plus_per_story",
        "run_id": run_id,
        "generated_at": generated_at,
        "episode_style": _episode_style(episode_direction, config),
        "story_plans": _story_plans(stories, story_drafts, scene_timeline),
        "story_sections": _sections_for_output(story_sections),
        "visual_beat_map": _visual_beat_map(scene_timeline),
        "scene_timeline": scene_timeline,
        "asset_manifest": asset_manifest,
        "coverage": coverage,
        "planning_calls": _planning_calls_from_llm_calls(llm_calls),
        "source_script": {
            "script_source": script_source or "script_generation",
            "word_count": count_words(script_text),
            "script_fingerprint": script_provenance["script_fingerprint"],
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
    parents = {"script": script_provenance["script_fingerprint"]}
    if voiceover_provenance:
        parents["voiceover"] = voiceover_provenance["voiceover_fingerprint"]
    visual_scene_plan["provenance"] = build_artifact_provenance(
        artifact_type="visual_plan",
        run_id=run_id,
        parents=parents,
        script_source=script_provenance.get("script_source", ""),
        payload=visual_plan_artifact_payload(visual_scene_plan),
    )
    return visual_scene_plan


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
        if render_kind in {"source_article_scene", "quote_or_claim_highlight_scene"} and not url:
            render_kind = "logo_reveal_scene" if _primary_entity_for_story(story_id, source_index) else "bullet_build_scene"
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
    title_card = section.get("title_card") if isinstance(section.get("title_card"), dict) else None
    if not title_card:
        return candidates

    remaining: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate = dict(candidate)
        candidate_start = safe_int(candidate.get("start_unit_order"), section_start)
        candidate_end = safe_int(candidate.get("end_unit_order"), candidate_start)
        if candidate_start <= section_start:
            candidate_start = section_start + 1
        if candidate_start <= candidate_end and candidate_start <= section_end:
            candidate["start_unit_order"] = candidate_start
            remaining.append(candidate)

    display_title = clean_text(title_card.get("display_title")) or clean_text(story.get("story_title", ""))
    subtitle = clean_text(title_card.get("subtitle"))
    title_kind = "transition_stinger_scene" if "transition_stinger_scene" in set(policy["allowed_render_kinds"]) else "logo_reveal_scene"
    title_payload = {
        "transition_label": short_text(display_title, 62),
        "subtitle": short_text(subtitle or clean_text((story.get("story_identity") or {}).get("why_it_matters", "")), 82),
        "background_motif": "newsroom_grid",
        "motion_style": "signal_wipe",
        "eyebrow": f"STORY {safe_int((story.get('video_segment') or {}).get('segment_order'), 1)}",
        "voice_behavior": "continue",
        "configured_title_seconds": safe_float(title_card.get("duration_seconds"), 2.8),
    }
    if title_kind == "logo_reveal_scene":
        primary_entity = _primary_entity_for_story(story_id, source_index)
        title_payload = {
            "entities": [primary_entity] if primary_entity else [],
            "primary_entity": primary_entity,
            "logo_strategy": "simple_icons_then_favicon_then_text",
            "companion_text": short_text(display_title, 62),
            "motion_style": "spotlight",
            "voice_behavior": "continue",
        }
    title_candidate = {
        "story_id": story_id,
        "story_title": clean_text(story.get("story_title", "")),
        "section_type": "story",
        "start_unit_order": section_start,
        "end_unit_order": section_start,
        "render_kind": title_kind,
        "script_excerpt": _section_unit_excerpt(section, section_start, section_start),
        "visual_intent": "Introduce the story with a moving title while narration continues.",
        "payload": title_payload,
        "source_record_keys": [],
        "source_urls": [],
        "reason": "Deterministic story-title interstitial anchored to the canonical transition beat.",
    }
    return [title_candidate, *remaining]


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
            policy=policy,
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
    if not policy.get("compact_per_chunk_scenes", True):
        return _fixed_time_slices(start_unit, end_unit, script_units, policy)

    max_seconds = max(1.0, safe_float(policy.get("max_scene_seconds"), 14.0))
    min_seconds = min(max_seconds, max(safe_float(policy.get("min_scene_seconds"), 3.0), safe_float(policy.get("semantic_min_scene_seconds"), 5.0)))
    target_seconds = min(max_seconds, max(min_seconds, safe_float(policy.get("semantic_target_scene_seconds"), 9.0)))
    max_units = max(1, safe_int(policy.get("semantic_max_units_per_scene"), 4))
    range_units = script_units[start_unit - 1 : end_unit]
    if not range_units:
        return []
    if any(
        safe_float(unit.get("end_seconds"), 0.0) - safe_float(unit.get("start_seconds"), 0.0) > max_seconds + 0.01
        for unit in range_units
    ):
        return _fixed_time_slices(start_unit, end_unit, script_units, policy)
    slices: list[dict[str, Any]] = []
    current_units: list[dict[str, Any]] = []
    current_start = safe_float(range_units[0].get("start_seconds"), 0.0)

    def close_current() -> None:
        nonlocal current_units, current_start
        if not current_units:
            return
        unit_orders = [safe_int(unit.get("order"), start_unit) for unit in current_units]
        end_seconds = safe_float(current_units[-1].get("end_seconds"), current_start)
        slices.append(
            {
                "start_unit_order": min(unit_orders),
                "end_unit_order": max(unit_orders),
                "unit_orders": unit_orders,
                "start_seconds": round(current_start, 2),
                "end_seconds": round(end_seconds, 2),
            }
        )
        current_units = []

    for index, unit in enumerate(range_units):
        if not current_units:
            current_start = safe_float(unit.get("start_seconds"), 0.0)
        else:
            candidate_end = safe_float(unit.get("end_seconds"), current_start)
            if candidate_end - current_start > max_seconds + 0.01:
                close_current()
                current_start = safe_float(unit.get("start_seconds"), candidate_end)
        current_units.append(unit)
        current_end = safe_float(unit.get("end_seconds"), current_start)
        duration = max(0.0, current_end - current_start)
        next_unit = range_units[index + 1] if index + 1 < len(range_units) else None
        should_close = False
        if duration >= max_seconds - 0.01:
            should_close = True
        elif len(current_units) >= max_units and duration >= min_seconds:
            should_close = True
        elif duration >= target_seconds and _semantic_break_after(unit, next_unit):
            should_close = True
        elif next_unit is None:
            should_close = True
        elif duration >= min_seconds and _starts_new_visual_thought(next_unit):
            should_close = True
        if should_close:
            close_current()
    return slices


def _fixed_time_slices(
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
    total_duration = max(0.0, section_end - section_start)
    slice_count = max(1, math.ceil(total_duration / max_seconds))
    balanced_duration = total_duration / slice_count if slice_count else total_duration
    cursor = section_start
    for slice_index in range(slice_count):
        slice_end = section_end if slice_index == slice_count - 1 else min(section_end, cursor + balanced_duration)
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


def _semantic_break_after(unit: dict[str, Any], next_unit: dict[str, Any] | None) -> bool:
    text = clean_text(unit.get("text", ""))
    if not next_unit:
        return True
    if re.search(r"[.!?][\"')\]]?$", text):
        return True
    return _starts_new_visual_thought(next_unit)


def _starts_new_visual_thought(unit: dict[str, Any]) -> bool:
    lower = clean_text(unit.get("text", "")).lower()
    return lower.startswith(
        (
            "which brings",
            "which raises",
            "and then",
            "now to",
            "now,",
            "finally",
            "the catch",
            "the twist",
            "the lesson",
            "so ",
            "here's",
        )
    )


def _visual_beats_for_slice(unit_slice: dict[str, Any], script_units: list[dict[str, Any]], scene_start_seconds: float) -> list[dict[str, Any]]:
    orders = {safe_int(order, 0) for order in unit_slice.get("unit_orders", [])}
    beats: list[dict[str, Any]] = []
    for unit in script_units:
        order = safe_int(unit.get("order"), 0)
        if order not in orders:
            continue
        start = safe_float(unit.get("start_seconds"), scene_start_seconds)
        end = safe_float(unit.get("end_seconds"), start)
        text = clean_text(unit.get("text", ""))
        if not text:
            continue
        beats.append(
            {
                "unit_order": order,
                "beat_id": clean_text(unit.get("beat_id", "")),
                "beat_type": clean_text(unit.get("beat_type", "")),
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "relative_start_seconds": round(max(0.0, start - scene_start_seconds), 2),
                "relative_end_seconds": round(max(0.0, end - scene_start_seconds), 2),
                "text": text,
                "visual_action": clean_text((unit.get("visual_brief") or {}).get("visual_intent", "")) or _visual_action_for_beat(text),
                "visual_brief": unit.get("visual_brief", {}),
                "source_record_keys": unit.get("source_record_keys", []),
                "emphasis_words": meaningful_words(text)[:4],
            }
        )
    return beats


def _visual_action_for_beat(text: str) -> str:
    if _excerpt_has_metric(text):
        return "emphasize_metric"
    if _excerpt_has_flow(text):
        return "advance_diagram_step"
    if _excerpt_has_decision_tree(text):
        return "highlight_decision_path"
    if _excerpt_has_signal_radar(text):
        return "scan_signal"
    return "reveal_point"


def _fallback_candidate_for_slice(
    *,
    section: dict[str, Any],
    story: dict[str, Any],
    unit_slice: dict[str, Any],
    script_units: list[dict[str, Any]],
    source_index: dict[str, Any],
    counts: Counter[str],
    group_index: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    del counts
    story_id = clean_text(section.get("story_id", ""))
    section_type = clean_text(section.get("section_type", ""))
    excerpt = _script_excerpt(script_units, unit_slice["start_unit_order"], unit_slice["end_unit_order"])
    covered_units = script_units[unit_slice["start_unit_order"] - 1 : unit_slice["end_unit_order"]]
    first_unit = covered_units[0] if covered_units else {}
    visual_brief = first_unit.get("visual_brief") if isinstance(first_unit.get("visual_brief"), dict) else {}
    visual_intent = clean_text(visual_brief.get("visual_intent", ""))
    hinted_keys = [
        clean_text(key)
        for unit in covered_units
        for key in (unit.get("source_record_keys") or [])
        if clean_text(key)
    ]
    first_key = (hinted_keys or source_index["record_keys_by_story"].get(story_id) or [""])[0]
    record = source_index["records_by_key"].get(first_key, {})
    url = clean_text(record.get("url", ""))
    primary_entity = _primary_entity_for_story(story_id, source_index)
    allowed = set(policy.get("allowed_render_kinds", []))
    if section_type == "closing":
        render_kind = "recap_sequence_scene" if "recap_sequence_scene" in allowed else "bullet_build_scene"
    elif section_type != "story":
        render_kind = "bullet_build_scene" if "bullet_build_scene" in allowed else "kinetic_type_scene"
    elif visual_intent in {"story_title", "transition"} and "transition_stinger_scene" in allowed:
        render_kind = "transition_stinger_scene"
    elif visual_intent == "source_proof" and url and "source_article_scene" in allowed:
        render_kind = "source_article_scene"
    elif visual_intent == "entity_intro" and primary_entity and "logo_reveal_scene" in allowed:
        render_kind = "logo_reveal_scene"
    elif visual_intent == "product_demo" and url and "browser_walkthrough_scene" in allowed:
        render_kind = "browser_walkthrough_scene"
    elif visual_intent == "metric_explainer" and "data_counter_scene" in allowed:
        render_kind = "data_counter_scene"
    elif visual_intent == "process_explainer" and "architecture_flow_scene" in allowed:
        render_kind = "architecture_flow_scene"
    elif visual_intent == "comparison" and "entity_compare_scene" in allowed:
        render_kind = "entity_compare_scene"
    elif visual_intent == "context_media" and "context_image_scene" in allowed:
        render_kind = "context_image_scene"
    elif visual_intent == "takeaway" and "kinetic_type_scene" in allowed:
        render_kind = "kinetic_type_scene"
    elif group_index == 1 and primary_entity:
        render_kind = "logo_reveal_scene"
    elif url and _excerpt_has_browser_context(excerpt) and "browser_walkthrough_scene" in allowed:
        render_kind = "browser_walkthrough_scene"
    elif _excerpt_has_interface_transform(excerpt) and "interface_transform_scene" in allowed:
        render_kind = "interface_transform_scene"
    elif _excerpt_has_decision_tree(excerpt) and "decision_tree_scene" in allowed:
        render_kind = "decision_tree_scene"
    elif _excerpt_has_capability_matrix(excerpt) and "capability_matrix_scene" in allowed:
        render_kind = "capability_matrix_scene"
    elif _excerpt_has_timeline_zoom(excerpt) and "timeline_zoom_scene" in allowed:
        render_kind = "timeline_zoom_scene"
    elif _excerpt_has_document_stack(excerpt) and "document_stack_scene" in allowed:
        render_kind = "document_stack_scene"
    elif _excerpt_has_signal_radar(excerpt) and "signal_radar_scene" in allowed:
        render_kind = "signal_radar_scene"
    elif _excerpt_has_benchmark_delta(excerpt) and "benchmark_delta_scene" in allowed:
        render_kind = "benchmark_delta_scene"
    elif _excerpt_has_ranking(excerpt) and "ranked_list_scene" in allowed:
        render_kind = "ranked_list_scene"
    elif _excerpt_has_race(excerpt) and "bar_race_scene" in allowed:
        render_kind = "bar_race_scene"
    elif _excerpt_has_metric_comparison(excerpt) and "bar_chart_scene" in allowed:
        render_kind = "bar_chart_scene"
    elif _excerpt_has_metric(excerpt) and "data_counter_scene" in allowed:
        render_kind = "data_counter_scene"
    elif _excerpt_has_trend(excerpt) and "trend_line_scene" in allowed:
        render_kind = "trend_line_scene"
    elif _excerpt_has_process_focus(excerpt) and "process_zoom_scene" in allowed:
        render_kind = "process_zoom_scene"
    elif _excerpt_has_flow(excerpt) and "architecture_flow_scene" in allowed:
        render_kind = "architecture_flow_scene"
    elif primary_entity and len(_entities_for_story(story_id, source_index, excerpt)) >= 2 and "ecosystem_map_scene" in allowed:
        render_kind = "ecosystem_map_scene"
    elif url and group_index % 4 == 2 and "quote_or_claim_highlight_scene" in allowed:
        render_kind = "quote_or_claim_highlight_scene"
    elif url and group_index % 4 == 0:
        render_kind = "source_article_scene"
    elif primary_entity and group_index % 4 == 3 and "entity_compare_scene" in allowed:
        render_kind = "entity_compare_scene"
    elif "bullet_build_scene" in allowed:
        render_kind = "bullet_build_scene"
    else:
        render_kind = "kinetic_type_scene"
    if render_kind not in allowed:
        render_kind = "kinetic_type_scene" if "kinetic_type_scene" in allowed else sorted(allowed)[0]
    source_required = render_kind in {"source_article_scene", "quote_or_claim_highlight_scene"}
    if source_required and not url:
        render_kind = "bullet_build_scene" if "bullet_build_scene" in allowed else "kinetic_type_scene"
    draft = {
        "render_kind": render_kind,
        "source_record_key": first_key,
        "url": url,
        "target_text": (record.get("screenshot_target_candidates") or [record.get("title", "")])[0] if record else "",
        "overlay_headline": clean_text(story.get("story_title", "")) or short_text(excerpt, 70),
        "highlight_phrases": [_short_phrase(excerpt)],
        "claim_text": _short_phrase(excerpt),
        "supporting_text": (record.get("screenshot_target_candidates") or [excerpt])[0] if record else excerpt,
        "primary_entity": primary_entity,
        "entities": [primary_entity] if primary_entity else [],
        "companion_text": clean_text(story.get("story_title", "")) or _short_phrase(excerpt),
        "phrases": [_short_phrase(excerpt)],
        "emphasis_words": meaningful_words(excerpt)[:4],
        "headline": _short_phrase(excerpt),
        "points": _points_from_text(excerpt, max_points=4, max_chars=62),
        "build_style": "numbered_build",
        "comparison_axis": "What changes",
        "entity_notes": _points_from_text(excerpt, max_points=3, max_chars=48),
        "comparison_motion_style": "orbit_stack",
        "recap_items": _points_from_text(excerpt, max_points=6, max_chars=58),
        "final_takeaway": _short_phrase(excerpt),
        "recap_motion_style": "story_rhythm",
        "metrics": _metrics_from_text(excerpt),
        "metric_label": _metric_label_from_text(excerpt),
        "metric_value": _metric_value_from_text(excerpt),
        "metric_unit": "",
        "metric_context": _short_phrase(excerpt),
        "emphasis_label": "Scale signal",
        "data_motion_style": "count_up",
        "trend_direction": _trend_direction_from_text(excerpt),
        "y_axis_label": "Momentum",
        "x_axis_label": "Time",
        "annotations": _points_from_text(excerpt, max_points=3, max_chars=42),
        "trend_motion_style": "draw_line",
        "bars": _bars_from_text(excerpt),
        "items": _ranked_items_from_text(excerpt),
        "benchmarks": _benchmarks_from_text(excerpt),
        "unit": "",
        "leader_label": "Momentum shift",
        "winner_label": "Biggest delta",
        "chart_motion_style": "grow_bars",
        "race_motion_style": "rank_shift",
        "ranked_motion_style": "staggered_rank",
        "benchmark_motion_style": "delta_snap",
        "nodes": _nodes_from_entities(_entities_for_story(story_id, source_index, excerpt)),
        "edges": _edges_from_entities(_entities_for_story(story_id, source_index, excerpt)),
        "focus_entity": primary_entity,
        "map_motion_style": "pulse_connections",
        "steps": _flow_steps_from_text(excerpt),
        "flow_direction": "left_to_right",
        "active_step_label": _short_phrase(excerpt),
        "flow_motion_style": "packet_flow",
        "focus_step_label": _focus_step_from_text(excerpt),
        "zoom_note": short_text(excerpt, 86),
        "zoom_motion_style": "focus_zoom",
        "walkthrough_steps": _flow_steps_from_text(excerpt),
        "focus_text": _short_phrase(excerpt),
        "browser_motion_style": "guided_scroll",
        "root_label": "Decision point",
        "branches": _decision_branches_from_text(excerpt),
        "selected_path_label": _short_phrase(excerpt),
        "decision_motion_style": "branch_glow",
        "columns": ["Speed", "Cost", "Context", "Tools"],
        "rows": _matrix_rows_from_text(excerpt),
        "highlight_cell": "Best fit",
        "matrix_motion_style": "cell_scan",
        "events": _timeline_events_from_text(excerpt),
        "focus_event_label": _short_phrase(excerpt),
        "timeline_motion_style": "event_zoom",
        "documents": _documents_from_story_source(story, record, excerpt),
        "focus_document_label": clean_text(record.get("title", "")) if record else _short_phrase(excerpt),
        "document_motion_style": "parallax_stack",
        "signals": _signals_from_text(excerpt),
        "scan_label": "Emerging signal",
        "radar_motion_style": "radar_sweep",
        "before": {"label": "Before", "detail": "manual workflow", "items": _points_from_text(excerpt, max_points=3, max_chars=34)},
        "after": {"label": "After", "detail": "AI-assisted workflow", "items": _flow_step_labels_from_text(excerpt)[:3]},
        "transformation_label": "workflow shift",
        "transform_motion_style": "panel_morph",
        "transition_label": clean_text(story.get("story_title", "")) or _short_phrase(excerpt),
        "transition_subtitle": clean_text(visual_brief.get("on_screen_text", "")) or _short_phrase(excerpt),
        "stinger_motion_style": "signal_wipe",
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
        "visual_intent": clean_text(visual_brief.get("purpose", "")) or _default_visual_intent(render_kind),
        "payload": payload,
        "source_record_keys": [source_record_key] if source_record_key else [],
        "source_urls": [source_url] if source_url else [],
        "reason": "Deterministic stitcher fallback for uncovered narration chunk.",
    }


def _scene_from_candidate_slice(candidate: dict[str, Any], unit_slice: dict[str, Any], script_units: list[dict[str, Any]]) -> dict[str, Any]:
    start_seconds = safe_float(unit_slice.get("start_seconds"), 0.0)
    end_seconds = safe_float(unit_slice.get("end_seconds"), start_seconds)
    payload = dict(candidate.get("payload", {})) if isinstance(candidate.get("payload"), dict) else {}
    beats = _visual_beats_for_slice(unit_slice, script_units, start_seconds)
    if beats:
        payload["beats"] = beats
        payload["beat_count"] = len(beats)
        payload.setdefault("covered_text", short_text(" ".join(beat["text"] for beat in beats if beat.get("text")), 320))
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
        "payload": payload,
        "source_record_keys": candidate.get("source_record_keys", []),
        "source_urls": candidate.get("source_urls", []),
        "reason": clean_text(candidate.get("reason", "")),
    }


def _finalize_scene_order(scenes: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = sorted(scenes, key=lambda scene: (safe_float(scene.get("start_seconds"), 0.0), safe_int(scene.get("script_unit_start"), 0)))
    max_scene_seconds = safe_float(policy.get("max_scene_seconds"), 14.0)
    _close_timeline_gaps(ordered, max_scene_seconds)
    ordered = _compact_scene_timeline(ordered, policy)
    ordered = _diversify_repetitive_runs(ordered, policy)
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
            if _is_story_title_interstitial(first) or _is_story_title_interstitial(second):
                continue
            if clean_text(first.get("section_type", "")) != clean_text(second.get("section_type", "")):
                continue
            if clean_text(first.get("story_id", "")) != clean_text(second.get("story_id", "")):
                continue
            combined = safe_float(second.get("end_seconds"), 0.0) - safe_float(first.get("start_seconds"), 0.0)
            if combined <= max_scene_seconds + 0.01 and (
                safe_float(first.get("duration_seconds"), 0.0) < min_scene_seconds
                or safe_float(second.get("duration_seconds"), 0.0) < min_scene_seconds
            ):
                merge_at(index)
                changed = True
                break

    if policy.get("compact_per_chunk_scenes", True):
        changed = True
        while changed:
            changed = False
            for index in range(len(compacted) - 1):
                if _should_merge_semantic_neighbors(compacted[index], compacted[index + 1], policy):
                    merge_at(index)
                    changed = True
                    break

    while len(compacted) > max_scenes:
        best_index: int | None = None
        best_score: tuple[int, float] | None = None
        for index in range(len(compacted) - 1):
            first = compacted[index]
            second = compacted[index + 1]
            if _is_story_title_interstitial(first) or _is_story_title_interstitial(second):
                continue
            if clean_text(first.get("section_type", "")) != clean_text(second.get("section_type", "")):
                continue
            if clean_text(first.get("story_id", "")) != clean_text(second.get("story_id", "")):
                continue
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


def _should_merge_semantic_neighbors(first: dict[str, Any], second: dict[str, Any], policy: dict[str, Any]) -> bool:
    if _is_story_title_interstitial(first) or _is_story_title_interstitial(second):
        return False
    if clean_text(first.get("story_id", "")) != clean_text(second.get("story_id", "")):
        return False
    if clean_text(first.get("section_type", "")) != clean_text(second.get("section_type", "")):
        return False
    first_kind = clean_text(first.get("render_kind", ""))
    second_kind = clean_text(second.get("render_kind", ""))
    if first_kind in SOURCE_BACKED_RENDER_KINDS or second_kind in SOURCE_BACKED_RENDER_KINDS:
        return False
    start = safe_float(first.get("start_seconds"), 0.0)
    end = safe_float(second.get("end_seconds"), start)
    combined = max(0.0, end - start)
    max_seconds = safe_float(policy.get("max_scene_seconds"), 14.0)
    target_seconds = min(max_seconds, max(safe_float(policy.get("semantic_min_scene_seconds"), 5.0), safe_float(policy.get("semantic_target_scene_seconds"), 9.0)))
    if combined > target_seconds + 0.01:
        return False
    first_units = set(safe_int(unit, 0) for unit in first.get("covered_unit_orders", []))
    second_units = set(safe_int(unit, 0) for unit in second.get("covered_unit_orders", []))
    if first_kind == second_kind and first_kind in TEXT_LIKE_RENDER_KINDS:
        return True
    if _scene_headline(first) and _scene_headline(first) == _scene_headline(second):
        return True
    if len(first_units) <= 1 and len(second_units) <= 1 and first_kind in TEXT_LIKE_RENDER_KINDS | GRAPHIC_RENDER_KINDS and second_kind in TEXT_LIKE_RENDER_KINDS | GRAPHIC_RENDER_KINDS:
        return True
    if safe_float(first.get("duration_seconds"), 0.0) < safe_float(policy.get("semantic_min_scene_seconds"), 5.0):
        return True
    if safe_float(second.get("duration_seconds"), 0.0) < safe_float(policy.get("semantic_min_scene_seconds"), 5.0):
        return True
    return False


def _is_story_title_interstitial(scene: dict[str, Any]) -> bool:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    return (
        clean_text(scene.get("render_kind", "")) == "transition_stinger_scene"
        and clean_text(payload.get("voice_behavior", "")) == "continue"
    )


def _scene_headline(scene: dict[str, Any]) -> str:
    payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
    for key in ("headline", "overlay_headline", "companion_text", "transition_label"):
        value = clean_text(payload.get(key, "")).lower()
        if value:
            return value
    return ""


def _diversify_repetitive_runs(scenes: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    max_same = max(1, safe_int(policy.get("max_consecutive_same_kind"), 2))
    allowed = set(policy.get("allowed_render_kinds", []))
    diversified: list[dict[str, Any]] = []
    previous_kind = ""
    run_length = 0
    for scene in scenes:
        current = dict(scene)
        kind = clean_text(current.get("render_kind", ""))
        if kind == previous_kind:
            run_length += 1
        else:
            previous_kind = kind
            run_length = 1
        if run_length > max_same:
            replacement = _replacement_kind_for_repetition(current, allowed)
            if replacement and replacement != kind:
                current = _adapt_scene_to_render_kind(current, replacement)
                kind = replacement
                previous_kind = kind
                run_length = 1
        diversified.append(current)
    return diversified


def _replacement_kind_for_repetition(scene: dict[str, Any], allowed: set[str]) -> str:
    kind = clean_text(scene.get("render_kind", ""))
    section_type = clean_text(scene.get("section_type", ""))
    script_excerpt = clean_text(scene.get("script_excerpt", ""))
    payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
    has_source = clean_text(payload.get("url", "")) or bool(scene.get("source_urls"))
    if section_type == "closing" and "recap_sequence_scene" in allowed and kind != "recap_sequence_scene":
        return "recap_sequence_scene"
    if kind == "kinetic_type_scene":
        if _excerpt_has_browser_context(script_excerpt) and "browser_walkthrough_scene" in allowed:
            return "browser_walkthrough_scene"
        if _excerpt_has_interface_transform(script_excerpt) and "interface_transform_scene" in allowed:
            return "interface_transform_scene"
        if _excerpt_has_decision_tree(script_excerpt) and "decision_tree_scene" in allowed:
            return "decision_tree_scene"
        if _excerpt_has_capability_matrix(script_excerpt) and "capability_matrix_scene" in allowed:
            return "capability_matrix_scene"
        if _excerpt_has_timeline_zoom(script_excerpt) and "timeline_zoom_scene" in allowed:
            return "timeline_zoom_scene"
        if _excerpt_has_document_stack(script_excerpt) and "document_stack_scene" in allowed:
            return "document_stack_scene"
        if _excerpt_has_signal_radar(script_excerpt) and "signal_radar_scene" in allowed:
            return "signal_radar_scene"
        if _excerpt_has_benchmark_delta(script_excerpt) and "benchmark_delta_scene" in allowed:
            return "benchmark_delta_scene"
        if _excerpt_has_metric_comparison(script_excerpt) and "bar_chart_scene" in allowed:
            return "bar_chart_scene"
        if _excerpt_has_ranking(script_excerpt) and "ranked_list_scene" in allowed:
            return "ranked_list_scene"
        if _excerpt_has_race(script_excerpt) and "bar_race_scene" in allowed:
            return "bar_race_scene"
        if _excerpt_has_metric(script_excerpt) and "data_counter_scene" in allowed:
            return "data_counter_scene"
        if _excerpt_has_trend(script_excerpt) and "trend_line_scene" in allowed:
            return "trend_line_scene"
        if _excerpt_has_process_focus(script_excerpt) and "process_zoom_scene" in allowed:
            return "process_zoom_scene"
        if _excerpt_has_flow(script_excerpt) and "architecture_flow_scene" in allowed:
            return "architecture_flow_scene"
        return "bullet_build_scene" if "bullet_build_scene" in allowed else kind
    if kind == "bullet_build_scene":
        if _excerpt_has_decision_tree(script_excerpt) and "decision_tree_scene" in allowed:
            return "decision_tree_scene"
        if _excerpt_has_capability_matrix(script_excerpt) and "capability_matrix_scene" in allowed:
            return "capability_matrix_scene"
        if _excerpt_has_ranking(script_excerpt) and "ranked_list_scene" in allowed:
            return "ranked_list_scene"
        if _excerpt_has_flow(script_excerpt) and "architecture_flow_scene" in allowed:
            return "architecture_flow_scene"
        if _excerpt_has_process_focus(script_excerpt) and "process_zoom_scene" in allowed:
            return "process_zoom_scene"
        if _excerpt_has_metric_comparison(script_excerpt) and "bar_chart_scene" in allowed:
            return "bar_chart_scene"
        if _excerpt_has_metric(script_excerpt) and "data_counter_scene" in allowed:
            return "data_counter_scene"
        return "trend_line_scene" if _excerpt_has_trend(script_excerpt) and "trend_line_scene" in allowed else "kinetic_type_scene" if "kinetic_type_scene" in allowed else kind
    if kind == "logo_reveal_scene":
        return "entity_compare_scene" if "entity_compare_scene" in allowed else "bullet_build_scene"
    if kind == "entity_compare_scene":
        return "logo_reveal_scene" if "logo_reveal_scene" in allowed else "bullet_build_scene"
    if kind == "data_counter_scene":
        if _excerpt_has_metric_comparison(script_excerpt) and "bar_chart_scene" in allowed:
            return "bar_chart_scene"
        if _excerpt_has_benchmark_delta(script_excerpt) and "benchmark_delta_scene" in allowed:
            return "benchmark_delta_scene"
        return "trend_line_scene" if "trend_line_scene" in allowed else "architecture_flow_scene" if "architecture_flow_scene" in allowed else "bullet_build_scene"
    if kind == "trend_line_scene":
        if _excerpt_has_race(script_excerpt) and "bar_race_scene" in allowed:
            return "bar_race_scene"
        return "data_counter_scene" if "data_counter_scene" in allowed and _excerpt_has_metric(script_excerpt) else "ecosystem_map_scene" if "ecosystem_map_scene" in allowed else "bullet_build_scene"
    if kind == "bar_chart_scene":
        return "benchmark_delta_scene" if "benchmark_delta_scene" in allowed and _excerpt_has_benchmark_delta(script_excerpt) else "data_counter_scene" if "data_counter_scene" in allowed else "trend_line_scene" if "trend_line_scene" in allowed else "bullet_build_scene"
    if kind == "bar_race_scene":
        return "trend_line_scene" if "trend_line_scene" in allowed else "ranked_list_scene" if "ranked_list_scene" in allowed else "bullet_build_scene"
    if kind == "ranked_list_scene":
        return "bar_chart_scene" if "bar_chart_scene" in allowed and _excerpt_has_metric_comparison(script_excerpt) else "entity_compare_scene" if "entity_compare_scene" in allowed else "bullet_build_scene"
    if kind == "benchmark_delta_scene":
        return "bar_chart_scene" if "bar_chart_scene" in allowed else "data_counter_scene" if "data_counter_scene" in allowed else "trend_line_scene" if "trend_line_scene" in allowed else "bullet_build_scene"
    if kind == "ecosystem_map_scene":
        return "architecture_flow_scene" if "architecture_flow_scene" in allowed else "entity_compare_scene" if "entity_compare_scene" in allowed else "bullet_build_scene"
    if kind == "architecture_flow_scene":
        return "process_zoom_scene" if "process_zoom_scene" in allowed else "ecosystem_map_scene" if "ecosystem_map_scene" in allowed else "trend_line_scene" if "trend_line_scene" in allowed else "bullet_build_scene"
    if kind == "process_zoom_scene":
        return "architecture_flow_scene" if "architecture_flow_scene" in allowed else "ecosystem_map_scene" if "ecosystem_map_scene" in allowed else "bullet_build_scene"
    if kind == "browser_walkthrough_scene":
        return "source_article_scene" if has_source and "source_article_scene" in allowed else "quote_or_claim_highlight_scene" if has_source and "quote_or_claim_highlight_scene" in allowed else "document_stack_scene" if "document_stack_scene" in allowed else "bullet_build_scene"
    if kind == "decision_tree_scene":
        return "process_zoom_scene" if "process_zoom_scene" in allowed else "architecture_flow_scene" if "architecture_flow_scene" in allowed else "bullet_build_scene"
    if kind == "capability_matrix_scene":
        return "entity_compare_scene" if "entity_compare_scene" in allowed else "bar_chart_scene" if "bar_chart_scene" in allowed else "ranked_list_scene" if "ranked_list_scene" in allowed else "bullet_build_scene"
    if kind == "timeline_zoom_scene":
        return "document_stack_scene" if "document_stack_scene" in allowed else "trend_line_scene" if "trend_line_scene" in allowed else "bullet_build_scene"
    if kind == "document_stack_scene":
        return "browser_walkthrough_scene" if has_source and "browser_walkthrough_scene" in allowed else "source_article_scene" if has_source and "source_article_scene" in allowed else "bullet_build_scene"
    if kind == "signal_radar_scene":
        return "trend_line_scene" if "trend_line_scene" in allowed else "ecosystem_map_scene" if "ecosystem_map_scene" in allowed else "bullet_build_scene"
    if kind == "interface_transform_scene":
        return "process_zoom_scene" if "process_zoom_scene" in allowed else "architecture_flow_scene" if "architecture_flow_scene" in allowed else "bullet_build_scene"
    if kind == "source_article_scene" and has_source and "quote_or_claim_highlight_scene" in allowed:
        return "quote_or_claim_highlight_scene"
    if kind == "quote_or_claim_highlight_scene" and has_source and "source_article_scene" in allowed:
        return "source_article_scene"
    return "bullet_build_scene" if "bullet_build_scene" in allowed else kind


def _adapt_scene_to_render_kind(scene: dict[str, Any], render_kind: str) -> dict[str, Any]:
    script_excerpt = clean_text(scene.get("script_excerpt", ""))
    existing_payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
    adapted = dict(scene)
    adapted["render_kind"] = render_kind
    adapted["visual_intent"] = _default_visual_intent(render_kind)
    adapted["reason"] = clean_text(scene.get("reason", "")) or "Adjusted by anti-repetition visual rhythm guardrail."
    draft = {
        **existing_payload,
        "render_kind": render_kind,
        "source_record_key": clean_text(existing_payload.get("source_record_key", "")) or (scene.get("source_record_keys") or [""])[0],
        "url": clean_text(existing_payload.get("url", "")) or (scene.get("source_urls") or [""])[0],
        "target_text": clean_text(existing_payload.get("target_text", "")) or script_excerpt,
        "overlay_headline": clean_text(existing_payload.get("overlay_headline", "")) or _short_phrase(script_excerpt),
        "highlight_phrases": existing_payload.get("highlight_phrases", []) or [_short_phrase(script_excerpt)],
        "claim_text": clean_text(existing_payload.get("claim_text", "")) or _short_phrase(script_excerpt),
        "supporting_text": clean_text(existing_payload.get("supporting_text", "")) or script_excerpt,
        "primary_entity": clean_text(existing_payload.get("primary_entity", "")),
        "entities": existing_payload.get("entities", []),
        "phrases": existing_payload.get("phrases", []) or [_short_phrase(script_excerpt)],
        "emphasis_words": existing_payload.get("emphasis_words", []) or meaningful_words(script_excerpt)[:4],
        "headline": clean_text(existing_payload.get("headline", "")) or _short_phrase(script_excerpt),
        "points": existing_payload.get("points", []) or _points_from_text(script_excerpt, max_points=4, max_chars=62),
        "recap_items": existing_payload.get("recap_items", []) or _points_from_text(script_excerpt, max_points=6, max_chars=58),
        "final_takeaway": clean_text(existing_payload.get("final_takeaway", "")) or _short_phrase(script_excerpt),
        "metrics": existing_payload.get("metrics", []) or _metrics_from_text(script_excerpt),
        "metric_label": clean_text(existing_payload.get("metric_label", "")) or _metric_label_from_text(script_excerpt),
        "metric_value": clean_text(existing_payload.get("metric_value", "")) or _metric_value_from_text(script_excerpt),
        "metric_unit": clean_text(existing_payload.get("metric_unit", "")),
        "metric_context": clean_text(existing_payload.get("metric_context", "")) or script_excerpt,
        "emphasis_label": clean_text(existing_payload.get("emphasis_label", "")) or "Scale signal",
        "trend_direction": clean_text(existing_payload.get("trend_direction", "")) or _trend_direction_from_text(script_excerpt),
        "y_axis_label": clean_text(existing_payload.get("y_axis_label", "")) or "Momentum",
        "x_axis_label": clean_text(existing_payload.get("x_axis_label", "")) or "Time",
        "annotations": existing_payload.get("annotations", []) or _points_from_text(script_excerpt, max_points=3, max_chars=42),
        "bars": existing_payload.get("bars", []) or _bars_from_text(script_excerpt),
        "items": existing_payload.get("items", []) or _ranked_items_from_text(script_excerpt),
        "benchmarks": existing_payload.get("benchmarks", []) or _benchmarks_from_text(script_excerpt),
        "unit": clean_text(existing_payload.get("unit", "")),
        "leader_label": clean_text(existing_payload.get("leader_label", "")) or "Momentum shift",
        "winner_label": clean_text(existing_payload.get("winner_label", "")) or "Biggest delta",
        "chart_motion_style": clean_text(existing_payload.get("chart_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "grow_bars",
        "race_motion_style": clean_text(existing_payload.get("race_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "rank_shift",
        "ranked_motion_style": clean_text(existing_payload.get("ranked_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "staggered_rank",
        "benchmark_motion_style": clean_text(existing_payload.get("benchmark_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "delta_snap",
        "nodes": existing_payload.get("nodes", []),
        "edges": existing_payload.get("edges", []),
        "focus_entity": clean_text(existing_payload.get("focus_entity", "")),
        "steps": existing_payload.get("steps", []) or _flow_steps_from_text(script_excerpt),
        "active_step_label": clean_text(existing_payload.get("active_step_label", "")) or _short_phrase(script_excerpt),
        "focus_step_label": clean_text(existing_payload.get("focus_step_label", "")) or clean_text(existing_payload.get("active_step_label", "")) or _focus_step_from_text(script_excerpt),
        "zoom_note": clean_text(existing_payload.get("zoom_note", "")) or short_text(script_excerpt, 86),
        "zoom_motion_style": clean_text(existing_payload.get("zoom_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "focus_zoom",
        "walkthrough_steps": existing_payload.get("walkthrough_steps", []) or _flow_steps_from_text(script_excerpt),
        "focus_text": clean_text(existing_payload.get("focus_text", "")) or _short_phrase(script_excerpt),
        "browser_motion_style": clean_text(existing_payload.get("browser_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "guided_scroll",
        "root_label": clean_text(existing_payload.get("root_label", "")) or "Decision point",
        "branches": existing_payload.get("branches", []) or _decision_branches_from_text(script_excerpt),
        "selected_path_label": clean_text(existing_payload.get("selected_path_label", "")) or _short_phrase(script_excerpt),
        "decision_motion_style": clean_text(existing_payload.get("decision_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "branch_glow",
        "columns": existing_payload.get("columns", []) or ["Speed", "Cost", "Context", "Tools"],
        "rows": existing_payload.get("rows", []) or _matrix_rows_from_text(script_excerpt),
        "highlight_cell": clean_text(existing_payload.get("highlight_cell", "")) or "Best fit",
        "matrix_motion_style": clean_text(existing_payload.get("matrix_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "cell_scan",
        "events": existing_payload.get("events", []) or _timeline_events_from_text(script_excerpt),
        "focus_event_label": clean_text(existing_payload.get("focus_event_label", "")) or _short_phrase(script_excerpt),
        "timeline_motion_style": clean_text(existing_payload.get("timeline_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "event_zoom",
        "documents": existing_payload.get("documents", []) or _documents_from_text(script_excerpt),
        "focus_document_label": clean_text(existing_payload.get("focus_document_label", "")) or _short_phrase(script_excerpt),
        "document_motion_style": clean_text(existing_payload.get("document_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "parallax_stack",
        "signals": existing_payload.get("signals", []) or _signals_from_text(script_excerpt),
        "scan_label": clean_text(existing_payload.get("scan_label", "")) or "Emerging signal",
        "radar_motion_style": clean_text(existing_payload.get("radar_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "radar_sweep",
        "before": existing_payload.get("before", {}) or {"label": "Before", "detail": "manual workflow", "items": _points_from_text(script_excerpt, max_points=3, max_chars=34)},
        "after": existing_payload.get("after", {}) or {"label": "After", "detail": "AI-assisted workflow", "items": _flow_step_labels_from_text(script_excerpt)[:3]},
        "transformation_label": clean_text(existing_payload.get("transformation_label", "")) or "workflow shift",
        "transform_motion_style": clean_text(existing_payload.get("transform_motion_style", "")) or clean_text(existing_payload.get("motion_style", "")) or "panel_morph",
    }
    adapted["payload"] = _payload_for_scene(
        draft=draft,
        render_kind=render_kind,
        story_id=clean_text(scene.get("story_id", "")),
        source_record_key=clean_text(draft.get("source_record_key", "")),
        url=clean_text(draft.get("url", "")),
        script_excerpt=script_excerpt,
        source_index={"records_by_key": {}, "record_keys_by_story": {}},
    )
    if render_kind not in {"source_article_scene", "quote_or_claim_highlight_scene"}:
        adapted["source_record_keys"] = []
        adapted["source_urls"] = []
    return adapted


def _merge_adjacent_scenes(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    preferred = _preferred_scene_for_merge(first, second)
    start = safe_float(first.get("start_seconds"), 0.0)
    end = safe_float(second.get("end_seconds"), start)
    script_excerpt = short_text(" ".join([clean_text(first.get("script_excerpt", "")), clean_text(second.get("script_excerpt", ""))]), 420)
    payload = _merged_payload_for_scene(preferred, first, second, script_excerpt, start)
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
        "script_excerpt": script_excerpt,
        "payload": payload,
        "source_record_keys": dedupe([*first.get("source_record_keys", []), *second.get("source_record_keys", [])]),
        "source_urls": dedupe([*first.get("source_urls", []), *second.get("source_urls", [])]),
        "reason": clean_text(preferred.get("reason", "")) or "Merged adjacent short scenes during deterministic compaction.",
    }


def _merged_payload_for_scene(preferred: dict[str, Any], first: dict[str, Any], second: dict[str, Any], script_excerpt: str, scene_start_seconds: float) -> dict[str, Any]:
    payload = dict(preferred.get("payload", {})) if isinstance(preferred.get("payload"), dict) else {}
    render_kind = clean_text(preferred.get("render_kind", ""))
    beats = _merge_scene_beats(first, second, scene_start_seconds)
    if beats:
        payload["beats"] = beats
        payload["beat_count"] = len(beats)
        payload["covered_text"] = short_text(" ".join(beat["text"] for beat in beats if beat.get("text")), 320)
    if render_kind == "kinetic_type_scene":
        payload["phrases"] = [_short_phrase(script_excerpt), *dedupe([clean_text(item) for scene in (first, second) for item in (scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}).get("phrases", [])])][:3]
        payload["emphasis_words"] = meaningful_words(script_excerpt)[:5]
    elif render_kind == "bullet_build_scene":
        points = [
            clean_text(item)
            for scene in (first, second)
            for item in (scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}).get("points", [])
            if clean_text(item)
        ]
        payload["points"] = dedupe(points + _points_from_text(script_excerpt, max_points=4, max_chars=64))[:4]
        payload["headline"] = short_text(clean_text(payload.get("headline", "")) or _short_phrase(script_excerpt), 64)
    elif render_kind == "recap_sequence_scene":
        items = [
            clean_text(item)
            for scene in (first, second)
            for item in (scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}).get("recap_items", [])
            if clean_text(item)
        ]
        payload["recap_items"] = dedupe(items + _points_from_text(script_excerpt, max_points=6, max_chars=58))[:6]
        payload["final_takeaway"] = short_text(clean_text(payload.get("final_takeaway", "")) or _short_phrase(script_excerpt), 64)
    return payload


def _merge_scene_beats(first: dict[str, Any], second: dict[str, Any], scene_start_seconds: float) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for scene in (first, second):
        payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
        beats = payload.get("beats") if isinstance(payload.get("beats"), list) else []
        for beat in beats:
            if not isinstance(beat, dict):
                continue
            start = safe_float(beat.get("start_seconds"), safe_float(scene.get("start_seconds"), scene_start_seconds))
            end = safe_float(beat.get("end_seconds"), start)
            merged.append(
                {
                    **beat,
                    "start_seconds": round(start, 2),
                    "end_seconds": round(end, 2),
                    "relative_start_seconds": round(max(0.0, start - scene_start_seconds), 2),
                    "relative_end_seconds": round(max(0.0, end - scene_start_seconds), 2),
                }
            )
    return sorted(merged, key=lambda beat: (safe_float(beat.get("start_seconds"), 0.0), safe_int(beat.get("unit_order"), 0)))


def _preferred_scene_for_merge(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    priority = {
        "source_article_scene": 0,
        "quote_or_claim_highlight_scene": 1,
        "broll_video_scene": 2,
        "context_image_scene": 3,
        "benchmark_delta_scene": 4,
        "bar_chart_scene": 5,
        "bar_race_scene": 6,
        "browser_walkthrough_scene": 7,
        "decision_tree_scene": 8,
        "capability_matrix_scene": 9,
        "timeline_zoom_scene": 10,
        "document_stack_scene": 11,
        "signal_radar_scene": 12,
        "interface_transform_scene": 13,
        "process_zoom_scene": 14,
        "architecture_flow_scene": 15,
        "ecosystem_map_scene": 16,
        "entity_compare_scene": 17,
        "data_counter_scene": 18,
        "trend_line_scene": 19,
        "logo_reveal_scene": 20,
        "ranked_list_scene": 21,
        "bullet_build_scene": 22,
        "kinetic_type_scene": 23,
        "recap_sequence_scene": 24,
        "transition_stinger_scene": 25,
    }
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
        sections = _sections_from_content_order(script_units, stories)
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
    if script_units and all(clean_text(unit.get("section_id", "")) for unit in script_units):
        sections: list[dict[str, Any]] = []
        for section in explicit_sections:
            section_id = clean_text(section.get("section_id", ""))
            units = [unit for unit in script_units if clean_text(unit.get("section_id", "")) == section_id]
            if not units:
                continue
            story_id = clean_text(section.get("story_id", ""))
            mapped = _section_from_unit_range(
                section_type=clean_text(section.get("section_type", "story")),
                story=story_lookup.get(story_id, {}),
                start_unit=safe_int(units[0].get("order"), 1),
                end_unit=safe_int(units[-1].get("order"), 1),
                script_units=script_units,
                assignment_method="canonical_script_beats_with_voiceover_alignment",
            )
            mapped["section_id"] = section_id
            mapped["title_card"] = section.get("title_card")
            sections.append(mapped)
        if len(sections) == len(explicit_sections):
            return sections
    cursor = 1
    sections: list[dict[str, Any]] = []
    for index, section in enumerate(explicit_sections, start=1):
        section_word_count = max(1, count_words(clean_text(section.get("narration_text", ""))))
        start = cursor
        consumed = 0
        while cursor <= len(script_units) and (consumed < section_word_count or index == len(explicit_sections)):
            consumed += safe_int(script_units[cursor - 1].get("word_count"), count_words(script_units[cursor - 1].get("text", "")))
            cursor += 1
            if index != len(explicit_sections) and consumed >= section_word_count:
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
        return _sections_from_content_order(script_units, stories)
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
    closing_started = False
    for index, paragraph in enumerate(paragraphs):
        text = clean_text(paragraph.get("text", ""))
        lower = text.lower()
        if closing_started or (CLOSING_RE.search(lower) and index >= max(1, len(paragraphs) - 6)):
            closing_started = True
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


def _sections_from_content_order(
    script_units: list[dict[str, Any]],
    stories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not script_units:
        return []
    group_count = len(stories) + 2
    labels_by_group = [
        {"section_type": "intro", "story_id": ""},
        *[
            {"section_type": "story", "story_id": clean_text(story.get("story_id", ""))}
            for story in stories
        ],
        {"section_type": "closing", "story_id": ""},
    ]
    if len(script_units) >= group_count:
        base, remainder = divmod(len(script_units), group_count)
        group_sizes = [base + (1 if index < remainder else 0) for index in range(group_count)]
    else:
        group_sizes = [1] * len(script_units) + [0] * (group_count - len(script_units))
    labels: list[dict[str, Any]] = []
    unit_index = 0
    for group_index, size in enumerate(group_sizes):
        label = labels_by_group[group_index]
        for _ in range(size):
            if unit_index >= len(script_units):
                break
            unit = script_units[unit_index]
            labels.append(
                {
                    "unit_order": safe_int(unit.get("order"), unit_index + 1),
                    **label,
                }
            )
            unit_index += 1
    return _sections_from_unit_labels(labels, script_units, stories, assignment_method="content_order_fallback")


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
                "section_id": unit.get("section_id", ""),
                "story_id": unit.get("story_id", ""),
                "beat_id": unit.get("beat_id", ""),
                "beat_type": unit.get("beat_type", ""),
                "source_record_keys": unit.get("source_record_keys", []),
                "visual_brief": unit.get("visual_brief", {}),
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
        "source_article_scene": int(policy.get("max_source_article_scenes", 999999)),
        "context_image_scene": int(policy.get("max_context_image_scenes", 999999)),
        "broll_video_scene": int(policy.get("max_broll_video_scenes", 999999)),
        "logo_reveal_scene": int(policy.get("max_logo_reveal_scenes", 999999)),
        "kinetic_type_scene": int(policy.get("max_kinetic_type_scenes", 999999)),
        "bullet_build_scene": int(policy.get("max_bullet_build_scenes", 999999)),
        "quote_or_claim_highlight_scene": int(policy.get("max_quote_or_claim_highlight_scenes", 999999)),
        "entity_compare_scene": int(policy.get("max_entity_compare_scenes", 999999)),
        "recap_sequence_scene": int(policy.get("max_recap_sequence_scenes", 999999)),
        "data_counter_scene": int(policy.get("max_data_counter_scenes", 999999)),
        "trend_line_scene": int(policy.get("max_trend_line_scenes", 999999)),
        "bar_chart_scene": int(policy.get("max_bar_chart_scenes", 999999)),
        "bar_race_scene": int(policy.get("max_bar_race_scenes", 999999)),
        "ranked_list_scene": int(policy.get("max_ranked_list_scenes", 999999)),
        "benchmark_delta_scene": int(policy.get("max_benchmark_delta_scenes", 999999)),
        "ecosystem_map_scene": int(policy.get("max_ecosystem_map_scenes", 999999)),
        "architecture_flow_scene": int(policy.get("max_architecture_flow_scenes", 999999)),
        "process_zoom_scene": int(policy.get("max_process_zoom_scenes", 999999)),
        "browser_walkthrough_scene": int(policy.get("max_browser_walkthrough_scenes", 999999)),
        "decision_tree_scene": int(policy.get("max_decision_tree_scenes", 999999)),
        "capability_matrix_scene": int(policy.get("max_capability_matrix_scenes", 999999)),
        "timeline_zoom_scene": int(policy.get("max_timeline_zoom_scenes", 999999)),
        "document_stack_scene": int(policy.get("max_document_stack_scenes", 999999)),
        "signal_radar_scene": int(policy.get("max_signal_radar_scenes", 999999)),
        "interface_transform_scene": int(policy.get("max_interface_transform_scenes", 999999)),
        "transition_stinger_scene": int(policy.get("max_transition_stinger_scenes", 999999)),
    }
    if counts.get(render_kind, 0) >= caps.get(render_kind, 999999):
        render_kind = _fallback_non_capped_kind(render_kind, allowed, counts, caps)
    return render_kind


def _fallback_non_capped_kind(
    current: str,
    allowed: set[str],
    counts: Counter[str],
    caps: dict[str, int],
) -> str:
    preferred = [
        "broll_video_scene",
        "context_image_scene",
        "data_counter_scene",
        "bar_chart_scene",
        "benchmark_delta_scene",
        "bar_race_scene",
        "ranked_list_scene",
        "capability_matrix_scene",
        "interface_transform_scene",
        "decision_tree_scene",
        "browser_walkthrough_scene",
        "timeline_zoom_scene",
        "document_stack_scene",
        "signal_radar_scene",
        "trend_line_scene",
        "process_zoom_scene",
        "architecture_flow_scene",
        "ecosystem_map_scene",
        "quote_or_claim_highlight_scene",
        "source_article_scene",
        "entity_compare_scene",
        "logo_reveal_scene",
        "bullet_build_scene",
        "kinetic_type_scene",
        "recap_sequence_scene",
        "transition_stinger_scene",
    ]
    for kind in preferred:
        if kind in allowed and kind != current and counts.get(kind, 0) < caps.get(kind, 999999):
            return kind
    return "kinetic_type_scene" if "kinetic_type_scene" in allowed else sorted(allowed)[0]


def _best_render_kind_for_draft(
    draft: dict[str, Any],
    story_id: str,
    source_index: dict[str, Any],
    allowed: set[str],
) -> str:
    excerpt = clean_text(draft.get("script_excerpt", ""))
    metrics = draft.get("metrics", []) if isinstance(draft.get("metrics", []), list) else []
    bars = draft.get("bars", []) if isinstance(draft.get("bars", []), list) else []
    items = draft.get("items", []) if isinstance(draft.get("items", []), list) else []
    benchmarks = draft.get("benchmarks", []) if isinstance(draft.get("benchmarks", []), list) else []
    if "broll_video_scene" in allowed and clean_text(draft.get("render_kind", "")) == "broll_video_scene" and draft.get("search_queries"):
        return "broll_video_scene"
    if "context_image_scene" in allowed and clean_text(draft.get("render_kind", "")) == "context_image_scene" and draft.get("search_queries"):
        return "context_image_scene"
    if "browser_walkthrough_scene" in allowed and (clean_text(draft.get("focus_text", "")) or draft.get("walkthrough_steps") or (_source_for_scene(draft, story_id, "source_article_scene", source_index)[1] and _excerpt_has_browser_context(excerpt))):
        return "browser_walkthrough_scene"
    if "interface_transform_scene" in allowed and (draft.get("before") or draft.get("after") or clean_text(draft.get("transformation_label", "")) or _excerpt_has_interface_transform(excerpt)):
        return "interface_transform_scene"
    if "decision_tree_scene" in allowed and (draft.get("branches") or clean_text(draft.get("root_label", "")) or _excerpt_has_decision_tree(excerpt)):
        return "decision_tree_scene"
    if "capability_matrix_scene" in allowed and (draft.get("rows") or draft.get("columns") or _excerpt_has_capability_matrix(excerpt)):
        return "capability_matrix_scene"
    if "timeline_zoom_scene" in allowed and (draft.get("events") or clean_text(draft.get("focus_event_label", "")) or _excerpt_has_timeline_zoom(excerpt)):
        return "timeline_zoom_scene"
    if "document_stack_scene" in allowed and (draft.get("documents") or _excerpt_has_document_stack(excerpt)):
        return "document_stack_scene"
    if "signal_radar_scene" in allowed and (draft.get("signals") or clean_text(draft.get("scan_label", "")) or _excerpt_has_signal_radar(excerpt)):
        return "signal_radar_scene"
    if "benchmark_delta_scene" in allowed and (benchmarks or _excerpt_has_benchmark_delta(excerpt)):
        return "benchmark_delta_scene"
    if "bar_chart_scene" in allowed and (bars or len(metrics) >= 2 or _excerpt_has_metric_comparison(excerpt)):
        return "bar_chart_scene"
    if "bar_race_scene" in allowed and (_items_have_race_values(items) or _excerpt_has_race(excerpt)):
        return "bar_race_scene"
    if "ranked_list_scene" in allowed and (items or _excerpt_has_ranking(excerpt)):
        return "ranked_list_scene"
    if "data_counter_scene" in allowed and (draft.get("metrics") or clean_text(draft.get("metric_value", "")) or _excerpt_has_metric(excerpt)):
        return "data_counter_scene"
    if "trend_line_scene" in allowed and (_excerpt_has_trend(excerpt) or draft.get("annotations")):
        return "trend_line_scene"
    if "process_zoom_scene" in allowed and (clean_text(draft.get("focus_step_label", "")) or clean_text(draft.get("zoom_note", "")) or _excerpt_has_process_focus(excerpt)):
        return "process_zoom_scene"
    if "architecture_flow_scene" in allowed and (draft.get("steps") or _excerpt_has_flow(excerpt)):
        return "architecture_flow_scene"
    if "ecosystem_map_scene" in allowed and (draft.get("nodes") or len(draft.get("entities", [])) >= 2):
        return "ecosystem_map_scene"
    if "quote_or_claim_highlight_scene" in allowed and _source_for_scene(draft, story_id, "quote_or_claim_highlight_scene", source_index)[1]:
        return "quote_or_claim_highlight_scene"
    if "source_article_scene" in allowed and _source_for_scene(draft, story_id, "source_article_scene", source_index)[1]:
        return "source_article_scene"
    if "bullet_build_scene" in allowed and len(draft.get("points", []) or draft.get("phrases", [])) >= 2:
        return "bullet_build_scene"
    if "entity_compare_scene" in allowed and len(draft.get("entities", [])) >= 2:
        return "entity_compare_scene"
    if "transition_stinger_scene" in allowed and clean_text(draft.get("transition_label", "")):
        return "transition_stinger_scene"
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
    if render_kind in {"context_image_scene", "broll_video_scene"}:
        search_queries = dedupe([clean_text(item) for item in draft.get("search_queries", [])])
        if not search_queries:
            search_queries = dedupe(
                [
                    clean_text(draft.get("primary_entity", "")),
                    clean_text(draft.get("headline", "")),
                    short_text(script_excerpt, 120),
                ]
            )
        return {
            "search_queries": search_queries[:3],
            "must_show": dedupe([clean_text(item) for item in draft.get("must_show", [])])[:5],
            "must_avoid": dedupe([clean_text(item) for item in draft.get("must_avoid", [])])[:5],
            "shot_style": short_text(clean_text(draft.get("shot_style", "")) or "editorial_wide", 48),
            "overlay_headline": short_text(clean_text(draft.get("media_overlay_headline", "")), 54),
            "motion_style": clean_text(draft.get("media_motion_style", "")) or ("editorial_crop" if render_kind == "broll_video_scene" else "slow_push"),
            "show_overlay": bool(draft.get("show_media_overlay", False)),
        }
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
    if render_kind == "quote_or_claim_highlight_scene":
        record = source_index["records_by_key"].get(source_record_key, {}) if source_record_key else {}
        candidates = record.get("screenshot_target_candidates", []) if record else []
        claim_text = clean_text(draft.get("claim_text", "")) or clean_text(draft.get("target_text", "")) or _short_phrase(script_excerpt)
        supporting_text = clean_text(draft.get("supporting_text", "")) or (candidates[0] if candidates else script_excerpt)
        return {
            "url": url,
            "source_record_key": source_record_key,
            "claim_text": short_text(claim_text, 90),
            "supporting_text": short_text(supporting_text, 260),
            "highlight_phrases": dedupe([clean_text(item) for item in draft.get("highlight_phrases", [])] + [claim_text])[:4],
            "overlay_headline": short_text(clean_text(draft.get("overlay_headline", "")) or claim_text or script_excerpt, 70),
            "motion_style": clean_text(draft.get("source_motion_style", "")) or "highlight_scan",
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
    if render_kind == "entity_compare_scene":
        primary_entity = clean_text(draft.get("primary_entity", "")) or _primary_entity_for_story(story_id, source_index)
        entity_items = [clean_text(item) for item in draft.get("entities", []) if clean_text(item)]
        entities = dedupe([primary_entity, *entity_items])[:4]
        if len(entities) < 2:
            entities = dedupe([primary_entity or "AI", "Market", "Developers"])[:3]
        notes = [short_text(clean_text(item), 52) for item in draft.get("entity_notes", []) if clean_text(item)]
        if len(notes) < len(entities):
            notes.extend(_points_from_text(script_excerpt, max_points=len(entities) - len(notes), max_chars=48))
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or clean_text(draft.get("companion_text", "")) or "How the players line up", 72),
            "entities": entities,
            "comparison_axis": short_text(clean_text(draft.get("comparison_axis", "")) or "What changes for viewers", 52),
            "entity_notes": notes[: len(entities)],
            "motion_style": clean_text(draft.get("comparison_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "versus",
        }
    if render_kind == "data_counter_scene":
        metrics = _metrics_from_draft(draft, script_excerpt)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "The scale signal", 64),
            "metrics": metrics[:3],
            "emphasis_label": short_text(clean_text(draft.get("emphasis_label", "")) or "What changes", 44),
            "motion_style": clean_text(draft.get("data_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "count_up",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "trend_line_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "Momentum is shifting", 64),
            "trend_direction": clean_text(draft.get("trend_direction", "")) or _trend_direction_from_text(script_excerpt),
            "y_axis_label": short_text(clean_text(draft.get("y_axis_label", "")) or "Momentum", 32),
            "x_axis_label": short_text(clean_text(draft.get("x_axis_label", "")) or "Time", 32),
            "annotations": _annotations_from_draft(draft, script_excerpt),
            "motion_style": clean_text(draft.get("trend_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "draw_line",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "bar_chart_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "The comparison", 64),
            "bars": _bars_from_draft(draft, script_excerpt)[:5],
            "unit": short_text(clean_text(draft.get("unit", "")), 12),
            "emphasis_label": short_text(clean_text(draft.get("emphasis_label", "")) or "Scale comparison", 44),
            "motion_style": clean_text(draft.get("chart_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "grow_bars",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "bar_race_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "The race is shifting", 64),
            "items": _race_items_from_draft(draft, script_excerpt)[:5],
            "unit": short_text(clean_text(draft.get("unit", "")), 12),
            "leader_label": short_text(clean_text(draft.get("leader_label", "")) or "Momentum shift", 48),
            "motion_style": clean_text(draft.get("race_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "rank_shift",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "ranked_list_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "What matters most", 64),
            "items": _ranked_items_from_draft(draft, script_excerpt)[:5],
            "emphasis_label": short_text(clean_text(draft.get("emphasis_label", "")) or "Priority order", 44),
            "motion_style": clean_text(draft.get("ranked_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "staggered_rank",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "benchmark_delta_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "The delta is the story", 64),
            "benchmarks": _benchmarks_from_draft(draft, script_excerpt)[:3],
            "winner_label": short_text(clean_text(draft.get("winner_label", "")) or "Notable shift", 48),
            "motion_style": clean_text(draft.get("benchmark_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "delta_snap",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "ecosystem_map_scene":
        entities = _entities_for_story(story_id, source_index, script_excerpt, draft.get("entities", []))
        nodes = _nodes_from_draft(draft, entities)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "How the ecosystem connects", 64),
            "nodes": nodes[:6],
            "edges": _edges_from_draft(draft, nodes),
            "focus_entity": short_text(clean_text(draft.get("focus_entity", "")) or clean_text(draft.get("primary_entity", "")) or (nodes[0]["label"] if nodes else "AI"), 36),
            "motion_style": clean_text(draft.get("map_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "pulse_connections",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "architecture_flow_scene":
        steps = _flow_steps_from_draft(draft, script_excerpt)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "How the system works", 64),
            "steps": steps[:6],
            "flow_direction": clean_text(draft.get("flow_direction", "")) or "left_to_right",
            "active_step_label": short_text(clean_text(draft.get("active_step_label", "")) or (steps[-1]["label"] if steps else _short_phrase(script_excerpt)), 44),
            "motion_style": clean_text(draft.get("flow_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "packet_flow",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "process_zoom_scene":
        steps = _flow_steps_from_draft(draft, script_excerpt)
        focus = clean_text(draft.get("focus_step_label", "")) or clean_text(draft.get("active_step_label", "")) or _focus_step_from_steps(steps)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "Zoom into the workflow", 64),
            "steps": steps[:6],
            "focus_step_label": short_text(focus, 44),
            "zoom_note": short_text(clean_text(draft.get("zoom_note", "")) or clean_text(draft.get("metric_context", "")) or script_excerpt, 86),
            "motion_style": clean_text(draft.get("zoom_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "focus_zoom",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "browser_walkthrough_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or clean_text(draft.get("overlay_headline", "")) or "Walk through the source", 64),
            "url": clean_text(url or draft.get("url", "")),
            "source_record_key": source_record_key or clean_text(draft.get("source_record_key", "")),
            "walkthrough_steps": _walkthrough_steps_from_draft(draft, script_excerpt)[:5],
            "focus_text": short_text(clean_text(draft.get("focus_text", "")) or clean_text(draft.get("target_text", "")) or _short_phrase(script_excerpt), 76),
            "motion_style": clean_text(draft.get("browser_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "guided_scroll",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "decision_tree_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "The decision path", 64),
            "root_label": short_text(clean_text(draft.get("root_label", "")) or "Decision point", 42),
            "branches": _decision_branches_from_draft(draft, script_excerpt)[:5],
            "selected_path_label": short_text(clean_text(draft.get("selected_path_label", "")) or _short_phrase(script_excerpt), 48),
            "motion_style": clean_text(draft.get("decision_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "branch_glow",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "capability_matrix_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "Capability tradeoffs", 64),
            "columns": _matrix_columns_from_draft(draft)[:5],
            "rows": _matrix_rows_from_draft(draft, script_excerpt)[:5],
            "highlight_cell": short_text(clean_text(draft.get("highlight_cell", "")) or "Best fit", 40),
            "motion_style": clean_text(draft.get("matrix_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "cell_scan",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "timeline_zoom_scene":
        events = _timeline_events_from_draft(draft, script_excerpt)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "The moment that changed the arc", 64),
            "events": events[:5],
            "focus_event_label": short_text(clean_text(draft.get("focus_event_label", "")) or (events[min(1, len(events) - 1)]["label"] if events else _short_phrase(script_excerpt)), 44),
            "zoom_note": short_text(clean_text(draft.get("zoom_note", "")) or script_excerpt, 86),
            "motion_style": clean_text(draft.get("timeline_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "event_zoom",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "document_stack_scene":
        documents = _documents_from_draft(draft, script_excerpt)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "The evidence stack", 64),
            "documents": documents[:5],
            "focus_document_label": short_text(clean_text(draft.get("focus_document_label", "")) or (documents[0]["title"] if documents else _short_phrase(script_excerpt)), 46),
            "motion_style": clean_text(draft.get("document_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "parallax_stack",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "signal_radar_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "Signal radar", 64),
            "signals": _signals_from_draft(draft, script_excerpt)[:7],
            "scan_label": short_text(clean_text(draft.get("scan_label", "")) or "Emerging signal", 44),
            "motion_style": clean_text(draft.get("radar_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "radar_sweep",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "interface_transform_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "From interface to workflow", 64),
            "before": _interface_panel_from_draft(draft.get("before"), "Before", script_excerpt),
            "after": _interface_panel_from_draft(draft.get("after"), "After", script_excerpt, flow=True),
            "transformation_label": short_text(clean_text(draft.get("transformation_label", "")) or "workflow shift", 48),
            "motion_style": clean_text(draft.get("transform_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "panel_morph",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "transition_stinger_scene":
        label = clean_text(draft.get("transition_label", "")) or clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt)
        subtitle = clean_text(draft.get("transition_subtitle", "")) or clean_text(draft.get("companion_text", ""))
        return {
            "transition_label": short_text(label, 48),
            "subtitle": short_text(subtitle or "next signal", 60),
            "motion_style": clean_text(draft.get("stinger_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "signal_wipe",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "bullet_build_scene":
        points = [short_text(clean_text(item), 68) for item in draft.get("points", []) if clean_text(item)]
        if not points:
            points = _points_from_text(script_excerpt, max_points=4, max_chars=64)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "points": points[:4],
            "emphasis_words": dedupe([clean_text(item) for item in draft.get("emphasis_words", [])] + meaningful_words(script_excerpt))[:6],
            "build_style": clean_text(draft.get("build_style", "")) or "numbered_build",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "recap_sequence_scene":
        items = [short_text(clean_text(item), 62) for item in draft.get("recap_items", []) if clean_text(item)]
        if not items:
            items = _points_from_text(script_excerpt, max_points=5, max_chars=58)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or "The bigger shift", 64),
            "recap_items": items[:6],
            "final_takeaway": short_text(clean_text(draft.get("final_takeaway", "")) or _short_phrase(script_excerpt), 84),
            "motion_style": clean_text(draft.get("recap_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "story_rhythm",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
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
            "quote_or_claim_highlight_scene": "source_screenshot",
            "context_image_scene": "context_image",
            "broll_video_scene": "broll_video",
            "logo_reveal_scene": "logo_asset",
            "entity_compare_scene": "none",
            "bullet_build_scene": "none",
            "recap_sequence_scene": "none",
            "kinetic_type_scene": "none",
            "data_counter_scene": "none",
            "trend_line_scene": "none",
            "bar_chart_scene": "none",
            "bar_race_scene": "none",
            "ranked_list_scene": "none",
            "benchmark_delta_scene": "none",
            "ecosystem_map_scene": "none",
            "architecture_flow_scene": "none",
            "process_zoom_scene": "none",
            "browser_walkthrough_scene": "none",
            "decision_tree_scene": "none",
            "capability_matrix_scene": "none",
            "timeline_zoom_scene": "none",
            "document_stack_scene": "none",
            "signal_radar_scene": "none",
            "interface_transform_scene": "none",
            "transition_stinger_scene": "none",
        }[render_kind]
        requests.append(
            {
                "asset_request_id": f"asset_{scene['scene_order']:03d}",
                "scene_id": scene["scene_id"],
                "render_kind": render_kind,
                "asset_type": asset_type,
                "required": render_kind in {"source_article_scene", "quote_or_claim_highlight_scene", "logo_reveal_scene", "context_image_scene", "broll_video_scene"},
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


def _story_time_ranges(
    story_sections: list[dict[str, Any]],
    stories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sections_by_story = {
        clean_text(section.get("story_id", "")): section
        for section in story_sections
        if clean_text(section.get("section_type", "")) == "story"
        and clean_text(section.get("story_id", ""))
    }
    ranges: list[dict[str, Any]] = []
    for story in stories:
        story_id = clean_text(story.get("story_id", ""))
        section = sections_by_story.get(story_id)
        if not section:
            continue
        start = safe_float(section.get("start_seconds"), 0.0)
        end = safe_float(section.get("end_seconds"), start)
        ranges.append(
            {
                "story_id": story_id,
                "story_title": clean_text(story.get("story_title", "")),
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "duration_seconds": round(max(0.0, end - start), 2),
                "timing_source": clean_text(section.get("assignment_method", "")),
            }
        )
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
    if render_kind not in {"source_article_scene", "quote_or_claim_highlight_scene"}:
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
                "fallback_used": bool(draft.get("fallback_used")),
                "fallback_reason": clean_text(draft.get("fallback_reason", "")),
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
    return sorted(beat_map, key=lambda item: (safe_float(item.get("start_seconds"), 0.0), safe_int(item.get("unit_order"), 0)))


def _check_scene_plan(visual_scene_plan: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    scenes = visual_scene_plan.get("scene_timeline", [])
    allowed = set(config["scene_policy"]["allowed_render_kinds"])
    fallback_stories = _story_planner_fallbacks(visual_scene_plan)
    if fallback_stories:
        message = f"Story-level visual planning fell back for {len(fallback_stories)} story section(s): {fallback_stories[:8]}"
        if config.get("allow_deterministic_story_fallbacks"):
            warnings.append(message)
        else:
            errors.append(message)
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
    timeline_start = safe_float(coverage.get("timeline_start_seconds"), 0.0)
    timeline_end = safe_float(coverage.get("timeline_end_seconds"), 0.0)
    expected_end = safe_float(coverage.get("total_duration_seconds"), 0.0)
    if abs(timeline_start) > 0.05:
        errors.append(f"scene timeline must start at 0.0 seconds, got {timeline_start:.2f}")
    if expected_end > 0 and abs(timeline_end - expected_end) > 0.25:
        errors.append(
            f"scene timeline must end at the authoritative duration: {timeline_end:.2f}s vs {expected_end:.2f}s"
        )
    for story_plan in visual_scene_plan.get("story_plans", []):
        story_id = clean_text(story_plan.get("story_id", ""))
        story_scenes = [scene for scene in scenes if clean_text(scene.get("story_id", "")) == story_id]
        title_scenes = [scene for scene in story_scenes if _is_story_title_interstitial(scene)]
        if len(title_scenes) != 1:
            errors.append(f"{story_id} must have exactly one deterministic story-title interstitial; found {len(title_scenes)}")
        elif story_scenes and title_scenes[0].get("scene_id") != story_scenes[0].get("scene_id"):
            errors.append(f"{story_id} story-title interstitial must be the first scene in its story")
    source_scenes = [
        scene
        for scene in scenes
        if scene.get("render_kind") in {"source_article_scene", "quote_or_claim_highlight_scene"}
    ]
    source_url_count = safe_int(visual_scene_plan.get("source_context", {}).get("source_url_count"), 0)
    if (
        source_url_count > 0
        and not source_scenes
        and {"source_article_scene", "quote_or_claim_highlight_scene"} & allowed
    ):
        warnings.append("No source-backed scenes were planned even though selected-story source URLs are available.")
    for scene in source_scenes:
        payload = scene.get("payload", {})
        if not clean_text(payload.get("url", "")).startswith(("http://", "https://")):
            errors.append(f"{scene.get('scene_id')} {scene.get('render_kind')} is missing a valid url")
        if not clean_text(payload.get("source_record_key", "")):
            errors.append(f"{scene.get('scene_id')} {scene.get('render_kind')} is missing source_record_key")
    media_scenes = [scene for scene in scenes if scene.get("render_kind") in {"context_image_scene", "broll_video_scene"}]
    for scene in media_scenes:
        payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
        queries = payload.get("search_queries") if isinstance(payload.get("search_queries"), list) else []
        if not any(clean_text(query) for query in queries):
            errors.append(f"{scene.get('scene_id')} {scene.get('render_kind')} is missing search_queries")
    kind_counts = Counter(scene.get("render_kind", "") for scene in scenes)
    max_same = safe_int(config["scene_policy"].get("max_consecutive_same_kind"), 2)
    repetitive_runs = _same_kind_runs_over_limit(scenes, max_same)
    if repetitive_runs:
        warnings.append(f"Visual rhythm has repeated scene-kind runs over limit: {repetitive_runs[:5]}")
    placeholder_scenes = _generic_placeholder_scenes(scenes)
    if placeholder_scenes:
        warnings.append(f"Visual payloads contain generic placeholder labels that may feel disconnected: {placeholder_scenes[:8]}")
    if scenes:
        dominant_kind, dominant_count = kind_counts.most_common(1)[0]
        if dominant_count / len(scenes) > 0.72:
            warnings.append(f"Visual mix may be repetitive: {dominant_kind} is {dominant_count}/{len(scenes)} scenes.")
        text_like_count = len([scene for scene in scenes if scene.get("render_kind") in TEXT_LIKE_RENDER_KINDS])
        text_like_duration = sum(
            safe_float(scene.get("duration_seconds"), 0.0)
            for scene in scenes
            if scene.get("render_kind") in TEXT_LIKE_RENDER_KINDS
        )
        total_duration = sum(safe_float(scene.get("duration_seconds"), 0.0) for scene in scenes)
        if text_like_count / len(scenes) > 0.45:
            warnings.append(f"Text-like visual mix is high: {text_like_count}/{len(scenes)} scenes.")
        if total_duration > 0 and text_like_duration / total_duration > 0.45:
            warnings.append(f"Text-like visual duration is high: {round(text_like_duration, 2)}/{round(total_duration, 2)} seconds.")
    if not any(scene.get("render_kind") == "logo_reveal_scene" for scene in scenes):
        warnings.append("No logo_reveal_scene was planned.")
    if not any(scene.get("render_kind") == "kinetic_type_scene" for scene in scenes):
        warnings.append("No kinetic_type_scene was planned.")
    return {"passed": not errors, "errors": errors, "warnings": warnings}


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


def _same_kind_runs_over_limit(scenes: list[dict[str, Any]], max_same: int) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    current_kind = ""
    current_start = ""
    current_count = 0
    current_end = ""
    for scene in scenes:
        kind = clean_text(scene.get("render_kind", ""))
        scene_id = clean_text(scene.get("scene_id", ""))
        if kind == current_kind:
            current_count += 1
            current_end = scene_id
        else:
            if current_kind and current_count > max_same:
                runs.append({"render_kind": current_kind, "count": current_count, "start_scene_id": current_start, "end_scene_id": current_end})
            current_kind = kind
            current_start = scene_id
            current_end = scene_id
            current_count = 1
    if current_kind and current_count > max_same:
        runs.append({"render_kind": current_kind, "count": current_count, "start_scene_id": current_start, "end_scene_id": current_end})
    return runs


def _story_planner_fallbacks(visual_scene_plan: dict[str, Any]) -> list[str]:
    fallback_ids: list[str] = []
    for call in visual_scene_plan.get("planning_calls", []):
        metadata = call.get("metadata") if isinstance(call.get("metadata"), dict) else {}
        if call.get("module_name") == STORY_VISUAL_PLANNER_PROMPT_MODULE and metadata.get("fallback_used"):
            story_id = clean_text(metadata.get("story_id", ""))
            if story_id:
                fallback_ids.append(story_id)
    for plan in visual_scene_plan.get("story_plans", []):
        if not isinstance(plan, dict):
            continue
        if plan.get("fallback_used") or "fallback" in clean_text(plan.get("visual_strategy", "")).lower():
            story_id = clean_text(plan.get("story_id", ""))
            if story_id:
                fallback_ids.append(story_id)
    return dedupe(fallback_ids)


def _build_summary(visual_scene_plan: dict[str, Any], llm_calls: list[dict[str, Any]], failure_reason: str) -> dict[str, Any]:
    scenes = visual_scene_plan.get("scene_timeline", [])
    kinds = [scene.get("render_kind", "") for scene in scenes]
    coverage = visual_scene_plan.get("coverage", {})
    story_planner_fallbacks = _story_planner_fallbacks(visual_scene_plan)
    story_planner_parse_errors = [
        call
        for call in visual_scene_plan.get("planning_calls", [])
        if clean_text(call.get("module_name", "")) == STORY_VISUAL_PLANNER_PROMPT_MODULE
        and (
            clean_text(call.get("parse_error", ""))
            or clean_text((call.get("metadata") if isinstance(call.get("metadata"), dict) else {}).get("parse_error", ""))
        )
    ]
    return {
        "script_word_count": safe_int(visual_scene_plan.get("source_script", {}).get("word_count"), 0),
        "voiceover_duration_seconds": safe_float(visual_scene_plan.get("audio_timeline", {}).get("duration_seconds"), 0.0),
        "story_count": len(visual_scene_plan.get("story_plans", [])),
        "story_section_count": len([section for section in visual_scene_plan.get("story_sections", []) if section.get("section_type") == "story"]),
        "scene_count": len(scenes),
        "visual_beat_count": len(visual_scene_plan.get("visual_beat_map", [])),
        "source_article_scene_count": kinds.count("source_article_scene"),
        "context_image_scene_count": kinds.count("context_image_scene"),
        "broll_video_scene_count": kinds.count("broll_video_scene"),
        "source_backed_scene_count": kinds.count("source_article_scene") + kinds.count("quote_or_claim_highlight_scene"),
        "logo_reveal_scene_count": kinds.count("logo_reveal_scene"),
        "kinetic_type_scene_count": kinds.count("kinetic_type_scene"),
        "bullet_build_scene_count": kinds.count("bullet_build_scene"),
        "quote_or_claim_highlight_scene_count": kinds.count("quote_or_claim_highlight_scene"),
        "entity_compare_scene_count": kinds.count("entity_compare_scene"),
        "recap_sequence_scene_count": kinds.count("recap_sequence_scene"),
        "data_counter_scene_count": kinds.count("data_counter_scene"),
        "trend_line_scene_count": kinds.count("trend_line_scene"),
        "bar_chart_scene_count": kinds.count("bar_chart_scene"),
        "bar_race_scene_count": kinds.count("bar_race_scene"),
        "ranked_list_scene_count": kinds.count("ranked_list_scene"),
        "benchmark_delta_scene_count": kinds.count("benchmark_delta_scene"),
        "ecosystem_map_scene_count": kinds.count("ecosystem_map_scene"),
        "architecture_flow_scene_count": kinds.count("architecture_flow_scene"),
        "process_zoom_scene_count": kinds.count("process_zoom_scene"),
        "browser_walkthrough_scene_count": kinds.count("browser_walkthrough_scene"),
        "decision_tree_scene_count": kinds.count("decision_tree_scene"),
        "capability_matrix_scene_count": kinds.count("capability_matrix_scene"),
        "timeline_zoom_scene_count": kinds.count("timeline_zoom_scene"),
        "document_stack_scene_count": kinds.count("document_stack_scene"),
        "signal_radar_scene_count": kinds.count("signal_radar_scene"),
        "interface_transform_scene_count": kinds.count("interface_transform_scene"),
        "transition_stinger_scene_count": kinds.count("transition_stinger_scene"),
        "text_like_scene_count": len([kind for kind in kinds if kind in TEXT_LIKE_RENDER_KINDS]),
        "text_like_duration_seconds": round(
            sum(
                safe_float(scene.get("duration_seconds"), 0.0)
                for scene in scenes
                if scene.get("render_kind") in TEXT_LIKE_RENDER_KINDS
            ),
            2,
        ),
        "llm_call_count": len(llm_calls),
        "story_planner_fallback_count": len(story_planner_fallbacks),
        "story_planner_fallback_story_ids": story_planner_fallbacks,
        "story_planner_parse_error_count": len(story_planner_parse_errors),
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
            "ready_for_visual_media_discovery": False,
            "next_module": NEXT_MODULE,
            "selected_format": selected_format,
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _resolve_script_provenance(
    request: VisualPlannerRequest,
    script_text: str,
    script_source: str,
) -> dict[str, Any]:
    script_generation = request.input.script_generation
    if script_generation is None:
        return build_text_script_provenance(
            script_text,
            run_id=request.run.run_id,
            script_source=script_source or "input.script_text",
        )
    require_matching_run_id(request.run.run_id, script_generation.data.run_id, "script_generation")
    return validate_script_provenance(
        script_generation.data.script_package,
        run_id=request.run.run_id,
        upstream_run_id=script_generation.data.run_id,
    )


def _validate_voiceover_for_script(
    voiceover_package: dict[str, Any] | None,
    *,
    run_id: str,
    script_provenance: dict[str, Any],
    script_sections: list[dict[str, Any]],
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
    voiceover_fingerprint = clean_text((provenance or {}).get("voiceover_fingerprint"))
    if not voiceover_fingerprint:
        raise ValueError("voiceover.provenance.voiceover_fingerprint is required")
    if script_sections:
        expected_beats = {
            clean_text(beat.get("beat_id")): clean_text(beat.get("narration_text"))
            for section in script_sections
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
        if set(actual_beats) != set(expected_beats):
            missing = sorted(set(expected_beats) - set(actual_beats))
            extra = sorted(set(actual_beats) - set(expected_beats))
            raise ValueError(f"voiceover beat IDs do not match the script; missing={missing[:8]}, extra={extra[:8]}")
        changed = [beat_id for beat_id, text in expected_beats.items() if actual_beats.get(beat_id) != text]
        if changed:
            raise ValueError(f"voiceover narration does not match the current script beats: {changed[:8]}")
    return provenance


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
        sections = package.get("sections") if isinstance(package.get("sections"), list) else []
        projected_sections: list[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            beats = section.get("beats") if isinstance(section.get("beats"), list) else []
            text = " ".join(clean_text(beat.get("narration_text", "")) for beat in beats if isinstance(beat, dict)).strip()
            if not text:
                text = clean_text(section.get("narration_text", ""))
            if text:
                projected_sections.append(text)
        if projected_sections:
            projected = "\n\n".join(projected_sections)
            full_script = clean_text(package.get("full_script", ""))
            if full_script and clean_text(projected) != full_script:
                raise ValueError("script_package.full_script does not match its deterministic section/beat projection")
            return projected
        return str(package.get("full_script", "") or "").strip()
    return str(request.input.script_text or "").strip()


def _build_script_units(
    *,
    script_text: str,
    voiceover_package: dict[str, Any] | None,
    script_sections: list[dict[str, Any]],
    words_per_minute: int,
) -> list[dict[str, Any]]:
    chunks = voiceover_chunks(voiceover_package)
    if chunks:
        return chunks
    if script_sections:
        return _estimated_script_beat_units(script_sections, words_per_minute)
    return split_script_units(
        script_text,
        words_per_minute=words_per_minute,
    )


def _estimated_script_beat_units(
    sections: list[dict[str, Any]],
    words_per_minute: int,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    cursor = 0.0
    for section in sections:
        section_id = clean_text(section.get("section_id", ""))
        beats = [beat for beat in section.get("beats", []) if isinstance(beat, dict)]
        if not beats:
            beats = [
                {
                    "beat_id": f"{section_id}_beat_01",
                    "beat_type": clean_text(section.get("section_type", "")),
                    "narration_text": clean_text(section.get("narration_text", "")),
                    "source_record_keys": list(section.get("used_source_record_keys", [])),
                    "visual_brief": {},
                }
            ]
        for beat in beats:
            text = clean_text(beat.get("narration_text", ""))
            if not text:
                continue
            words = count_words(text)
            duration = safe_float(beat.get("estimated_seconds"), 0.0)
            if duration <= 0:
                duration = words / max(1, words_per_minute) * 60.0
            end = cursor + max(0.01, duration)
            beat_id = clean_text(beat.get("beat_id", "")) or f"{section_id}_beat_{len(units) + 1:02d}"
            units.append(
                {
                    "unit_id": beat_id,
                    "order": len(units) + 1,
                    "text": text,
                    "word_count": words,
                    "start_seconds": round(cursor, 2),
                    "end_seconds": round(end, 2),
                    "duration_seconds": round(end - cursor, 2),
                    "timing_source": "script_beat_estimate",
                    "section_id": section_id,
                    "section_type": clean_text(section.get("section_type", "")),
                    "story_id": clean_text(section.get("story_id", "")),
                    "story_title": clean_text(section.get("story_title", "")),
                    "beat_id": beat_id,
                    "beat_type": clean_text(beat.get("beat_type", "")),
                    "source_record_keys": list(beat.get("source_record_keys", [])),
                    "visual_brief": dict(beat.get("visual_brief") or {}),
                }
            )
            cursor = end
    return units


def _attach_script_beat_context(
    script_units: list[dict[str, Any]],
    request: VisualPlannerRequest,
) -> list[dict[str, Any]]:
    script_generation = request.input.script_generation
    if script_generation is None:
        return script_units
    sections = script_generation.data.script_package.get("sections")
    if not isinstance(sections, list):
        return script_units
    beat_index: dict[str, dict[str, Any]] = {}
    section_index: dict[str, dict[str, Any]] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_id = clean_text(section.get("section_id", ""))
        if section_id:
            section_index[section_id] = section
        for beat in section.get("beats", []):
            if not isinstance(beat, dict):
                continue
            beat_id = clean_text(beat.get("beat_id", ""))
            if beat_id:
                beat_index[beat_id] = beat
    enriched: list[dict[str, Any]] = []
    for unit in script_units:
        item = dict(unit)
        beat = beat_index.get(clean_text(item.get("beat_id") or item.get("unit_id")), {})
        section = section_index.get(clean_text(item.get("section_id", "")), {})
        if beat:
            item["beat_id"] = beat.get("beat_id", item.get("beat_id", ""))
            item["beat_type"] = beat.get("beat_type", item.get("beat_type", ""))
            item["source_record_keys"] = list(beat.get("source_record_keys", []))
            item["visual_brief"] = dict(beat.get("visual_brief") or {})
        if section:
            item["section_type"] = section.get("section_type", item.get("section_type", ""))
            item["story_id"] = section.get("story_id", item.get("story_id", ""))
            item["story_title"] = section.get("story_title", item.get("story_title", ""))
            item["title_card"] = section.get("title_card")
        enriched.append(item)
    return enriched


def _script_story_asset_hints(request: VisualPlannerRequest) -> dict[str, dict[str, Any]]:
    script_generation = request.input.script_generation
    if script_generation is None:
        return {}
    raw = script_generation.data.script_package.get("story_asset_hints")
    if not isinstance(raw, list):
        return {}
    return {
        clean_text(item.get("story_id", "")): dict(item)
        for item in raw
        if isinstance(item, dict) and clean_text(item.get("story_id", ""))
    }


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
    timing_source = "voiceover_package"
    if chunks:
        timing_source = clean_text(chunks[0].get("timing_source", "")) or "voiceover_chunks"
    return {
        "timing_source": timing_source,
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
    duration_policy = video_packet.get("duration_policy") if isinstance(video_packet.get("duration_policy"), dict) else {}
    return safe_float(duration_policy.get("configured_ceiling_seconds"), 0.0)


def _video_packet_summary(video_packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_type": clean_text(video_packet.get("packet_type", "")),
        "duration_policy": video_packet.get("duration_policy") or {
            "mode": "content_driven",
            "configured_ceiling_seconds": video_packet.get("target_duration_seconds"),
            "timing_source_of_truth": "voiceover",
        },
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
            "beat_id": unit.get("beat_id", ""),
            "beat_type": unit.get("beat_type", ""),
            "source_record_keys": unit.get("source_record_keys", []),
            "visual_brief": unit.get("visual_brief", {}),
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
    identity = source_index.get("story_identity_by_id", {}).get(story_id, {})
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


def _points_from_text(text: str, *, max_points: int = 4, max_chars: int = 64) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return ["AI is moving into products"]
    sentences = [clean_text(item) for item in re.split(r"(?<=[.!?])\s+", normalized) if clean_text(item)]
    points = [short_text(sentence, max_chars).strip(" ,.;:") for sentence in sentences if count_words(sentence) >= 3]
    if len(points) < max_points:
        chunks = re.split(r"\b(?:and|but|while|because|with|where)\b|[,;:]", normalized)
        points.extend(short_text(clean_text(chunk), max_chars).strip(" ,.;:") for chunk in chunks if count_words(chunk) >= 3)
    return dedupe([point for point in points if point])[:max_points] or [_short_phrase(normalized)]


def _excerpt_has_metric(text: str) -> bool:
    return bool(METRIC_RE.search(clean_text(text)))


def _excerpt_has_trend(text: str) -> bool:
    return bool(TREND_RE.search(clean_text(text)))


def _excerpt_has_flow(text: str) -> bool:
    return bool(FLOW_RE.search(clean_text(text)))


def _excerpt_has_metric_comparison(text: str) -> bool:
    normalized = clean_text(text).lower()
    return _excerpt_has_metric(normalized) and any(
        token in normalized
        for token in [
            "compared",
            "versus",
            "vs",
            "than",
            "across",
            "between",
            "from",
            "to",
            "cost",
            "latency",
            "price",
            "funding",
            "valuation",
            "adoption",
        ]
    )


def _excerpt_has_benchmark_delta(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(
        token in normalized
        for token in [
            "delta",
            "benchmark",
            "speedup",
            "speed up",
            "faster",
            "slower",
            "lower cost",
            "cost reduction",
            "reduced",
            "improved",
            "before",
            "after",
            "accuracy",
            "latency",
            "performance",
        ]
    ) and (_excerpt_has_metric(normalized) or any(token in normalized for token in ["faster", "slower", "improved", "reduced"]))


def _excerpt_has_race(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(
        token in normalized
        for token in [
            "race",
            "leader",
            "leading",
            "catching up",
            "overtake",
            "ahead",
            "behind",
            "competition",
            "competitive",
            "momentum",
            "rank",
            "market share",
        ]
    )


def _excerpt_has_ranking(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(
        token in normalized
        for token in [
            "top ",
            "first",
            "second",
            "third",
            "rank",
            "ranking",
            "priority",
            "biggest",
            "most important",
            "three things",
            "four things",
            "five things",
            "reasons",
        ]
    )


def _excerpt_has_process_focus(text: str) -> bool:
    normalized = clean_text(text).lower()
    return _excerpt_has_flow(normalized) and any(
        token in normalized
        for token in [
            "inside",
            "under the hood",
            "where",
            "step",
            "critical",
            "focus",
            "the key part",
            "what matters",
            "this is where",
        ]
    )


def _excerpt_has_browser_context(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(
        token in normalized
        for token in [
            "article",
            "post",
            "blog",
            "docs",
            "documentation",
            "release page",
            "product page",
            "github",
            "paper",
            "report",
            "webpage",
            "page says",
            "source",
        ]
    )


def _excerpt_has_decision_tree(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(
        token in normalized
        for token in [
            "choose",
            "decision",
            "if ",
            "route",
            "routing",
            "gate",
            "safety",
            "policy",
            "tradeoff",
            "option",
            "branch",
            "whether",
        ]
    )


def _excerpt_has_capability_matrix(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(token in normalized for token in ["speed", "cost", "context", "multimodal", "tooling", "capability", "compare", "tradeoff", "model"]) and any(
        token in normalized for token in ["versus", "vs", "compare", "model", "platform", "product", "capability"]
    )


def _excerpt_has_timeline_zoom(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(
        token in normalized
        for token in [
            "timeline",
            "first",
            "then",
            "next",
            "after",
            "before",
            "launch",
            "announced",
            "follow-up",
            "week",
            "month",
            "year",
        ]
    )


def _excerpt_has_document_stack(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(token in normalized for token in ["paper", "report", "docs", "documentation", "github", "issue", "release notes", "research", "source", "filing"])


def _excerpt_has_signal_radar(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(token in normalized for token in ["signal", "watch", "emerging", "risk", "trend", "early", "weak signal", "radar", "monitor"])


def _excerpt_has_interface_transform(text: str) -> bool:
    normalized = clean_text(text).lower()
    return any(token in normalized for token in ["from chat", "chatbot", "interface", "workflow", "manual", "automated", "agent", "tool", "productivity", "ui"]) and any(
        token in normalized for token in ["from", "to", "into", "becoming", "turns", "moves"]
    )


def _items_have_race_values(items: list[Any]) -> bool:
    for item in items:
        if not isinstance(item, dict):
            continue
        if clean_text(item.get("start_value", "")) and clean_text(item.get("end_value", "")):
            return True
    return False


def _metrics_from_text(text: str) -> list[dict[str, str]]:
    normalized = clean_text(text)
    values = [match.group(1).strip() for match in METRIC_RE.finditer(normalized)]
    metrics = []
    for value in dedupe(values)[:3]:
        metrics.append(
            {
                "label": _metric_label_from_text(normalized),
                "value": short_text(value, 18),
                "unit": "",
                "context": short_text(_short_phrase(normalized), 58),
            }
        )
    return metrics or [
        {
            "label": "Scale",
            "value": "AI",
            "unit": "",
            "context": short_text(_short_phrase(normalized), 58),
        }
    ]


def _metrics_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    metrics: list[dict[str, str]] = []
    for item in draft.get("metrics", []):
        if not isinstance(item, dict):
            continue
        value = short_text(clean_text(item.get("value", "")), 18)
        label = short_text(clean_text(item.get("label", "")) or clean_text(item.get("name", "")) or _metric_label_from_text(script_excerpt), 32)
        if value:
            metrics.append(
                {
                    "label": label,
                    "value": value,
                    "unit": short_text(clean_text(item.get("unit", "")), 12),
                    "context": short_text(clean_text(item.get("context", "")) or script_excerpt, 58),
                }
            )
    if clean_text(draft.get("metric_value", "")):
        metrics.append(
            {
                "label": short_text(clean_text(draft.get("metric_label", "")) or _metric_label_from_text(script_excerpt), 32),
                "value": short_text(clean_text(draft.get("metric_value", "")), 18),
                "unit": short_text(clean_text(draft.get("metric_unit", "")), 12),
                "context": short_text(clean_text(draft.get("metric_context", "")) or script_excerpt, 58),
            }
        )
    return metrics or _metrics_from_text(script_excerpt)


def _bars_from_text(text: str) -> list[dict[str, str]]:
    metrics = _metrics_from_text(text)
    if len(metrics) >= 2:
        return [
            {
                "label": short_text(metric.get("label", "") or f"Signal {index}", 28),
                "value": short_text(metric.get("value", ""), 18),
                "display_value": short_text(metric.get("value", ""), 18),
                "context": short_text(metric.get("context", ""), 42),
            }
            for index, metric in enumerate(metrics, start=1)
        ]
    points = _points_from_text(text, max_points=4, max_chars=34)
    values = ["82", "64", "48", "36"]
    return [
        {
            "label": short_text(point, 28),
            "value": values[index],
            "display_value": values[index],
            "context": "relative signal",
        }
        for index, point in enumerate(points[:4])
    ]


def _bars_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    bars: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("bars", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", "")) or f"Signal {index}"
        value = clean_text(item.get("value", "")) or clean_text(item.get("display_value", ""))
        if not value:
            continue
        bars.append(
            {
                "label": short_text(label, 30),
                "value": short_text(value, 18),
                "display_value": short_text(clean_text(item.get("display_value", "")) or value, 18),
                "context": short_text(clean_text(item.get("context", "")) or clean_text(item.get("detail", "")), 42),
            }
        )
    if bars:
        return bars
    metrics = _metrics_from_draft(draft, script_excerpt)
    if len(metrics) >= 2:
        return [
            {
                "label": short_text(metric.get("label", "") or f"Signal {index}", 30),
                "value": short_text(metric.get("value", ""), 18),
                "display_value": short_text(metric.get("value", ""), 18),
                "context": short_text(metric.get("context", ""), 42),
            }
            for index, metric in enumerate(metrics, start=1)
            if metric.get("value")
        ]
    return _bars_from_text(script_excerpt)


def _ranked_items_from_text(text: str) -> list[dict[str, str | int]]:
    points = _points_from_text(text, max_points=5, max_chars=46)
    return [
        {
            "rank": index,
            "label": short_text(point, 34),
            "value": "",
            "detail": short_text(point, 54),
        }
        for index, point in enumerate(points, start=1)
    ]


def _ranked_items_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str | int]]:
    items: list[dict[str, str | int]] = []
    for index, item in enumerate(draft.get("items", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", ""))
        detail = clean_text(item.get("detail", "")) or clean_text(item.get("context", ""))
        value = clean_text(item.get("value", "")) or clean_text(item.get("display_value", ""))
        if label or detail or value:
            items.append(
                {
                    "rank": safe_int(item.get("rank"), index) or index,
                    "label": short_text(label or detail or value, 34),
                    "value": short_text(value, 18),
                    "detail": short_text(detail or label, 54),
                }
            )
    return items or _ranked_items_from_text(script_excerpt)


def _race_items_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("items", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", "")) or f"Signal {index}"
        start_value = clean_text(item.get("start_value", ""))
        end_value = clean_text(item.get("end_value", "")) or clean_text(item.get("value", ""))
        if label and (start_value or end_value):
            fallback_start = str(max(12, 36 - index * 4))
            fallback_end = str(max(35, 92 - index * 9))
            items.append(
                {
                    "label": short_text(label, 30),
                    "start_value": short_text(start_value or fallback_start, 18),
                    "end_value": short_text(end_value or fallback_end, 18),
                    "display_value": short_text(clean_text(item.get("display_value", "")) or end_value or fallback_end, 18),
                }
            )
    if items:
        return items
    entities = dedupe([clean_text(item) for item in draft.get("entities", []) if clean_text(item)])[:5]
    if not entities:
        entities = [item["label"] for item in _ranked_items_from_text(script_excerpt)[:4]]
    return [
        {
            "label": short_text(entity, 30),
            "start_value": str(max(14, 38 - index * 4)),
            "end_value": str(max(36, 92 - index * 8)),
            "display_value": str(max(36, 92 - index * 8)),
        }
        for index, entity in enumerate(entities, start=1)
    ]


def _benchmarks_from_text(text: str) -> list[dict[str, str]]:
    metrics = _metrics_from_text(text)
    if metrics and metrics[0].get("value"):
        value = metrics[0]["value"]
        return [
            {
                "label": short_text(_metric_label_from_text(text), 28),
                "before": "baseline",
                "after": value,
                "delta": short_text(value, 18),
                "unit": "",
                "context": short_text(_short_phrase(text), 48),
            }
        ]
    return [
        {
            "label": "Performance",
            "before": "before",
            "after": "after",
            "delta": "shift",
            "unit": "",
            "context": short_text(_short_phrase(text), 48),
        }
    ]


def _benchmarks_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    benchmarks: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("benchmarks", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", "")) or f"Delta {index}"
        before = clean_text(item.get("before", ""))
        after = clean_text(item.get("after", ""))
        delta = clean_text(item.get("delta", ""))
        if label and (before or after or delta):
            benchmarks.append(
                {
                    "label": short_text(label, 28),
                    "before": short_text(before or "before", 18),
                    "after": short_text(after or "after", 18),
                    "delta": short_text(delta or after or "shift", 18),
                    "unit": short_text(clean_text(item.get("unit", "")), 12),
                    "context": short_text(clean_text(item.get("context", "")) or clean_text(item.get("detail", "")) or script_excerpt, 48),
                }
            )
    return benchmarks or _benchmarks_from_text(script_excerpt)


def _walkthrough_steps_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    steps = _flow_steps_from_draft({"steps": draft.get("walkthrough_steps", [])}, script_excerpt)
    if steps:
        return steps
    return [
        {"label": "Open source", "detail": "show page context"},
        {"label": "Find claim", "detail": "zoom to the key section"},
        {"label": "Connect story", "detail": "explain why it matters"},
    ]


def _decision_branches_from_text(text: str) -> list[dict[str, str]]:
    points = _points_from_text(text, max_points=4, max_chars=42)
    defaults = ["Use model", "Call tool", "Ask human", "Block action"]
    branches = points if len(points) >= 2 else defaults
    return [{"label": short_text(item, 30), "detail": "decision path"} for item in branches[:5]]


def _decision_branches_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    branches = _flow_steps_from_draft({"steps": draft.get("branches", [])}, script_excerpt)
    return branches or _decision_branches_from_text(script_excerpt)


def _matrix_columns_from_draft(draft: dict[str, Any]) -> list[str]:
    columns = [short_text(clean_text(item), 18) for item in draft.get("columns", []) if clean_text(item)]
    return columns[:5] or ["Speed", "Cost", "Context", "Tools"]


def _matrix_rows_from_text(text: str) -> list[dict[str, str]]:
    entities = re.findall(r"\b[A-Z][A-Za-z0-9&.-]{2,}(?:\s+[A-Z][A-Za-z0-9&.-]{2,})?\b", clean_text(text))
    labels = dedupe([short_text(item, 24) for item in entities])[:4] or ["Option A", "Option B", "Option C"]
    values = [
        {"speed": "high", "cost": "med", "context_window": "wide", "multimodal": "yes", "tooling": "strong"},
        {"speed": "med", "cost": "low", "context_window": "med", "multimodal": "partial", "tooling": "growing"},
        {"speed": "high", "cost": "high", "context_window": "wide", "multimodal": "yes", "tooling": "custom"},
        {"speed": "low", "cost": "low", "context_window": "narrow", "multimodal": "no", "tooling": "basic"},
    ]
    return [{"label": label, **values[index % len(values)], "detail": "relative capability"} for index, label in enumerate(labels)]


def _matrix_rows_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("rows", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", "")) or f"Option {index}"
        rows.append(
            {
                "label": short_text(label, 24),
                "speed": short_text(clean_text(item.get("speed", "")) or "med", 14),
                "cost": short_text(clean_text(item.get("cost", "")) or "med", 14),
                "context_window": short_text(clean_text(item.get("context_window", "")) or clean_text(item.get("context", "")) or "med", 14),
                "multimodal": short_text(clean_text(item.get("multimodal", "")) or "partial", 14),
                "tooling": short_text(clean_text(item.get("tooling", "")) or "growing", 16),
                "detail": short_text(clean_text(item.get("detail", "")), 36),
            }
        )
    return rows or _matrix_rows_from_text(script_excerpt)


def _timeline_events_from_text(text: str) -> list[dict[str, str]]:
    points = _points_from_text(text, max_points=4, max_chars=44)
    labels = points if len(points) >= 2 else ["Signal appears", "Momentum builds", "Critical shift"]
    date_matches = [match.group(1) for match in METRIC_RE.finditer(text) if any(unit in match.group(1).lower() for unit in ["day", "week", "month", "year"])]
    return [
        {
            "label": short_text(label, 34),
            "date": short_text(date_matches[index] if index < len(date_matches) else f"T+{index}", 14),
            "detail": short_text(label, 46),
            "importance": "focus" if index == min(1, len(labels) - 1) else "context",
        }
        for index, label in enumerate(labels[:5])
    ]


def _timeline_events_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("events", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or f"Event {index}"
        events.append(
            {
                "label": short_text(label, 34),
                "date": short_text(clean_text(item.get("date", "")) or f"T+{index - 1}", 14),
                "detail": short_text(clean_text(item.get("detail", "")) or label, 46),
                "importance": short_text(clean_text(item.get("importance", "")) or ("focus" if index == 2 else "context"), 18),
            }
        )
    return events or _timeline_events_from_text(script_excerpt)


def _documents_from_text(text: str) -> list[dict[str, str]]:
    points = _points_from_text(text, max_points=4, max_chars=46)
    types = ["Report", "Docs", "Release", "Research"]
    return [
        {
            "title": short_text(point, 42),
            "source": "selected source",
            "document_type": types[index % len(types)],
            "detail": "evidence layer",
            "status": "referenced",
        }
        for index, point in enumerate(points)
    ]


def _documents_from_story_source(story: dict[str, Any], record: dict[str, Any], text: str) -> list[dict[str, str]]:
    documents = []
    for item in story.get("records", [])[:5]:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title", ""))
        if title:
            documents.append(
                {
                    "title": short_text(title, 42),
                    "source": short_text(clean_text(item.get("source_name") or item.get("source") or "source"), 22),
                    "document_type": short_text(clean_text(item.get("source_group", "")) or "Source", 18),
                    "detail": short_text(clean_text(item.get("summary") or item.get("description") or ""), 46),
                    "status": "selected",
                }
            )
    if documents:
        return documents
    if record:
        return [
            {
                "title": short_text(clean_text(record.get("title", "")) or _short_phrase(text), 42),
                "source": short_text(clean_text(record.get("source_name", "")) or "source", 22),
                "document_type": short_text(clean_text(record.get("source_group", "")) or "Source", 18),
                "detail": "selected record",
                "status": "selected",
            }
        ]
    return _documents_from_text(text)


def _documents_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("documents", []), start=1):
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title", "")) or f"Document {index}"
        documents.append(
            {
                "title": short_text(title, 42),
                "source": short_text(clean_text(item.get("source", "")) or "source", 22),
                "document_type": short_text(clean_text(item.get("document_type", "")) or "Doc", 18),
                "detail": short_text(clean_text(item.get("detail", "")), 46),
                "status": short_text(clean_text(item.get("status", "")) or "selected", 18),
            }
        )
    return documents or _documents_from_text(script_excerpt)


def _signals_from_text(text: str) -> list[dict[str, str]]:
    points = _points_from_text(text, max_points=6, max_chars=34)
    return [
        {
            "label": short_text(point, 28),
            "value": str(max(25, 88 - index * 9)),
            "display_value": "watch",
            "context": "signal",
        }
        for index, point in enumerate(points)
    ]


def _signals_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("signals", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", "")) or f"Signal {index}"
        signals.append(
            {
                "label": short_text(label, 28),
                "value": short_text(clean_text(item.get("value", "")) or str(max(25, 88 - index * 9)), 12),
                "display_value": short_text(clean_text(item.get("display_value", "")) or clean_text(item.get("value", "")) or "watch", 14),
                "context": short_text(clean_text(item.get("context", "")) or clean_text(item.get("detail", "")) or "signal", 22),
            }
        )
    return signals or _signals_from_text(script_excerpt)


def _flow_step_labels_from_text(text: str) -> list[str]:
    return [step["label"] for step in _flow_steps_from_text(text)]


def _interface_panel_from_draft(value: Any, fallback_label: str, script_excerpt: str, *, flow: bool = False) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    items = [short_text(clean_text(item), 34) for item in source.get("items", []) if clean_text(item)]
    if not items:
        items = _flow_step_labels_from_text(script_excerpt)[:3] if flow else _points_from_text(script_excerpt, max_points=3, max_chars=34)
    return {
        "label": short_text(clean_text(source.get("label", "")) or fallback_label, 28),
        "detail": short_text(clean_text(source.get("detail", "")) or ("AI-assisted workflow" if flow else "manual workflow"), 44),
        "items": items[:4],
    }


def _metric_value_from_text(text: str) -> str:
    match = METRIC_RE.search(clean_text(text))
    return short_text(match.group(1), 18) if match else "AI"


def _metric_label_from_text(text: str) -> str:
    lower = clean_text(text).lower()
    if any(token in lower for token in ["speed", "faster", "training", "precision", "bit", "fp"]):
        return "Training signal"
    if any(token in lower for token in ["ipo", "market", "valuation", "public", "funding"]):
        return "Market signal"
    if any(token in lower for token in ["year", "month", "day", "timeline", "timing"]):
        return "Timeline"
    if any(token in lower for token in ["adoption", "developers", "users", "enterprise"]):
        return "Adoption signal"
    return "Key metric"


def _trend_direction_from_text(text: str) -> str:
    lower = clean_text(text).lower()
    if any(token in lower for token in ["fall", "decline", "drop", "behind", "slower"]):
        return "falling"
    if any(token in lower for token in ["volatile", "uncertain", "pressure"]):
        return "pressure_building"
    if any(token in lower for token in ["jump", "surge", "skyrocket", "accelerat"]):
        return "flat_then_jump"
    return "rising"


def _annotations_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[str]:
    annotations = [short_text(clean_text(item), 42) for item in draft.get("annotations", []) if clean_text(item)]
    if len(annotations) < 2:
        annotations.extend(_points_from_text(script_excerpt, max_points=3 - len(annotations), max_chars=42))
    return dedupe([item for item in annotations if item])[:3]


def _entities_for_story(
    story_id: str,
    source_index: dict[str, Any],
    text: str,
    extra_entities: list[Any] | None = None,
) -> list[str]:
    identity = source_index.get("story_identity_by_id", {}).get(story_id, {})
    candidates = [
        clean_text(identity.get("primary_entity", "")),
        clean_text(identity.get("owning_org", "")),
        clean_text(identity.get("product_or_project", "")),
    ]
    candidates.extend(clean_text(item) for item in (extra_entities or []) if clean_text(item))
    stop_tokens = {"the", "this", "that", "when", "today", "next", "now"}
    for token in re.findall(r"\b[A-Z][A-Za-z0-9&.-]{2,}(?:\s+[A-Z][A-Za-z0-9&.-]{2,})?\b", clean_text(text)):
        if token.lower() not in stop_tokens:
            candidates.append(token)
    return dedupe([short_text(item, 34) for item in candidates if item])[:6]


def _nodes_from_entities(entities: list[str]) -> list[dict[str, str]]:
    nodes = []
    for index, entity in enumerate(dedupe([clean_text(item) for item in entities if clean_text(item)])[:6], start=1):
        nodes.append(
            {
                "id": f"node_{index}",
                "label": short_text(entity, 30),
                "role": "focus" if index == 1 else "connected",
            }
        )
    return nodes or [
        {"id": "node_1", "label": "AI", "role": "focus"},
        {"id": "node_2", "label": "Developers", "role": "connected"},
        {"id": "node_3", "label": "Users", "role": "connected"},
    ]


def _nodes_from_draft(draft: dict[str, Any], fallback_entities: list[str]) -> list[dict[str, str]]:
    nodes: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("nodes", []), start=1):
        if isinstance(item, dict):
            label = clean_text(item.get("label", "")) or clean_text(item.get("name", ""))
            role = clean_text(item.get("role", "")) or ("focus" if index == 1 else "connected")
        else:
            label = clean_text(item)
            role = "focus" if index == 1 else "connected"
        if label:
            nodes.append({"id": clean_text(item.get("id", "")) if isinstance(item, dict) else f"node_{index}", "label": short_text(label, 30), "role": short_text(role, 24)})
    return nodes or _nodes_from_entities(fallback_entities)


def _edges_from_entities(entities: list[str]) -> list[dict[str, str]]:
    nodes = _nodes_from_entities(entities)
    if len(nodes) < 2:
        return []
    focus = nodes[0]["id"]
    return [{"from": focus, "to": node["id"], "label": "connects"} for node in nodes[1:]]


def _edges_from_draft(draft: dict[str, Any], nodes: list[dict[str, str]]) -> list[dict[str, str]]:
    node_ids = {node["id"] for node in nodes}
    edges: list[dict[str, str]] = []
    for item in draft.get("edges", []):
        if not isinstance(item, dict):
            continue
        source = clean_text(item.get("from", "")) or clean_text(item.get("source", ""))
        target = clean_text(item.get("to", "")) or clean_text(item.get("target", ""))
        if source in node_ids and target in node_ids and source != target:
            edges.append({"from": source, "to": target, "label": short_text(clean_text(item.get("label", "")) or "connects", 22)})
    if edges:
        return edges[:8]
    if len(nodes) < 2:
        return []
    focus = nodes[0]["id"]
    return [{"from": focus, "to": node["id"], "label": "connects"} for node in nodes[1:]]


def _flow_steps_from_text(text: str) -> list[dict[str, str]]:
    normalized = clean_text(text)
    lower = normalized.lower()
    if "sdk" in lower or "developer" in lower:
        labels = ["Developer app", "SDK", "Model call", "User result"]
    elif "training" in lower or "precision" in lower or "model" in lower:
        labels = ["Data", "Training stack", "Model", "Output"]
    elif "agent" in lower or "workflow" in lower:
        labels = ["Task", "Agent", "Tools", "Outcome"]
    else:
        points = _points_from_text(normalized, max_points=4, max_chars=28)
        labels = points if len(points) >= 2 else ["Input", "System", "Output"]
    return [{"label": short_text(label, 28), "detail": ""} for label in labels[:6]]


def _flow_steps_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for item in draft.get("steps", []):
        if isinstance(item, dict):
            label = clean_text(item.get("label", "")) or clean_text(item.get("name", ""))
            detail = clean_text(item.get("detail", "")) or clean_text(item.get("description", ""))
        else:
            label = clean_text(item)
            detail = ""
        if label:
            steps.append({"label": short_text(label, 28), "detail": short_text(detail, 44)})
    return steps or _flow_steps_from_text(script_excerpt)


def _focus_step_from_steps(steps: list[dict[str, str]]) -> str:
    if not steps:
        return "Key step"
    if len(steps) >= 3:
        return clean_text(steps[1].get("label", "")) or clean_text(steps[2].get("label", "")) or "Key step"
    return clean_text(steps[-1].get("label", "")) or "Key step"


def _focus_step_from_text(text: str) -> str:
    return _focus_step_from_steps(_flow_steps_from_text(text))


def _default_visual_intent(render_kind: str) -> str:
    if render_kind == "source_article_scene":
        return "Show the source article as visual proof for the narration beat."
    if render_kind == "context_image_scene":
        return "Show a real contextual image that makes the spoken subject tangible without competing text."
    if render_kind == "broll_video_scene":
        return "Show short real-world b-roll that directly depicts the environment, action, or object in the narration."
    if render_kind == "quote_or_claim_highlight_scene":
        return "Show a source-backed claim as a highlighted editorial callout."
    if render_kind == "logo_reveal_scene":
        return "Introduce or contrast the entity with a logo-driven motion moment."
    if render_kind == "entity_compare_scene":
        return "Compare the key entities or platforms in a motion graphic."
    if render_kind == "bullet_build_scene":
        return "Reveal the narration points one by one as a readable build."
    if render_kind == "recap_sequence_scene":
        return "Turn the closing or transition into a paced recap sequence."
    if render_kind == "data_counter_scene":
        return "Turn a key number or scale cue into an animated metric graphic."
    if render_kind == "trend_line_scene":
        return "Show momentum, pressure, or direction of change with a stylized trend graphic."
    if render_kind == "bar_chart_scene":
        return "Compare concrete values or relative signals with bold animated bars."
    if render_kind == "bar_race_scene":
        return "Show competitive momentum or before-to-after rank movement as animated bars."
    if render_kind == "ranked_list_scene":
        return "Turn an ordered set of implications or takeaways into a punchy ranked graphic."
    if render_kind == "benchmark_delta_scene":
        return "Make a before/after improvement, cost shift, speedup, or benchmark delta visually obvious."
    if render_kind == "ecosystem_map_scene":
        return "Map the entities, platforms, and relationships in a compact motion graphic."
    if render_kind == "architecture_flow_scene":
        return "Explain a technical workflow or integration as an animated flow diagram."
    if render_kind == "process_zoom_scene":
        return "Zoom into the critical step of a workflow while keeping the surrounding process visible."
    if render_kind == "browser_walkthrough_scene":
        return "Guide the viewer through a webpage, product page, or source page with scroll and focus motion."
    if render_kind == "decision_tree_scene":
        return "Show branching choices or routing logic as a highlighted decision path."
    if render_kind == "capability_matrix_scene":
        return "Compare products, models, or platforms across compact capability dimensions."
    if render_kind == "timeline_zoom_scene":
        return "Show a short event sequence and zoom into the moment that changes the story."
    if render_kind == "document_stack_scene":
        return "Show multiple documents or sources as a layered evidence stack."
    if render_kind == "signal_radar_scene":
        return "Frame emerging signals or watchlist items as a radar scan."
    if render_kind == "interface_transform_scene":
        return "Show a before-and-after workflow or interface transformation."
    if render_kind == "transition_stinger_scene":
        return "Use a short motion bumper to reset pacing between story beats."
    return "Turn the key narration phrase into kinetic on-screen text."
