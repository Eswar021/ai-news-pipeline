from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import math
import re
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

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

from ..asset_catalog.identity import catalog_identity_payload

from ..common import (
    clean_text,
    count_words,
    counter_dict,
    dedupe,
    first_url,
    format_timestamp,
    iso_now,
    meaningful_words,
    normalize_text_list,
    normalize_voiceover_package,
    safe_float,
    safe_int,
    screenshot_target_candidates,
    short_text,
    split_script_units,
    voiceover_chunks,
)
from ..payload_validation import (
    MEDIA_KINDS,
    prompt_payload_contract,
    validate_scene_payload,
)
from ..recipes import RECIPE_REGISTRY, recipe_specs_for_prompt
from .config import (
    BOOKEND_VISUAL_PLANNER_PROMPT_MODULE,
    EPISODE_DIRECTOR_PROMPT_MODULE,
    NEXT_MODULE,
    OLD_CARD_RENDER_KINDS,
    PACKAGE_TYPE,
    STORY_VISUAL_EDITOR_PROMPT_MODULE,
    STORY_VISUAL_PLANNER_PROMPT_MODULE,
    SUPPORTED_FORMAT,
    VISUAL_LLM_ROLES,
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
    "editorial_text_scene",
    "simple_explainer_scene",
    "story_transition_scene",
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
TEXT_LIKE_RENDER_KINDS = {
    "editorial_text_scene",
    "kinetic_type_scene",
    "bullet_build_scene",
    "recap_sequence_scene",
}
MERGEABLE_TEXT_RENDER_KINDS = {"kinetic_type_scene", "bullet_build_scene", "recap_sequence_scene"}
SOURCE_BACKED_RENDER_KINDS = {"source_article_scene", "quote_or_claim_highlight_scene"}
SOURCE_BOUND_RENDER_KINDS = SOURCE_BACKED_RENDER_KINDS | {"browser_walkthrough_scene"}
CATALOG_ASSET_TYPES_BY_RENDER_KIND = {
    "source_article_scene": {"source_page"},
    "quote_or_claim_highlight_scene": {"source_page"},
    "browser_walkthrough_scene": {"source_page"},
    "context_image_scene": {"source_image", "official_product_interface", "source_figure"},
    "broll_video_scene": {"source_video", "broll_video"},
    "logo_reveal_scene": {"logo"},
}
CATALOG_RENDER_KIND_BY_ASSET_TYPE = {
    "source_page": "source_article_scene",
    "source_image": "context_image_scene",
    "official_product_interface": "context_image_scene",
    "source_figure": "context_image_scene",
    "source_video": "broll_video_scene",
    "broll_video": "broll_video_scene",
    "logo": "logo_reveal_scene",
}
EVIDENCE_BOUND_RENDER_KINDS = {
    "simple_explainer_scene",
    "data_counter_scene",
    "trend_line_scene",
    "bar_chart_scene",
    "bar_race_scene",
    "ranked_list_scene",
    "benchmark_delta_scene",
    "ecosystem_map_scene",
    "architecture_flow_scene",
    "process_zoom_scene",
    "decision_tree_scene",
    "capability_matrix_scene",
    "timeline_zoom_scene",
    "document_stack_scene",
    "signal_radar_scene",
    "interface_transform_scene",
    "entity_compare_scene",
}
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
    "simple_explainer_scene",
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


class ProviderSceneDraft(BaseModel):
    """Compact provider contract; render-kind payloads are validated after decoding."""

    model_config = ConfigDict(extra="forbid")

    order: int
    start_unit_order: int
    end_unit_order: int
    render_kind: RenderKind
    script_excerpt: str
    visual_intent: str
    evidence_record_keys: list[str]
    evidence_truth_ids: list[str] = Field(
        description=(
            "Exact script-package truth IDs supporting numeric, quoted, comparative, or other "
            "evidence-bound payload details; return an empty list for transitions and purely editorial text."
        )
    )
    evidence_text: str
    grounding_basis: Literal[
        "selected_record",
        "script_beat",
        "editorial_transition",
        "context_media",
    ]
    payload_json: str = Field(
        description=(
            "A JSON-encoded object containing only the payload fields required by the "
            "chosen render kind in the supplied visual capability registry."
        )
    )
    reason: str

    @field_validator("order", "start_unit_order", "end_unit_order")
    @classmethod
    def order_fields_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("scene order and unit orders must be positive")
        return value

    @field_validator("payload_json")
    @classmethod
    def payload_json_must_encode_an_object(cls, value: str) -> str:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json must contain valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("payload_json must encode a JSON object")
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @model_validator(mode="after")
    def payload_must_match_render_contract(self) -> "ProviderSceneDraft":
        payload = json.loads(self.payload_json)
        errors = validate_scene_payload(self.render_kind, payload)
        if errors:
            raise ValueError("; ".join(errors))
        return self


class StoryVisualPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    visual_strategy: str
    key_entities: list[str] = Field(default_factory=list)
    scene_timeline: list[ProviderSceneDraft]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("story_id", "visual_strategy")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("story_id and visual_strategy must not be empty")
        return value

    @field_validator("scene_timeline")
    @classmethod
    def scene_timeline_must_not_be_empty(
        cls,
        value: list[ProviderSceneDraft],
    ) -> list[ProviderSceneDraft]:
        if not value:
            raise ValueError("scene_timeline must contain at least one scene")
        return value


class BookendSectionVisualPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_type: Literal["intro", "closing"]
    visual_strategy: str
    scene_timeline: list[ProviderSceneDraft]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("visual_strategy")
    @classmethod
    def visual_strategy_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("bookend visual_strategy must not be empty")
        return value

    @field_validator("scene_timeline")
    @classmethod
    def scene_timeline_must_not_be_empty(
        cls,
        value: list[ProviderSceneDraft],
    ) -> list[ProviderSceneDraft]:
        if not value:
            raise ValueError("bookend scene_timeline must contain at least one scene")
        return value


class EpisodeBookendVisualPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[BookendSectionVisualPlanDraft]

    @field_validator("sections")
    @classmethod
    def sections_must_not_be_empty(
        cls,
        value: list[BookendSectionVisualPlanDraft],
    ) -> list[BookendSectionVisualPlanDraft]:
        if not value:
            raise ValueError("bookend visual plan must contain at least one section")
        return value


def _story_visual_plan_output_model(allowed_render_kinds: list[str]) -> type[BaseModel]:
    """Build a strict provider schema for only the capabilities in this run."""

    allowed = tuple(
        kind
        for kind in dedupe([clean_text(kind) for kind in allowed_render_kinds])
        if kind and kind != "story_transition_scene"
    )
    if not allowed:
        raise ValueError("story visual planning requires at least one user-plannable render kind")
    render_kind_type = Literal.__getitem__(allowed)
    scene_model = create_model(
        "ActiveProviderSceneDraft",
        __base__=ProviderSceneDraft,
        __module__=__name__,
        render_kind=(
            render_kind_type,
            Field(description="One render kind from the active run capability registry."),
        ),
    )
    return create_model(
        "ActiveStoryVisualPlanDraft",
        __base__=StoryVisualPlanDraft,
        __module__=__name__,
        scene_timeline=(
            list[scene_model],
            Field(description="Renderable scenes covering the exact required visual slots."),
        ),
    )


def _bookend_visual_plan_output_model(allowed_render_kinds: list[str]) -> type[BaseModel]:
    allowed = tuple(
        kind
        for kind in dedupe([clean_text(kind) for kind in allowed_render_kinds])
        if kind and kind != "story_transition_scene"
    )
    if not allowed:
        raise ValueError("bookend visual planning requires at least one render kind")
    render_kind_type = Literal.__getitem__(allowed)
    scene_model = create_model(
        "ActiveBookendProviderSceneDraft",
        __base__=ProviderSceneDraft,
        __module__=__name__,
        render_kind=(
            render_kind_type,
            Field(description="One render kind from the active run capability registry."),
        ),
    )
    section_model = create_model(
        "ActiveBookendSectionVisualPlanDraft",
        __base__=BookendSectionVisualPlanDraft,
        __module__=__name__,
        scene_timeline=(
            list[scene_model],
            Field(description="Renderable scenes covering the exact required bookend slots."),
        ),
    )
    return create_model(
        "ActiveEpisodeBookendVisualPlanDraft",
        __base__=EpisodeBookendVisualPlanDraft,
        __module__=__name__,
        sections=(
            list[section_model],
            Field(description="One complete plan for each supplied intro or closing section."),
        ),
    )


def _story_visual_edit_output_model(story_plan_model: type[BaseModel]) -> type[BaseModel]:
    editable_story_plan_model = create_model(
        "ActiveEditableStoryVisualPlanDraft",
        __base__=story_plan_model,
        __module__=__name__,
        key_entities=(
            list[str],
            Field(description="Story entities used by the visual plan; return an empty list when none."),
        ),
        warnings=(
            list[str],
            Field(description="Plan warnings; return an empty list when there are none."),
        ),
    )
    return create_model(
        "ActiveStoryVisualEditOutput",
        __module__=__name__,
        revision_required=(bool, Field(description="True only when the current plan has a material visual problem.")),
        diagnosis=(list[str], Field(description="Concrete viewer-facing problems; empty when keeping the plan.")),
        revised_plan=(
            editable_story_plan_model | None,
            Field(
                description=(
                    "A complete replacement story plan when revision_required=true; otherwise null."
                )
            ),
        ),
    )


def _resolved_llm_configs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    default_config = {
        "provider": config["provider"],
        "model": config["model"],
        "temperature": float(config["temperature"]),
        "base_url": config.get("base_url"),
        "provider_options": dict(config.get("provider_options") or {}),
        "structured_output": dict(config.get("structured_output") or {}),
        "max_attempts": int(config.get("max_attempts", 2)),
        "content_filter_fallback": None,
    }
    overrides = dict(config.get("llm_roles") or {})
    resolved: dict[str, dict[str, Any]] = {}
    for role in VISUAL_LLM_ROLES:
        role_config = dict(default_config)
        override = dict(overrides.get(role) or {})
        if override:
            role_config.update(
                {
                    "provider": override["provider"],
                    "model": override["model"],
                    "temperature": float(override["temperature"]),
                    "base_url": override.get("base_url"),
                    "provider_options": dict(override.get("provider_options") or {}),
                    "structured_output": dict(override.get("structured_output") or {}),
                }
            )
            if override.get("max_attempts") is not None:
                role_config["max_attempts"] = int(override["max_attempts"])
            role_config["content_filter_fallback"] = _resolved_content_filter_fallback(
                override.get("content_filter_fallback")
            )
        resolved[role] = role_config
    return resolved


def _resolved_content_filter_fallback(raw_config: Any) -> dict[str, Any] | None:
    if not raw_config:
        return None
    fallback = dict(raw_config)
    return {
        "provider": fallback["provider"],
        "model": fallback["model"],
        "temperature": float(fallback["temperature"]),
        "base_url": fallback.get("base_url"),
        "provider_options": dict(fallback.get("provider_options") or {}),
        "structured_output": dict(fallback.get("structured_output") or {}),
        "max_attempts": int(fallback.get("max_attempts", 2)),
    }


def _build_llm_runtimes(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    runtimes: dict[str, dict[str, Any]] = {}
    for role, role_config in _resolved_llm_configs(config).items():
        runtimes[role] = {
            "config": role_config,
            "llm": make_llm(
                provider=role_config["provider"],
                model=role_config["model"],
                temperature=float(role_config["temperature"]),
                base_url=role_config.get("base_url"),
                provider_options=role_config.get("provider_options"),
            ),
        }
        fallback_config = role_config.get("content_filter_fallback")
        if fallback_config:
            runtimes[role]["content_filter_fallback"] = {
                "config": fallback_config,
                "llm": make_llm(
                    provider=fallback_config["provider"],
                    model=fallback_config["model"],
                    temperature=float(fallback_config["temperature"]),
                    base_url=fallback_config.get("base_url"),
                    provider_options=fallback_config.get("provider_options"),
                ),
            }
    return runtimes


def _structured_llm(llm, output_model, llm_config: dict[str, Any]):
    structured = dict(llm_config.get("structured_output") or {})
    return llm.with_structured_output(
        output_model,
        include_raw=True,
        method=clean_text(structured.get("method")) or "json_schema",
        strict=bool(structured.get("strict", True)),
    )


def _llm_route_summary(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        role: {
            "provider": route["provider"],
            "model": route["model"],
            "structured_output": route["structured_output"],
            "request_timeout_seconds": (
                route.get("provider_options") or {}
            ).get("request_timeout_seconds"),
            "content_filter_fallback": _fallback_route_summary(
                route.get("content_filter_fallback")
            ),
        }
        for role, route in _resolved_llm_configs(config).items()
    }


def _fallback_route_summary(fallback: Any) -> dict[str, Any] | None:
    if not fallback:
        return None
    return {
        "trigger": "content_filter",
        "provider": fallback["provider"],
        "model": fallback["model"],
        "structured_output": fallback["structured_output"],
        "request_timeout_seconds": (
            fallback.get("provider_options") or {}
        ).get("request_timeout_seconds"),
    }


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
    source_index = _build_source_index(
        stories,
        story_truth_indexes=_script_story_truth_indexes(request),
    )
    script_asset_hints = _script_story_asset_hints(request)
    asset_catalog, asset_catalog_provenance = _validated_asset_catalog(
        request,
        run_id=run_id,
        script_provenance=script_provenance,
    )
    asset_catalog_index = _asset_catalog_index(asset_catalog)
    story_sections = _build_story_sections(
        request=request,
        script_text=script_text,
        script_units=script_units,
        stories=stories,
    )
    story_ranges = _story_time_ranges(story_sections, stories)

    episode_prompt_bundle = load_prompt_bundle(EPISODE_DIRECTOR_PROMPT_MODULE, config["prompt_version"])
    bookend_prompt_bundle = load_prompt_bundle(
        BOOKEND_VISUAL_PLANNER_PROMPT_MODULE, config["prompt_version"]
    )
    story_prompt_bundle = load_prompt_bundle(STORY_VISUAL_PLANNER_PROMPT_MODULE, config["prompt_version"])
    story_editor_prompt_bundle = load_prompt_bundle(
        STORY_VISUAL_EDITOR_PROMPT_MODULE, config["prompt_version"]
    )
    llm_runtimes = _build_llm_runtimes(config)

    episode_direction = _generate_episode_direction(
        script_units=script_units,
        video_packet=video_packet,
        voiceover_package=voiceover_package,
        stories=stories,
        story_sections=story_sections,
        config=config,
        prompt_bundle=episode_prompt_bundle,
        llm_runtime=llm_runtimes[EPISODE_DIRECTOR_PROMPT_MODULE],
        llm_calls=llm_calls,
    )
    bookend_drafts = _generate_bookend_visual_plan(
        story_sections=story_sections,
        stories=stories,
        source_index=source_index,
        asset_catalog_index=asset_catalog_index,
        episode_direction=episode_direction,
        config=config,
        prompt_bundle=bookend_prompt_bundle,
        llm_runtime=llm_runtimes[BOOKEND_VISUAL_PLANNER_PROMPT_MODULE],
        llm_calls=llm_calls,
    )
    story_drafts = _generate_story_visual_plans(
        story_sections=story_sections,
        stories=stories,
        source_index=source_index,
        script_asset_hints=script_asset_hints,
        asset_catalog_index=asset_catalog_index,
        episode_direction=episode_direction,
        config=config,
        prompt_bundle=story_prompt_bundle,
        llm_runtime=llm_runtimes[STORY_VISUAL_PLANNER_PROMPT_MODULE],
        llm_calls=llm_calls,
    )
    preliminary_scene_plan = _build_visual_scene_plan(
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
        bookend_drafts=bookend_drafts,
        story_drafts=story_drafts,
        config=config,
        llm_calls=llm_calls,
        script_provenance=script_provenance,
        voiceover_provenance=voiceover_provenance,
        asset_catalog=asset_catalog,
        asset_catalog_provenance=asset_catalog_provenance,
    )
    story_drafts, visual_editor_report = _edit_story_visual_plans(
        story_drafts=story_drafts,
        preliminary_scene_plan=preliminary_scene_plan,
        story_sections=story_sections,
        stories=stories,
        source_index=source_index,
        script_asset_hints=script_asset_hints,
        asset_catalog_index=asset_catalog_index,
        episode_direction=episode_direction,
        config=config,
        prompt_bundle=story_editor_prompt_bundle,
        llm_runtime=llm_runtimes[STORY_VISUAL_EDITOR_PROMPT_MODULE],
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
        bookend_drafts=bookend_drafts,
        story_drafts=story_drafts,
        config=config,
        llm_calls=llm_calls,
        script_provenance=script_provenance,
        voiceover_provenance=voiceover_provenance,
        asset_catalog=asset_catalog,
        asset_catalog_provenance=asset_catalog_provenance,
        visual_editor_report=visual_editor_report,
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


def _validated_asset_catalog(
    request: VisualPlannerRequest,
    *,
    run_id: str,
    script_provenance: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    envelope = request.input.asset_catalog
    if envelope is None:
        return {}, None
    require_matching_run_id(run_id, envelope.data.run_id, "asset_catalog")
    catalog = envelope.data.visual_asset_catalog
    require_matching_run_id(run_id, catalog.get("run_id"), "visual_asset_catalog")
    provenance = validate_artifact_provenance(
        catalog.get("provenance"),
        artifact_type="visual_asset_catalog",
        run_id=run_id,
        payload=catalog_identity_payload(catalog),
        label="visual_asset_catalog",
    )
    require_parent_fingerprint(
        provenance,
        parent_name="script",
        expected=script_provenance["script_fingerprint"],
        label="visual_asset_catalog",
    )
    return catalog, provenance


def _asset_catalog_index(catalog: dict[str, Any]) -> dict[str, Any]:
    assets = [asset for asset in catalog.get("assets", []) if isinstance(asset, dict)]
    assets_by_id = {
        clean_text(asset.get("asset_id")): asset
        for asset in assets
        if clean_text(asset.get("asset_id"))
    }
    assets_by_story: dict[str, list[dict[str, Any]]] = {}
    for asset in assets_by_id.values():
        assets_by_story.setdefault(clean_text(asset.get("story_id")), []).append(asset)
    story_catalogs = {
        clean_text(item.get("story_id")): item
        for item in catalog.get("story_catalogs", [])
        if isinstance(item, dict) and clean_text(item.get("story_id"))
    }
    return {
        "assets_by_id": assets_by_id,
        "assets_by_story": assets_by_story,
        "story_catalogs": story_catalogs,
    }


def _catalog_for_story_prompt(
    catalog_index: dict[str, Any],
    story_id: str,
) -> dict[str, Any]:
    story_catalog = catalog_index.get("story_catalogs", {}).get(story_id, {})
    assets = catalog_index.get("assets_by_story", {}).get(story_id, [])
    return {
        "policy": {
            "asset_ids_are_authoritative": True,
            "available_assets_may_be_used_without_external_search": True,
            "unresolved_briefs_are_not_available_assets": True,
        },
        "available_assets": [
            _catalog_asset_for_prompt(asset)
            for asset in assets
            if clean_text(asset.get("status")) == "available"
        ],
        "asset_briefs": story_catalog.get("asset_briefs", []),
    }


def _catalog_asset_for_prompt(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": asset.get("asset_id"),
        "story_id": asset.get("story_id"),
        "asset_type": asset.get("asset_type"),
        "title": asset.get("title"),
        "description": short_text(clean_text(asset.get("description")), 420),
        "visual_description": short_text(clean_text(asset.get("visual_description")), 420),
        "contextual_description": short_text(
            clean_text(asset.get("contextual_description")), 520
        ),
        "descriptor_quality": asset.get("descriptor_quality"),
        "descriptor_provenance": asset.get("descriptor_provenance", []),
        "figure_caption": short_text(clean_text(asset.get("figure_caption")), 320),
        "page_section_heading": short_text(
            clean_text(asset.get("page_section_heading")), 220
        ),
        "nearby_text": short_text(clean_text(asset.get("nearby_text")), 520),
        "page_context": asset.get("page_context", {}),
        "source_record_key": asset.get("source_record_key"),
        "source_url": asset.get("source_url"),
        "asset_url": asset.get("asset_url"),
        "review_status": asset.get("review_status"),
        "image_role": asset.get("image_role"),
        "video_role": asset.get("video_role"),
        "alt_text": short_text(clean_text(asset.get("alt_text")), 240),
        "duration_seconds": asset.get("duration_seconds"),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "screenshot_target_candidates": asset.get("screenshot_target_candidates", [])[:5],
        "beat_screenshot_targets": asset.get("beat_screenshot_targets", [])[:8],
    }


def _catalog_for_bookend_prompt(catalog_index: dict[str, Any]) -> dict[str, Any]:
    assets = [
        asset
        for asset in catalog_index.get("assets_by_id", {}).values()
        if clean_text(asset.get("status")) == "available"
    ]
    return {
        "policy": {
            "asset_ids_are_authoritative": True,
            "asset_story_id_identifies_ownership": True,
            "page_context_does_not_describe_image_pixels": True,
            "external_search_is_not_available": True,
        },
        "available_assets": [_catalog_asset_for_prompt(asset) for asset in assets],
    }


def _bookend_allowed_render_kinds(
    config: dict[str, Any],
    catalog_index: dict[str, Any],
) -> list[str]:
    configured = [
        clean_text(kind)
        for kind in config["scene_policy"]["allowed_render_kinds"]
        if clean_text(kind) and clean_text(kind) != "story_transition_scene"
    ]
    required_assets = {
        clean_text(kind)
        for kind in config.get("asset_availability_policy", {}).get(
            "catalog_asset_required_render_kinds", []
        )
        if clean_text(kind)
    }
    available_types = {
        clean_text(asset.get("asset_type"))
        for asset in catalog_index.get("assets_by_id", {}).values()
        if clean_text(asset.get("status")) == "available"
    }
    allowed = [
        kind
        for kind in configured
        if kind not in required_assets
        or bool(CATALOG_ASSET_TYPES_BY_RENDER_KIND.get(kind, set()) & available_types)
    ]
    if not allowed:
        raise ValueError("No render kinds remain for bookend visual planning")
    return allowed


def _story_allowed_render_kinds(
    config: dict[str, Any],
    story_catalog: dict[str, Any],
) -> list[str]:
    """Limit asset-backed scene families to assets this story can actually use."""

    configured = [
        clean_text(kind)
        for kind in config["scene_policy"]["allowed_render_kinds"]
        if clean_text(kind) and clean_text(kind) != "story_transition_scene"
    ]
    required_assets = {
        clean_text(kind)
        for kind in (
            config.get("asset_availability_policy", {}).get(
                "catalog_asset_required_render_kinds", []
            )
        )
        if clean_text(kind)
    }
    available_types = {
        clean_text(asset.get("asset_type"))
        for asset in story_catalog.get("available_assets", [])
        if isinstance(asset, dict)
        and clean_text(asset.get("review_status")) not in {"rejected", "blocked"}
    }
    allowed = [
        kind
        for kind in configured
        if kind not in required_assets
        or bool(CATALOG_ASSET_TYPES_BY_RENDER_KIND.get(kind, set()) & available_types)
    ]
    if not allowed:
        raise ValueError(
            "No story-plannable render kinds remain after catalog availability routing"
        )
    return allowed


def _real_anchor_contract_for_prompt(
    story_catalog: dict[str, Any],
    config: dict[str, Any],
    *,
    allowed_render_kinds: list[str] | None = None,
) -> dict[str, Any]:
    allowed = set(
        allowed_render_kinds
        if allowed_render_kinds is not None
        else config["scene_policy"]["allowed_render_kinds"]
    )
    options = []
    for asset in story_catalog.get("available_assets", []):
        render_kind = CATALOG_RENDER_KIND_BY_ASSET_TYPE.get(
            clean_text(asset.get("asset_type")), ""
        )
        if render_kind not in allowed:
            continue
        options.append(
            {
                "asset_id": clean_text(asset.get("asset_id")),
                "asset_type": clean_text(asset.get("asset_type")),
                "compatible_render_kind": render_kind,
                "title": clean_text(asset.get("title")),
            }
        )
    required = bool(config.get("require_real_anchor_per_story")) and bool(options)
    return {
        "required": required,
        "available_assignments": options,
        "requirement": (
            "At least one returned scene must copy one available assignment's asset_id "
            "into payload_json and use that assignment's compatible_render_kind."
            if required
            else "No catalog anchor is required because no compatible asset is available."
        ),
    }


def _catalog_asset_for_scene(
    draft: dict[str, Any],
    *,
    story_id: str,
    render_kind: str,
    catalog_index: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    asset_id = clean_text(draft.get("asset_id"))
    if not asset_id:
        return None, []
    asset = catalog_index.get("assets_by_id", {}).get(asset_id)
    if not isinstance(asset, dict):
        return None, [f"references unknown asset_id {asset_id!r}"]

    errors: list[str] = []
    asset_story_id = clean_text(asset.get("story_id"))
    if asset_story_id != story_id:
        errors.append(
            f"asset_id {asset_id!r} belongs to story {asset_story_id!r}, not {story_id!r}"
        )
    if clean_text(asset.get("status")) != "available":
        errors.append(f"asset_id {asset_id!r} is not available")

    allowed_types = CATALOG_ASSET_TYPES_BY_RENDER_KIND.get(render_kind)
    asset_type = clean_text(asset.get("asset_type"))
    if allowed_types is None:
        errors.append(f"render_kind {render_kind!r} does not consume catalog assets")
    elif asset_type not in allowed_types:
        errors.append(
            f"asset_id {asset_id!r} has type {asset_type!r}; "
            f"{render_kind} requires one of {sorted(allowed_types)}"
        )

    canonical_key = clean_text(asset.get("source_record_key"))
    requested_key = clean_text(draft.get("source_record_key"))
    if requested_key and canonical_key and requested_key != canonical_key:
        errors.append(
            f"asset_id {asset_id!r} source_record_key does not match the scene payload"
        )
    canonical_url = clean_text(asset.get("source_url") or asset.get("asset_url"))
    requested_url = clean_text(draft.get("url"))
    if requested_url and canonical_url and requested_url != canonical_url:
        errors.append(f"asset_id {asset_id!r} URL does not match the scene payload")
    return (asset if not errors else None), errors


def _scene_with_catalog_asset(
    draft: dict[str, Any],
    asset: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(draft)
    enriched["asset_id"] = clean_text(asset.get("asset_id"))
    asset_type = clean_text(asset.get("asset_type"))
    if asset_type == "source_page":
        enriched["source_record_key"] = clean_text(asset.get("source_record_key"))
        enriched["url"] = clean_text(asset.get("source_url") or asset.get("asset_url"))
    elif asset_type == "logo":
        enriched["primary_entity"] = clean_text(asset.get("title"))
    return enriched


def _prepare_story_scene_draft(
    raw_scene: dict[str, Any],
    *,
    story_id: str,
    section: dict[str, Any],
    source_index: dict[str, Any],
    asset_catalog_index: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    scene = _expand_provider_scene_draft(raw_scene)
    scene, _ = _normalize_provider_scene_fields(
        scene,
        section=section,
        allowed_render_kinds=set(config["scene_policy"]["allowed_render_kinds"]),
    )
    scene, catalog_errors = _normalize_catalog_scene_reference(
        scene,
        story_id=story_id,
        catalog_index=asset_catalog_index,
        allowed_render_kinds=set(config["scene_policy"]["allowed_render_kinds"]),
    )
    scene, montage_errors = _normalize_montage_scene_references(
        scene,
        story_id=story_id,
        catalog_index=asset_catalog_index,
    )
    contract_errors = [
        *scene.get("contract_validation_errors", []),
        *catalog_errors,
        *montage_errors,
    ]
    if contract_errors:
        scene["contract_validation_errors"] = dedupe(
            [clean_text(error) for error in contract_errors if clean_text(error)]
        )
    return scene


def _prepare_bookend_scene_draft(
    raw_scene: dict[str, Any],
    *,
    section: dict[str, Any],
    source_index: dict[str, Any],
    asset_catalog_index: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    scene = _expand_provider_scene_draft(raw_scene)
    owner_story_id = _bookend_scene_owner_story_id(
        scene,
        source_index=source_index,
        asset_catalog_index=asset_catalog_index,
    )
    scene, _ = _normalize_provider_scene_fields(
        scene,
        section=section,
        allowed_render_kinds=set(config["scene_policy"]["allowed_render_kinds"]),
    )
    scene, catalog_errors = _normalize_catalog_scene_reference(
        scene,
        story_id=owner_story_id,
        catalog_index=asset_catalog_index,
        allowed_render_kinds=set(config["scene_policy"]["allowed_render_kinds"]),
    )
    scene, montage_errors = _normalize_montage_scene_references(
        scene,
        story_id=owner_story_id,
        catalog_index=asset_catalog_index,
    )
    contract_errors = [
        *scene.get("contract_validation_errors", []),
        *catalog_errors,
        *montage_errors,
    ]
    if contract_errors:
        scene["contract_validation_errors"] = dedupe(
            [clean_text(error) for error in contract_errors if clean_text(error)]
        )
    return scene, owner_story_id


def _bookend_scene_owner_story_id(
    scene: dict[str, Any],
    *,
    source_index: dict[str, Any],
    asset_catalog_index: dict[str, Any],
) -> str:
    asset_id = clean_text(scene.get("asset_id"))
    asset = asset_catalog_index.get("assets_by_id", {}).get(asset_id, {})
    if isinstance(asset, dict) and clean_text(asset.get("story_id")):
        return clean_text(asset.get("story_id"))
    for document in scene.get("documents", []):
        if not isinstance(document, dict):
            continue
        document_asset = asset_catalog_index.get("assets_by_id", {}).get(
            clean_text(document.get("asset_id")), {}
        )
        if isinstance(document_asset, dict) and clean_text(document_asset.get("story_id")):
            return clean_text(document_asset.get("story_id"))
    record_keys = [
        clean_text(scene.get("source_record_key")),
        *[
            clean_text(key)
            for key in scene.get("evidence_record_keys", [])
            if clean_text(key)
        ],
    ]
    for record_key in record_keys:
        record = source_index.get("records_by_key", {}).get(record_key, {})
        if isinstance(record, dict) and clean_text(record.get("story_id")):
            return clean_text(record.get("story_id"))
    return ""


def _normalize_provider_scene_fields(
    scene: dict[str, Any],
    *,
    section: dict[str, Any],
    allowed_render_kinds: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Preserve provider semantics; downstream code validates the declared shape."""

    del section, allowed_render_kinds
    return dict(scene), []


def _normalize_catalog_scene_reference(
    scene: dict[str, Any],
    *,
    story_id: str,
    catalog_index: dict[str, Any],
    allowed_render_kinds: set[str],
) -> tuple[dict[str, Any], list[str]]:
    del allowed_render_kinds
    normalized = dict(scene)
    asset_id = clean_text(normalized.get("asset_id"))
    if not asset_id:
        return normalized, []
    asset = catalog_index.get("assets_by_id", {}).get(asset_id)
    if not isinstance(asset, dict):
        return normalized, []
    render_kind = clean_text(normalized.get("render_kind"))
    compatible = clean_text(asset.get("asset_type")) in CATALOG_ASSET_TYPES_BY_RENDER_KIND.get(
        render_kind, set()
    )
    if (
        compatible
        and clean_text(asset.get("story_id")) == story_id
        and clean_text(asset.get("status")) == "available"
    ):
        # Canonical metadata for an exact provider-selected ID is identity binding,
        # not a semantic asset or scene-family substitution.
        normalized = _scene_with_catalog_asset(normalized, asset)
    return normalized, []


def _normalize_montage_scene_references(
    scene: dict[str, Any],
    *,
    story_id: str,
    catalog_index: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    normalized = dict(scene)
    if (
        clean_text(normalized.get("render_kind")) != "document_stack_scene"
        or clean_text(normalized.get("recipe_id")) != "source_proof_montage"
    ):
        return normalized, []

    errors: list[str] = []
    documents: list[dict[str, Any]] = []
    record_keys = [
        clean_text(value)
        for value in normalized.get("evidence_record_keys", [])
        if clean_text(value)
    ]
    for index, raw in enumerate(normalized.get("documents", []), start=1):
        if not isinstance(raw, dict):
            errors.append(f"source montage document {index} must be an object")
            continue
        asset_id = clean_text(raw.get("asset_id"))
        asset = catalog_index.get("assets_by_id", {}).get(asset_id)
        if not asset_id or not isinstance(asset, dict):
            errors.append(
                f"source montage document {index} references unknown asset_id {asset_id!r}"
            )
            continue
        if clean_text(asset.get("story_id")) != story_id:
            errors.append(
                f"source montage asset_id {asset_id!r} is not owned by story {story_id!r}"
            )
            continue
        if clean_text(asset.get("status")) != "available":
            errors.append(f"source montage asset_id {asset_id!r} is not available")
            continue
        if clean_text(asset.get("asset_type")) != "source_page":
            errors.append(f"source montage asset_id {asset_id!r} is not a source_page")
            continue
        candidates = [
            clean_text(value)
            for value in asset.get("screenshot_target_candidates", [])
            if clean_text(value)
        ]
        requested_target = clean_text(raw.get("target_text"))
        target_text = next(
            (
                candidate
                for candidate in candidates
                if candidate.casefold() == requested_target.casefold()
            ),
            candidates[0] if candidates else clean_text(asset.get("title")),
        )
        record_key = clean_text(asset.get("source_record_key"))
        source_url = clean_text(asset.get("source_url") or asset.get("asset_url"))
        record_keys.append(record_key)
        documents.append(
            {
                "asset_id": asset_id,
                "title": short_text(clean_text(asset.get("title")), 72),
                "source": short_text(clean_text(asset.get("source_name")) or "Source", 32),
                "document_type": short_text(
                    clean_text(raw.get("document_type")) or "SOURCE", 18
                ),
                "date": short_text(clean_text(raw.get("date")), 20),
                "detail": short_text(clean_text(raw.get("detail")), 72),
                "source_record_key": record_key,
                "url": source_url,
                "target_text": short_text(target_text, 260),
            }
        )
    normalized["documents"] = documents
    normalized["evidence_record_keys"] = dedupe(record_keys)
    normalized["payload_json"] = _updated_payload_json(
        normalized,
        {"documents": documents},
    )
    return normalized, errors


def _updated_payload_json(scene: dict[str, Any], updates: dict[str, Any]) -> str:
    try:
        payload = json.loads(clean_text(scene.get("payload_json")) or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.update(updates)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _generate_episode_direction(
    *,
    script_units: list[dict[str, Any]],
    video_packet: dict[str, Any],
    voiceover_package: dict[str, Any] | None,
    stories: list[dict[str, Any]],
    story_sections: list[dict[str, Any]],
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    total_duration = _total_duration(script_units, voiceover_package, video_packet)
    timed_script = _episode_script_context(script_units)
    payload = {
        "task": "Create the global motion direction for an AI news roundup visual plan.",
        "selected_format": SUPPORTED_FORMAT,
        "style": config["style"],
        "visual_mix_policy": config.get("visual_mix_policy", {}),
        "scene_policy": config["scene_policy"],
        "visual_capabilities": _visual_capabilities_for_prompt(config, include_system_managed=False),
        "audio_context": _audio_context(voiceover_package, total_duration),
        "video_packet_summary": _video_packet_summary(video_packet),
        "story_section_summary": _story_section_summary(story_sections),
        "selected_stories": _story_summaries_for_prompt(stories),
        "timed_script": timed_script,
        "banned_visual_language": sorted(OLD_CARD_RENDER_KINDS),
        "required_behavior": {
            "do_not_plan_individual_scene_timeline": True,
            "give_global_direction_only": True,
            "optimize_for_youtube_motion_not_presentation_cards": True,
        },
    }
    return _invoke_chain_with_attempts(
        module_name=EPISODE_DIRECTOR_PROMPT_MODULE,
        output_model=EpisodeDirectorDraft,
        llm_runtime=llm_runtime,
        prompt_bundle=prompt_bundle,
        task_payload=payload,
        metadata={
            "story_count": len(stories),
            "script_unit_count": len(script_units),
            "total_duration_seconds": round(total_duration, 2),
            "script_context": timed_script["telemetry"],
        },
        llm_calls=llm_calls,
    )


def _generate_bookend_visual_plan(
    *,
    story_sections: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    source_index: dict[str, Any],
    asset_catalog_index: dict[str, Any],
    episode_direction: dict[str, Any],
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    sections = [
        section
        for section in story_sections
        if clean_text(section.get("section_type")) in {"intro", "closing"}
    ]
    if not sections:
        return {}

    allowed_render_kinds = _bookend_allowed_render_kinds(config, asset_catalog_index)
    output_model = _bookend_visual_plan_output_model(allowed_render_kinds)
    bookend_config = deepcopy(config)
    bookend_config["scene_policy"] = {
        **config["scene_policy"],
        "allowed_render_kinds": allowed_render_kinds,
    }
    payload_sections = []
    for section in sections:
        payload_sections.append(
            {
                **_section_for_prompt(section),
                "script_units": _script_units_for_bookend_prompt(
                    section.get("script_units", []),
                    source_index=source_index,
                ),
                "unit_coverage_contract": _story_coverage_contract(
                    section,
                    max_scene_seconds=safe_float(
                        config["scene_policy"].get("max_scene_seconds"), 14.0
                    ),
                    hard_max_scene_seconds=_hard_max_scene_seconds(config["scene_policy"]),
                    hard_cap_tolerance_seconds=safe_float(
                        config["scene_policy"].get("hard_cap_tolerance_seconds"), 0.0
                    ),
                    unit_assignment_mode=clean_text(
                        config["scene_policy"].get(
                            "unit_assignment_mode", "one_scene_per_script_unit"
                        )
                    ),
                ),
            }
        )
    task_payload = {
        "task": "Plan the intro and closing visuals for a finished AI news roundup.",
        "selected_format": SUPPORTED_FORMAT,
        "episode_direction": episode_direction,
        "style": config["style"],
        "visual_mix_policy": config.get("visual_mix_policy", {}),
        "scene_policy": bookend_config["scene_policy"],
        "visual_capabilities": _visual_capabilities_for_prompt(
            bookend_config,
            include_system_managed=False,
            allowed_render_kinds=allowed_render_kinds,
        ),
        "selected_stories": _story_summaries_for_prompt(stories),
        "verified_asset_catalog": _catalog_for_bookend_prompt(asset_catalog_index),
        "bookend_sections": payload_sections,
        "allowed_render_kinds": allowed_render_kinds,
        "banned_visual_language": sorted(OLD_CARD_RENDER_KINDS),
        "required_behavior": {
            "plan_only_supplied_intro_and_closing_sections": True,
            "honor_authored_visual_briefs": True,
            "use_authored_on_screen_text_when_present": True,
            "cover_every_required_scene_slot": True,
            "do_not_author_seconds": True,
            "do_not_slice_narration_into_display_copy": True,
            "catalog_asset_ids_are_exact": True,
        },
    }
    draft = _invoke_chain_with_attempts(
        module_name=BOOKEND_VISUAL_PLANNER_PROMPT_MODULE,
        output_model=output_model,
        llm_runtime=llm_runtime,
        prompt_bundle=prompt_bundle,
        task_payload=task_payload,
        metadata={
            "section_types": [clean_text(section.get("section_type")) for section in sections],
            "script_unit_count": sum(len(section.get("script_units", [])) for section in sections),
            "allowed_render_kinds": allowed_render_kinds,
        },
        llm_calls=llm_calls,
        validate_output=lambda candidate: _bookend_draft_errors(
            candidate,
            sections=sections,
            source_index=source_index,
            asset_catalog_index=asset_catalog_index,
            config=bookend_config,
        ),
    )
    return {
        clean_text(section.get("section_type")): section
        for section in draft.get("sections", [])
        if isinstance(section, dict) and clean_text(section.get("section_type"))
    }


def _generate_story_visual_plans(
    *,
    story_sections: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    source_index: dict[str, Any],
    script_asset_hints: dict[str, dict[str, Any]],
    asset_catalog_index: dict[str, Any],
    episode_direction: dict[str, Any],
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    stories_by_id = {clean_text(story.get("story_id", "")): story for story in stories}
    drafts: dict[str, dict[str, Any]] = {}
    for section in story_sections:
        if section.get("section_type") != "story":
            continue
        story_id = clean_text(section.get("story_id", ""))
        story = stories_by_id.get(story_id)
        if not story:
            continue
        coverage_contract = _story_coverage_contract(
            section,
            max_scene_seconds=safe_float(config["scene_policy"].get("max_scene_seconds"), 14.0),
            hard_max_scene_seconds=_hard_max_scene_seconds(config["scene_policy"]),
            hard_cap_tolerance_seconds=safe_float(
                config["scene_policy"].get("hard_cap_tolerance_seconds"), 0.0
            ),
            unit_assignment_mode=clean_text(
                config["scene_policy"].get(
                    "unit_assignment_mode", "one_scene_per_script_unit"
                )
            ),
        )
        story_catalog = _catalog_for_story_prompt(asset_catalog_index, story_id)
        story_allowed_render_kinds = _story_allowed_render_kinds(config, story_catalog)
        story_config = deepcopy(config)
        story_config["scene_policy"] = {
            **config["scene_policy"],
            "allowed_render_kinds": story_allowed_render_kinds,
        }
        output_model = _story_visual_plan_output_model(story_allowed_render_kinds)
        story_context = _story_for_prompt(
            story,
            source_index,
            config,
            script_units=section.get("script_units", []),
        )
        payload = {
            "task": "Create renderable visual scenes for exactly one story in a finished AI news roundup.",
            "selected_format": SUPPORTED_FORMAT,
            "episode_direction": episode_direction,
            "visual_mix_policy": config.get("visual_mix_policy", {}),
            "scene_policy": story_config["scene_policy"],
            "visual_capabilities": _visual_capabilities_for_prompt(
                story_config,
                include_system_managed=False,
                allowed_render_kinds=story_allowed_render_kinds,
            ),
            "story": story_context,
            "available_story_assets": script_asset_hints.get(story_id, {}),
            "verified_asset_catalog": story_catalog,
            "real_anchor_contract": _real_anchor_contract_for_prompt(
                story_catalog,
                story_config,
                allowed_render_kinds=story_allowed_render_kinds,
            ),
            "story_section": _section_for_prompt(section),
            "script_units": _script_units_for_story_prompt(
                section.get("script_units", []),
                source_index=source_index,
                story_id=story_id,
            ),
            "unit_coverage_contract": coverage_contract,
            "allowed_render_kinds": story_allowed_render_kinds,
            "banned_visual_language": sorted(OLD_CARD_RENDER_KINDS),
            "required_behavior": {
                "plan_only_this_story": True,
                "use_only_this_story_records": True,
                "use_absolute_start_unit_order_values_from_script_units": True,
                "cover_every_required_unit_order_without_shifting_content": True,
                "treat_beat_id_and_visual_brief_as_authoritative_context": True,
                "do_not_author_seconds_or_retime_narration": True,
                "return_one_scene_for_every_required_scene_slot": True,
                "do_not_combine_adjacent_script_units": True,
                "return_distinct_treatments_for_overlong_unit_slots": True,
                "first_story_title_beat_is_inserted_deterministically": True,
                "do_not_create_title_timeline_entity_recap_or_fallback_cards": True,
                "capability_registry_is_authoritative": True,
                "never_use_a_render_kind_missing_from_visual_capabilities": True,
                "bind_every_semantic_graphic_to_selected_record_or_canonical_script_beat": True,
                "do_not_invent_chart_values_relationships_flow_steps_or_comparison_cells": True,
                "numeric_payloads_require_exact_evidence_truth_ids": True,
                "copy_numeric_values_from_the_referenced_truth_items_without_inference": True,
                "leave_a_rich_scene_out_when_its_required_payload_is_not_supported": True,
                "choose_the_richest_supported_scene_for_each_spoken_idea": True,
                "reference_catalog_asset_id_for_real_source_image_or_logo_scenes": True,
                "use_at_least_one_available_real_world_anchor_for_this_story": True,
                "do_not_reuse_the_same_catalog_asset_for_multiple_scenes_unless_the_second_treatment_reveals_new_source_detail": True,
            },
        }
        metadata = {
            "story_id": story_id,
            "story_title": clean_text(story.get("story_title", "")),
            "script_unit_count": len(section.get("script_units", [])),
            "source_record_count": len(source_index["record_keys_by_story"].get(story_id, [])),
            "source_context": story_context["context_telemetry"],
            "allowed_render_kinds": story_allowed_render_kinds,
            "available_asset_ids": [
                clean_text(asset.get("asset_id"))
                for asset in story_catalog.get("available_assets", [])
                if clean_text(asset.get("asset_id"))
            ],
        }
        try:
            draft = _invoke_chain_with_attempts(
                module_name=STORY_VISUAL_PLANNER_PROMPT_MODULE,
                output_model=output_model,
                llm_runtime=llm_runtime,
                prompt_bundle=prompt_bundle,
                task_payload=payload,
                metadata=metadata,
                llm_calls=llm_calls,
                validate_output=lambda candidate: _story_draft_errors(
                    candidate,
                    story_id=story_id,
                    section=section,
                    source_index=source_index,
                    asset_catalog_index=asset_catalog_index,
                    config=story_config,
                ),
            )
        except Exception as exc:
            failure_reason = f"{type(exc).__name__}: {exc}"
            fallbacks_allowed = bool(config.get("allow_deterministic_story_fallbacks"))
            drafts[story_id] = {
                "story_id": story_id,
                "visual_strategy": (
                    "Use deterministic exact-narration substitutes because the story planner failed."
                    if fallbacks_allowed
                    else "Story planning failed; no substitute scenes were authorized."
                ),
                "key_entities": [],
                "scene_timeline": [],
                "fallback_used": fallbacks_allowed,
                "fallback_reason": failure_reason if fallbacks_allowed else "",
                "planning_failed": not fallbacks_allowed,
                "planning_failure_reason": failure_reason if not fallbacks_allowed else "",
                "warnings": [
                    (
                        f"Story visual planner fallback used: {failure_reason}"
                        if fallbacks_allowed
                        else f"Story visual planner failed: {failure_reason}"
                    )
                ],
            }
            continue
        returned_story_id = clean_text(draft.get("story_id", ""))
        if returned_story_id != story_id:
            if not _story_ids_equivalent(returned_story_id, story_id):
                failure_reason = f"returned story_id {returned_story_id!r}; expected {story_id!r}"
                fallbacks_allowed = bool(config.get("allow_deterministic_story_fallbacks"))
                drafts[story_id] = {
                    "story_id": story_id,
                    "visual_strategy": (
                        "Use deterministic exact-narration substitutes because the planner returned the wrong story id."
                        if fallbacks_allowed
                        else "Story planning failed; no substitute scenes were authorized."
                    ),
                    "key_entities": [],
                    "scene_timeline": [],
                    "fallback_used": fallbacks_allowed,
                    "fallback_reason": failure_reason if fallbacks_allowed else "",
                    "planning_failed": not fallbacks_allowed,
                    "planning_failure_reason": failure_reason if not fallbacks_allowed else "",
                    "warnings": [f"Story visual planner {failure_reason}"],
                }
                continue
            draft["story_id"] = story_id
            draft.setdefault("warnings", []).append(f"Planner returned punctuation-equivalent story_id {returned_story_id!r}; canonicalized to {story_id!r}.")
        drafts[story_id] = draft
    return drafts


def _edit_story_visual_plans(
    *,
    story_drafts: dict[str, dict[str, Any]],
    preliminary_scene_plan: dict[str, Any],
    story_sections: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    source_index: dict[str, Any],
    script_asset_hints: dict[str, dict[str, Any]],
    asset_catalog_index: dict[str, Any],
    episode_direction: dict[str, Any],
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    editor_config = dict(config.get("visual_editor") or {})
    if not bool(editor_config.get("enabled", False)) or int(editor_config.get("max_passes", 0)) < 1:
        return story_drafts, {
            "enabled": False,
            "max_passes": int(editor_config.get("max_passes", 0)),
            "reviewed_story_count": 0,
            "revision_count": 0,
            "failure_count": 0,
            "stories": [],
        }

    stories_by_id = {clean_text(story.get("story_id")): story for story in stories}
    sections_by_story = {
        clean_text(section.get("story_id")): section
        for section in story_sections
        if clean_text(section.get("section_type")) == "story"
        and clean_text(section.get("story_id"))
    }
    scenes_by_story: dict[str, list[dict[str, Any]]] = {}
    for scene in preliminary_scene_plan.get("scene_timeline", []):
        if isinstance(scene, dict) and clean_text(scene.get("story_id")):
            scenes_by_story.setdefault(clean_text(scene.get("story_id")), []).append(scene)

    edited = {story_id: dict(draft) for story_id, draft in story_drafts.items()}
    reports: list[dict[str, Any]] = []
    call_limit = int(editor_config.get("max_story_calls", 8))
    reviewed = 0
    editor_calls = 0
    for story in stories:
        story_id = clean_text(story.get("story_id"))
        section = sections_by_story.get(story_id)
        current = edited.get(story_id, {})
        if not story_id or not section or editor_calls >= call_limit:
            continue
        story_catalog = _catalog_for_story_prompt(asset_catalog_index, story_id)
        story_allowed_render_kinds = _story_allowed_render_kinds(config, story_catalog)
        story_config = deepcopy(config)
        story_config["scene_policy"] = {
            **config["scene_policy"],
            "allowed_render_kinds": story_allowed_render_kinds,
        }
        current_errors = _story_draft_errors(
            current,
            story_id=story_id,
            section=section,
            source_index=source_index,
            asset_catalog_index=asset_catalog_index,
            config=story_config,
        )
        current_scenes = scenes_by_story.get(story_id, [])
        quality_context = _story_visual_quality_context(
            story_id=story_id,
            scenes=current_scenes,
            asset_catalog_index=asset_catalog_index,
            config=config,
            current_errors=current_errors,
        )
        if not bool(editor_config.get("review_all_stories", False)) and not quality_context["review_recommended"]:
            continue

        reviewed += 1
        coverage_contract = _story_coverage_contract(
            section,
            max_scene_seconds=safe_float(config["scene_policy"].get("max_scene_seconds"), 14.0),
            hard_max_scene_seconds=_hard_max_scene_seconds(config["scene_policy"]),
            hard_cap_tolerance_seconds=safe_float(
                config["scene_policy"].get("hard_cap_tolerance_seconds"), 0.0
            ),
            unit_assignment_mode=clean_text(
                config["scene_policy"].get("unit_assignment_mode", "one_scene_per_script_unit")
            ),
        )
        story_plan_model = _story_visual_plan_output_model(story_allowed_render_kinds)
        output_model = _story_visual_edit_output_model(story_plan_model)
        story_context = _story_for_prompt(
            story,
            source_index,
            config,
            script_units=section.get("script_units", []),
        )
        payload = {
            "selected_format": SUPPORTED_FORMAT,
            "episode_direction": episode_direction,
            "style": config["style"],
            "visual_mix_policy": config.get("visual_mix_policy", {}),
            "scene_policy": story_config["scene_policy"],
            "visual_capabilities": _visual_capabilities_for_prompt(
                story_config,
                include_system_managed=False,
                allowed_render_kinds=story_allowed_render_kinds,
            ),
            "story": story_context,
            "available_story_assets": script_asset_hints.get(story_id, {}),
            "verified_asset_catalog": story_catalog,
            "real_anchor_contract": _real_anchor_contract_for_prompt(
                story_catalog,
                story_config,
                allowed_render_kinds=story_allowed_render_kinds,
            ),
            "story_section": _section_for_prompt(section),
            "script_units": _script_units_for_story_prompt(
                section.get("script_units", []),
                source_index=source_index,
                story_id=story_id,
            ),
            "unit_coverage_contract": coverage_contract,
            "current_story_plan": current,
            "current_normalized_scenes": [
                {
                    "scene_id": scene.get("scene_id"),
                    "start_unit_order": scene.get("script_unit_start"),
                    "end_unit_order": scene.get("script_unit_end"),
                    "render_kind": scene.get("render_kind"),
                    "script_excerpt": short_text(clean_text(scene.get("script_excerpt")), 320),
                    "payload": scene.get("payload", {}),
                    "semantic_grounding": scene.get("semantic_grounding", {}),
                }
                for scene in current_scenes
            ],
            "plan_quality_context": quality_context,
        }

        validation_current_errors = list(current_errors)

        def validate_editor_output(candidate: dict[str, Any]) -> list[str]:
            revision_required = bool(candidate.get("revision_required"))
            diagnosis = [clean_text(item) for item in candidate.get("diagnosis", []) if clean_text(item)]
            revised_plan = candidate.get("revised_plan")
            if not revision_required:
                errors = []
                if revised_plan is not None:
                    errors.append("revision_required=false requires revised_plan=null")
                if validation_current_errors:
                    errors.append("the current plan is invalid, so the editor must return a valid revised_plan")
                return errors
            if not diagnosis:
                return ["revision_required=true requires a concrete diagnosis"]
            if not isinstance(revised_plan, dict):
                return ["revision_required=true requires one complete revised_plan object"]
            returned_story_id = clean_text(revised_plan.get("story_id"))
            if returned_story_id != story_id and not _story_ids_equivalent(returned_story_id, story_id):
                return [f"revised_plan.story_id {returned_story_id!r} does not match {story_id!r}"]
            revised_plan["story_id"] = story_id
            return _story_draft_errors(
                revised_plan,
                story_id=story_id,
                section=section,
                source_index=source_index,
                asset_catalog_index=asset_catalog_index,
                config=story_config,
            )

        try:
            editor_calls += 1
            decision = _invoke_chain_with_attempts(
                module_name=STORY_VISUAL_EDITOR_PROMPT_MODULE,
                output_model=output_model,
                llm_runtime=llm_runtime,
                prompt_bundle=prompt_bundle,
                task_payload=payload,
                metadata={
                    "story_id": story_id,
                    "story_title": clean_text(story.get("story_title")),
                    "current_plan_valid": not current_errors,
                    "review_reasons": quality_context["review_reasons"],
                    "source_context": story_context["context_telemetry"],
                    "allowed_render_kinds": story_allowed_render_kinds,
                    "available_asset_ids": [
                        clean_text(asset.get("asset_id"))
                        for asset in story_catalog.get("available_assets", [])
                        if clean_text(asset.get("asset_id"))
                    ],
                    "editor_pass": 1,
                },
                llm_calls=llm_calls,
                validate_output=validate_editor_output,
            )
        except Exception as exc:
            if clean_text(editor_config.get("failure_mode")) == "fail":
                raise
            reports.append(
                {
                    "story_id": story_id,
                    "decision": "editor_failed_keep_original",
                    "revision_applied": False,
                    "diagnosis": [],
                    "failure_reason": f"{type(exc).__name__}: {exc}",
                    "original_plan_valid": not current_errors,
                }
            )
            continue

        revision_required = bool(decision.get("revision_required"))
        replacement = current
        if revision_required:
            replacement = dict(decision["revised_plan"])
            replacement["story_id"] = story_id
            replacement["editor_applied"] = True
            edited[story_id] = replacement

        recheck_context: dict[str, Any] = {}
        recheck_failure_reason = ""
        second_revision_applied = False
        if revision_required:
            try:
                normalized_replacement = _normalize_story_candidate_scenes(
                    story=story,
                    section=section,
                    source_index=source_index,
                    story_draft=replacement,
                    asset_catalog_index=asset_catalog_index,
                    counts=Counter(),
                    config=story_config,
                )
                recheck_context = _story_visual_quality_context(
                    story_id=story_id,
                    scenes=normalized_replacement,
                    asset_catalog_index=asset_catalog_index,
                    config=config,
                    current_errors=[],
                )
            except Exception as exc:
                recheck_failure_reason = f"{type(exc).__name__}: {exc}"

        if (
            revision_required
            and int(editor_config.get("max_passes", 1)) >= 2
            and recheck_context.get("review_recommended")
            and editor_calls < call_limit
        ):
            second_payload = dict(payload)
            second_payload["current_story_plan"] = replacement
            second_payload["current_normalized_scenes"] = [
                {
                    "start_unit_order": scene.get("start_unit_order"),
                    "end_unit_order": scene.get("end_unit_order"),
                    "render_kind": scene.get("render_kind"),
                    "script_excerpt": short_text(clean_text(scene.get("script_excerpt")), 320),
                    "payload": scene.get("payload", {}),
                    "semantic_grounding": scene.get("semantic_grounding", {}),
                }
                for scene in normalized_replacement
            ]
            second_payload["plan_quality_context"] = recheck_context
            validation_current_errors = []
            try:
                editor_calls += 1
                second_decision = _invoke_chain_with_attempts(
                    module_name=STORY_VISUAL_EDITOR_PROMPT_MODULE,
                    output_model=output_model,
                    llm_runtime=llm_runtime,
                    prompt_bundle=prompt_bundle,
                    task_payload=second_payload,
                    metadata={
                        "story_id": story_id,
                        "story_title": clean_text(story.get("story_title")),
                        "current_plan_valid": True,
                        "review_reasons": recheck_context.get("review_reasons", []),
                        "source_context": story_context["context_telemetry"],
                        "allowed_render_kinds": story_allowed_render_kinds,
                        "available_asset_ids": [
                            clean_text(asset.get("asset_id"))
                            for asset in story_catalog.get("available_assets", [])
                            if clean_text(asset.get("asset_id"))
                        ],
                        "editor_pass": 2,
                    },
                    llm_calls=llm_calls,
                    validate_output=validate_editor_output,
                )
                if bool(second_decision.get("revision_required")):
                    replacement = dict(second_decision["revised_plan"])
                    replacement["story_id"] = story_id
                    replacement["editor_applied"] = True
                    replacement["editor_passes"] = 2
                    edited[story_id] = replacement
                    second_revision_applied = True
                decision = second_decision
            except Exception as exc:
                recheck_failure_reason = f"{type(exc).__name__}: {exc}"
        reports.append(
            {
                "story_id": story_id,
                "decision": "revision_applied" if revision_required else "keep",
                "revision_applied": revision_required,
                "second_revision_applied": second_revision_applied,
                "diagnosis": [
                    clean_text(item) for item in decision.get("diagnosis", []) if clean_text(item)
                ],
                "failure_reason": "",
                "recheck_failure_reason": recheck_failure_reason,
                "recheck_reasons": recheck_context.get("review_reasons", []),
                "original_plan_valid": not current_errors,
            }
        )

    return edited, {
        "enabled": True,
        "max_passes": int(editor_config.get("max_passes", 1)),
        "reviewed_story_count": reviewed,
        "editor_call_count": editor_calls,
        "revision_count": sum(bool(item.get("revision_applied")) for item in reports),
        "failure_count": sum(bool(item.get("failure_reason")) for item in reports),
        "stories": reports,
    }


def _story_visual_quality_context(
    *,
    story_id: str,
    scenes: list[dict[str, Any]],
    asset_catalog_index: dict[str, Any],
    config: dict[str, Any],
    current_errors: list[str],
) -> dict[str, Any]:
    kind_counts = Counter(clean_text(scene.get("render_kind")) for scene in scenes)
    text_scenes = [scene for scene in scenes if clean_text(scene.get("render_kind")) in TEXT_LIKE_RENDER_KINDS]
    used_asset_ids = [
        clean_text((scene.get("payload") or {}).get("asset_id"))
        for scene in scenes
        if isinstance(scene.get("payload"), dict)
        and clean_text((scene.get("payload") or {}).get("asset_id"))
    ]
    repeated_asset_ids = sorted(
        asset_id for asset_id, count in Counter(used_asset_ids).items() if count > 1
    )
    available_asset_ids = [
        clean_text(asset.get("asset_id"))
        for asset in asset_catalog_index.get("assets_by_story", {}).get(story_id, [])
        if clean_text(asset.get("status")) == "available"
        and clean_text(asset.get("asset_id"))
    ]
    max_same = safe_int(config["scene_policy"].get("max_consecutive_same_kind"), 2)
    repeated_kind_runs = _same_kind_runs_over_limit(scenes, max_same)
    repeated_payloads = _adjacent_duplicate_visual_payloads(scenes)
    text_target = safe_int(
        config.get("visual_mix_policy", {}).get("target_max_text_like_scenes_per_story"),
        2,
    )
    review_reasons: list[str] = []
    if current_errors:
        review_reasons.append("invalid_story_plan")
    if repeated_kind_runs:
        review_reasons.append("repeated_render_kind_run")
    if repeated_asset_ids:
        review_reasons.append("repeated_exact_asset")
    if repeated_payloads:
        review_reasons.append("repeated_visual_payload")
    if len(text_scenes) > text_target:
        review_reasons.append("text_like_scene_target_exceeded")
    return {
        "review_recommended": bool(review_reasons),
        "review_reasons": review_reasons,
        "current_plan_errors": current_errors,
        "scene_count": len(scenes),
        "render_kind_counts": dict(kind_counts),
        "text_like_scene_count": len(text_scenes),
        "text_like_scene_target": text_target,
        "repeated_kind_runs": repeated_kind_runs,
        "repeated_asset_ids": repeated_asset_ids,
        "repeated_visual_payloads": repeated_payloads,
        "used_asset_ids": used_asset_ids,
        "available_asset_ids": available_asset_ids,
        "unused_asset_ids": sorted(set(available_asset_ids) - set(used_asset_ids)),
    }


def _invoke_chain_with_attempts(
    *,
    module_name: str,
    output_model,
    llm_runtime: dict[str, Any],
    prompt_bundle: dict[str, str],
    task_payload: dict[str, Any],
    metadata: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    validate_output=None,
) -> dict[str, Any]:
    primary_config = llm_runtime["config"]
    fallback_runtime = llm_runtime.get("content_filter_fallback")
    try:
        return _invoke_single_route_with_attempts(
            module_name=module_name,
            output_model=output_model,
            llm=llm_runtime["llm"],
            prompt_bundle=prompt_bundle,
            task_payload=task_payload,
            config=primary_config,
            metadata={
                **metadata,
                "route_attempt": "primary",
                "content_filter_fallback_configured": fallback_runtime is not None,
            },
            llm_calls=llm_calls,
            validate_output=validate_output,
            propagate_content_filter=fallback_runtime is not None,
        )
    except Exception as exc:
        if fallback_runtime is None or not _is_content_filter_error(exc):
            raise

    fallback_config = fallback_runtime["config"]
    return _invoke_single_route_with_attempts(
        module_name=module_name,
        output_model=output_model,
        llm=fallback_runtime["llm"],
        prompt_bundle=prompt_bundle,
        task_payload=task_payload,
        config=fallback_config,
        metadata={
            **metadata,
            "route_attempt": "content_filter_fallback",
            "fallback_trigger": "content_filter",
            "fallback_from_provider": primary_config.get("provider", ""),
            "fallback_from_model": primary_config.get("model", ""),
        },
        llm_calls=llm_calls,
        validate_output=validate_output,
        propagate_content_filter=False,
    )


def _invoke_single_route_with_attempts(
    *,
    module_name: str,
    output_model,
    llm,
    prompt_bundle: dict[str, str],
    task_payload: dict[str, Any],
    config: dict[str, Any],
    metadata: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    validate_output=None,
    propagate_content_filter: bool,
) -> dict[str, Any]:
    chain = TASK_PROMPT | _structured_llm(llm, output_model, config)
    last_error = ""
    max_attempts = int(config.get("max_attempts", 2))
    for attempt in range(1, max_attempts + 1):
        payload = dict(task_payload)
        if last_error:
            payload["repair_context"] = {
                "attempt": attempt,
                "previous_error": last_error,
                "instruction": (
                    "Return a corrected complete structured response. Do not repair an "
                    "unavailable asset by inventing another ID or changing it into an "
                    "uncataloged media request. Use an exact listed assignment with its "
                    "compatible render kind, or choose an asset-free render kind from the "
                    "active capability registry."
                ),
            }
            anchor_contract = task_payload.get("real_anchor_contract")
            if isinstance(anchor_contract, dict):
                payload["repair_context"]["exact_asset_assignments"] = list(
                    anchor_contract.get("available_assignments", [])
                )
            payload["repair_context"]["active_render_kinds"] = list(
                task_payload.get("allowed_render_kinds", [])
                or (task_payload.get("scene_policy") or {}).get(
                    "allowed_render_kinds", []
                )
            )
            coverage_contract = task_payload.get("unit_coverage_contract")
            if isinstance(coverage_contract, dict):
                payload["repair_context"]["unit_coverage_contract"] = coverage_contract
                payload["repair_context"]["verification_instruction"] = (
                    "Before returning, compare scene ranges against required_scene_slots. "
                    "Return exactly one scene per slot with that slot's exact start and end "
                    "unit order; do not combine adjacent units. Prefer distinct treatments "
                    "for repeated slots on one overlong unit, but repeat the honest supported "
                    "treatment instead of inventing a different visual. Recheck every "
                    "payload_json against the chosen capability's payload_field_contract, "
                    "including enum values, list cardinality, and required evidence_text. "
                    "Code owns exact seconds and converts honest repeated slices into timed "
                    "continuation phases. For numeric "
                    "scenes, use only the active unit's eligible_numeric_truth_items and "
                    "preserve their meaning."
                )
        try:
            result = _invoke_chain(
                module_name=module_name,
                output_model=output_model,
                chain=chain,
                prompt_bundle=prompt_bundle,
                task_payload=json.dumps(payload, ensure_ascii=False, indent=2),
                config=config,
                metadata={**metadata, "attempt": attempt},
                llm_calls=llm_calls,
            )
            validation_errors = list(validate_output(result) if validate_output else [])
            if validation_errors:
                if llm_calls:
                    call_metadata = llm_calls[-1].setdefault("metadata", {})
                    call_metadata["validation_errors"] = validation_errors
                raise ValueError("; ".join(validation_errors))
            return result
        except Exception as exc:
            if propagate_content_filter and _is_content_filter_error(exc):
                raise
            last_error = f"{type(exc).__name__}: {exc}"
    raise RuntimeError(
        f"{module_name} failed after {max_attempts} bounded attempt(s): {last_error}"
    )


def _story_draft_errors(
    draft: dict[str, Any],
    *,
    story_id: str,
    section: dict[str, Any],
    source_index: dict[str, Any],
    asset_catalog_index: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    _normalize_overlong_story_scene_slots(draft, section=section, config=config)
    errors: list[str] = []
    covered_unit_orders: set[int] = set()
    real_anchor_asset_ids: set[str] = set()
    timing_candidates: list[dict[str, Any]] = []
    returned_story_id = clean_text(draft.get("story_id", ""))
    if not _story_ids_equivalent(returned_story_id, story_id):
        errors.append(
            f"returned story_id {returned_story_id!r}; expected {story_id!r}"
        )
    allowed = set(config["scene_policy"]["allowed_render_kinds"])
    allowed.discard("story_transition_scene")
    catalog_required_kinds = {
        clean_text(kind)
        for kind in config.get("asset_availability_policy", {}).get(
            "catalog_asset_required_render_kinds", []
        )
        if clean_text(kind)
    }
    available_assets = [
        asset
        for asset in asset_catalog_index.get("assets_by_story", {}).get(story_id, [])
        if clean_text(asset.get("status")) == "available"
        and CATALOG_RENDER_KIND_BY_ASSET_TYPE.get(clean_text(asset.get("asset_type")))
        in allowed
    ]
    available_anchor_ids = {
        clean_text(asset.get("asset_id")) for asset in available_assets
    }
    anchor_required = bool(config.get("require_real_anchor_per_story")) and bool(
        available_anchor_ids
    )
    section_start = safe_int(section.get("start_unit_order"), 1)
    section_end = safe_int(section.get("end_unit_order"), section_start)
    title_unit_order = section_start if section.get("title_card") else None
    for raw_scene in draft.get("scene_timeline", []):
        scene = _prepare_story_scene_draft(
            raw_scene,
            story_id=story_id,
            section=section,
            source_index=source_index,
            asset_catalog_index=asset_catalog_index,
            config=config,
        )
        scene_order = safe_int(scene.get("order"), 0)
        render_kind = clean_text(scene.get("render_kind", ""))
        prefix = f"scene order {scene_order}"
        start_unit = safe_int(scene.get("start_unit_order"), 0)
        end_unit = safe_int(scene.get("end_unit_order"), 0)
        if title_unit_order is not None and start_unit == end_unit == title_unit_order:
            # This exact unit is replaced by the deterministic moving story title.
            # Some providers echo it despite the explicit coverage contract.
            continue
        errors.extend(
            f"{prefix} {error}"
            for error in scene.get("contract_validation_errors", [])
            if clean_text(error)
        )
        errors.extend(
            f"{prefix} {error}"
            for error in _scene_recipe_policy_errors(scene, config=config)
        )
        if render_kind in OLD_CARD_RENDER_KINDS or render_kind not in allowed:
            errors.append(f"{prefix} uses unsupported render_kind {render_kind!r}")
            continue
        if render_kind in catalog_required_kinds and not clean_text(scene.get("asset_id")):
            errors.append(
                f"{prefix} {render_kind} requires an exact available story-owned asset_id"
            )
        catalog_asset, catalog_errors = _catalog_asset_for_scene(
            scene,
            story_id=story_id,
            render_kind=render_kind,
            catalog_index=asset_catalog_index,
        )
        errors.extend(f"{prefix} {error}" for error in catalog_errors)
        if catalog_asset:
            real_anchor_asset_ids.add(clean_text(catalog_asset.get("asset_id")))
            scene = _scene_with_catalog_asset(scene, catalog_asset)
        if start_unit < section_start or end_unit > section_end or end_unit < start_unit:
            errors.append(
                f"{prefix} unit range {start_unit}-{end_unit} is outside "
                f"story range {section_start}-{section_end}"
            )
            continue
        covered_unit_orders.update(range(start_unit, end_unit + 1))
        timing_candidates.append(scene)
        source_record_key, url = _source_for_scene(
            scene,
            story_id,
            render_kind,
            source_index,
        )
        canonical_excerpt = _section_unit_excerpt(section, start_unit, end_unit)
        planned_excerpt = clean_text(scene.get("script_excerpt", ""))
        script_excerpt = planned_excerpt or canonical_excerpt
        payload = _payload_for_scene(
            draft=scene,
            render_kind=render_kind,
            story_id=story_id,
            source_record_key=source_record_key,
            url=url,
            script_excerpt=script_excerpt,
            source_index=source_index,
            asset_catalog_index=asset_catalog_index,
        )
        payload = _payload_with_recipe(payload, scene)
        grounding = _semantic_grounding_for_scene(
            draft=scene,
            render_kind=render_kind,
            story_id=story_id,
            source_record_key=source_record_key,
            url=url,
            payload=payload,
            source_index=source_index,
        )
        if grounding["status"] != "grounded":
            errors.append(f"{prefix} grounding failed: {grounding['errors']}")

    # The first unit is owned by the deterministic moving story title. The LLM
    # must cover every remaining narration unit so production never invents a
    # text-heavy substitute for an omitted semantic scene.
    coverage_contract = _story_coverage_contract(
        section,
        max_scene_seconds=safe_float(config["scene_policy"].get("max_scene_seconds"), 14.0),
        hard_max_scene_seconds=_hard_max_scene_seconds(config["scene_policy"]),
        hard_cap_tolerance_seconds=safe_float(
            config["scene_policy"].get("hard_cap_tolerance_seconds"), 0.0
        ),
        unit_assignment_mode=clean_text(
            config["scene_policy"].get(
                "unit_assignment_mode", "one_scene_per_script_unit"
            )
        ),
    )
    expected_unit_orders = set(coverage_contract["required_unit_orders"])
    missing_unit_orders = sorted(expected_unit_orders - covered_unit_orders)
    if missing_unit_orders:
        errors.append(
            "scene timeline does not cover required story unit orders: "
            f"{missing_unit_orders}"
        )
    if coverage_contract.get("unit_assignment_mode") == "one_scene_per_script_unit":
        expected_slot_counts = Counter(
            (
                safe_int(slot.get("start_unit_order"), 0),
                safe_int(slot.get("end_unit_order"), 0),
            )
            for slot in coverage_contract.get("required_scene_slots", [])
        )
        actual_slot_counts = Counter(
            (
                safe_int(scene.get("start_unit_order"), 0),
                safe_int(scene.get("end_unit_order"), 0),
            )
            for scene in timing_candidates
        )
        missing_slots = list((expected_slot_counts - actual_slot_counts).elements())
        unexpected_slots = list((actual_slot_counts - expected_slot_counts).elements())
        if missing_slots or unexpected_slots:
            errors.append(
                "scene slot coverage mismatch; "
                f"missing_ranges={missing_slots}, unexpected_ranges={unexpected_slots}"
            )
    errors.extend(
        _story_scene_timing_errors(
            timing_candidates,
            section=section,
            max_scene_seconds=safe_float(config["scene_policy"].get("max_scene_seconds"), 14.0),
            hard_max_scene_seconds=_hard_max_scene_seconds(config["scene_policy"]),
            hard_cap_tolerance_seconds=safe_float(
                config["scene_policy"].get("hard_cap_tolerance_seconds"), 0.0
            ),
            duplicate_subscene_policy=clean_text(
                config["scene_policy"].get("duplicate_subscene_policy", "continue")
            ),
        )
    )
    if (
        anchor_required
        and not real_anchor_asset_ids
        and clean_text(config.get("real_anchor_failure_mode", "warn")) == "fail"
    ):
        errors.append(
            "story plan must reference at least one available verified_asset_catalog asset_id"
        )
    return errors


def _bookend_draft_errors(
    draft: dict[str, Any],
    *,
    sections: list[dict[str, Any]],
    source_index: dict[str, Any],
    asset_catalog_index: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    expected = {
        clean_text(section.get("section_type")): section
        for section in sections
        if clean_text(section.get("section_type")) in {"intro", "closing"}
    }
    returned_sections = [
        section for section in draft.get("sections", []) if isinstance(section, dict)
    ]
    returned_types = [clean_text(section.get("section_type")) for section in returned_sections]
    if Counter(returned_types) != Counter(expected.keys()):
        errors.append(
            "bookend section coverage mismatch; "
            f"expected={sorted(expected)}, returned={returned_types}"
        )

    allowed = set(config["scene_policy"]["allowed_render_kinds"])
    catalog_required_kinds = {
        clean_text(kind)
        for kind in config.get("asset_availability_policy", {}).get(
            "catalog_asset_required_render_kinds", []
        )
        if clean_text(kind)
    }
    for returned in returned_sections:
        section_type = clean_text(returned.get("section_type"))
        section = expected.get(section_type)
        if not section:
            continue
        _normalize_overlong_story_scene_slots(returned, section=section, config=config)
        section_start = safe_int(section.get("start_unit_order"), 1)
        section_end = safe_int(section.get("end_unit_order"), section_start)
        covered_unit_orders: set[int] = set()
        timing_candidates: list[dict[str, Any]] = []
        for raw_scene in returned.get("scene_timeline", []):
            if not isinstance(raw_scene, dict):
                errors.append(f"{section_type} contains a non-object scene")
                continue
            scene, owner_story_id = _prepare_bookend_scene_draft(
                raw_scene,
                section=section,
                source_index=source_index,
                asset_catalog_index=asset_catalog_index,
                config=config,
            )
            scene_order = safe_int(scene.get("order"), 0)
            prefix = f"{section_type} scene order {scene_order}"
            render_kind = clean_text(scene.get("render_kind"))
            errors.extend(
                f"{prefix} {error}"
                for error in _scene_recipe_policy_errors(scene, config=config)
            )
            if render_kind in OLD_CARD_RENDER_KINDS or render_kind not in allowed:
                errors.append(f"{prefix} uses unsupported render_kind {render_kind!r}")
                continue
            if render_kind in catalog_required_kinds and not clean_text(scene.get("asset_id")):
                errors.append(f"{prefix} requires an exact available catalog asset_id")
            catalog_asset, catalog_errors = _catalog_asset_for_scene(
                scene,
                story_id=owner_story_id,
                render_kind=render_kind,
                catalog_index=asset_catalog_index,
            )
            errors.extend(f"{prefix} {error}" for error in catalog_errors)
            if catalog_asset:
                scene = _scene_with_catalog_asset(scene, catalog_asset)
            start_unit = safe_int(scene.get("start_unit_order"), 0)
            end_unit = safe_int(scene.get("end_unit_order"), 0)
            if start_unit < section_start or end_unit > section_end or end_unit < start_unit:
                errors.append(
                    f"{prefix} unit range {start_unit}-{end_unit} is outside "
                    f"{section_type} range {section_start}-{section_end}"
                )
                continue
            covered_unit_orders.update(range(start_unit, end_unit + 1))
            timing_candidates.append(scene)
            source_record_key, url = _source_for_scene(
                scene,
                owner_story_id,
                render_kind,
                source_index,
            )
            script_excerpt = _section_unit_excerpt(section, start_unit, end_unit)
            payload = _payload_for_scene(
                draft=scene,
                render_kind=render_kind,
                story_id=owner_story_id,
                source_record_key=source_record_key,
                url=url,
                script_excerpt=script_excerpt,
                source_index=source_index,
                asset_catalog_index=asset_catalog_index,
            )
            payload = _payload_with_recipe(payload, scene)
            grounding = _semantic_grounding_for_scene(
                draft=scene,
                render_kind=render_kind,
                story_id=owner_story_id,
                source_record_key=source_record_key,
                url=url,
                payload=payload,
                source_index=source_index,
            )
            if grounding["status"] != "grounded":
                errors.append(f"{prefix} grounding failed: {grounding['errors']}")

        coverage_contract = _story_coverage_contract(
            section,
            max_scene_seconds=safe_float(config["scene_policy"].get("max_scene_seconds"), 14.0),
            hard_max_scene_seconds=_hard_max_scene_seconds(config["scene_policy"]),
            hard_cap_tolerance_seconds=safe_float(
                config["scene_policy"].get("hard_cap_tolerance_seconds"), 0.0
            ),
            unit_assignment_mode=clean_text(
                config["scene_policy"].get("unit_assignment_mode", "one_scene_per_script_unit")
            ),
        )
        expected_orders = set(coverage_contract["required_unit_orders"])
        missing_orders = sorted(expected_orders - covered_unit_orders)
        if missing_orders:
            errors.append(f"{section_type} does not cover script units {missing_orders}")
        expected_slots = Counter(
            (
                safe_int(slot.get("start_unit_order"), 0),
                safe_int(slot.get("end_unit_order"), 0),
            )
            for slot in coverage_contract.get("required_scene_slots", [])
        )
        actual_slots = Counter(
            (
                safe_int(scene.get("start_unit_order"), 0),
                safe_int(scene.get("end_unit_order"), 0),
            )
            for scene in timing_candidates
        )
        if expected_slots != actual_slots:
            errors.append(
                f"{section_type} scene slot coverage mismatch; "
                f"missing={list((expected_slots - actual_slots).elements())}, "
                f"unexpected={list((actual_slots - expected_slots).elements())}"
            )
        errors.extend(
            f"{section_type} {error}"
            for error in _story_scene_timing_errors(
                timing_candidates,
                section=section,
                max_scene_seconds=safe_float(
                    config["scene_policy"].get("max_scene_seconds"), 14.0
                ),
                hard_max_scene_seconds=_hard_max_scene_seconds(config["scene_policy"]),
                hard_cap_tolerance_seconds=safe_float(
                    config["scene_policy"].get("hard_cap_tolerance_seconds"), 0.0
                ),
                duplicate_subscene_policy=clean_text(
                    config["scene_policy"].get("duplicate_subscene_policy", "continue")
                ),
            )
        )
    return dedupe(errors)


def _normalize_overlong_story_scene_slots(
    draft: dict[str, Any],
    *,
    section: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    """Expand an honest visual into timed continuation slices when configured."""

    policy = config.get("scene_policy") if isinstance(config.get("scene_policy"), dict) else {}
    if clean_text(policy.get("duplicate_subscene_policy", "continue")) != "continue":
        return []
    scenes = draft.get("scene_timeline")
    if not isinstance(scenes, list) or not scenes:
        return []
    coverage = _story_coverage_contract(
        section,
        max_scene_seconds=safe_float(policy.get("max_scene_seconds"), 14.0),
        hard_max_scene_seconds=_hard_max_scene_seconds(policy),
        hard_cap_tolerance_seconds=safe_float(
            policy.get("hard_cap_tolerance_seconds"), 0.0
        ),
        unit_assignment_mode=clean_text(
            policy.get("unit_assignment_mode", "one_scene_per_script_unit")
        ),
    )
    expected_counts = Counter(
        (
            safe_int(slot.get("start_unit_order"), 0),
            safe_int(slot.get("end_unit_order"), 0),
        )
        for slot in coverage.get("required_scene_slots", [])
    )
    actual_counts = Counter(
        (
            safe_int(scene.get("start_unit_order"), 0),
            safe_int(scene.get("end_unit_order"), 0),
        )
        for scene in scenes
        if isinstance(scene, dict)
    )
    deficits = {
        unit_range: expected_count - actual_counts.get(unit_range, 0)
        for unit_range, expected_count in expected_counts.items()
        if actual_counts.get(unit_range, 0) > 0
        and actual_counts.get(unit_range, 0) < expected_count
        and unit_range[0] == unit_range[1]
    }
    if not deficits:
        return []

    seen_counts: Counter[tuple[int, int]] = Counter()
    expanded: list[dict[str, Any]] = []
    repairs: list[str] = []
    for raw_scene in scenes:
        if not isinstance(raw_scene, dict):
            continue
        scene = deepcopy(raw_scene)
        unit_range = (
            safe_int(scene.get("start_unit_order"), 0),
            safe_int(scene.get("end_unit_order"), 0),
        )
        expanded.append(scene)
        seen_counts[unit_range] += 1
        if (
            unit_range not in deficits
            or seen_counts[unit_range] != actual_counts[unit_range]
        ):
            continue
        for _ in range(deficits[unit_range]):
            expanded.append(deepcopy(scene))
        repairs.append(
            f"expanded overlong unit {unit_range[0]} into "
            f"{expected_counts[unit_range]} timed continuation slices"
        )

    for order, scene in enumerate(expanded, start=1):
        scene["order"] = order
    draft["scene_timeline"] = expanded
    warnings = draft.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    draft["warnings"] = dedupe([*warnings, *repairs])
    return repairs


def _story_scene_timing_errors(
    scenes: list[dict[str, Any]],
    *,
    section: dict[str, Any],
    max_scene_seconds: float,
    hard_max_scene_seconds: float | None = None,
    hard_cap_tolerance_seconds: float = 0.0,
    duplicate_subscene_policy: str = "continue",
) -> list[str]:
    """Validate objective timing structure before seconds are assigned to scenes."""

    errors: list[str] = []
    hard_cap = max_scene_seconds
    if hard_max_scene_seconds is not None:
        hard_cap = max(max_scene_seconds, hard_max_scene_seconds)
    hard_cap += max(0.0, hard_cap_tolerance_seconds)
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    ranges: list[tuple[int, int]] = []
    for scene in scenes:
        start = safe_int(scene.get("start_unit_order"), 0)
        end = safe_int(scene.get("end_unit_order"), start)
        groups.setdefault((start, end), []).append(scene)
        if (start, end) not in ranges:
            ranges.append((start, end))

    for index, first in enumerate(ranges):
        for second in ranges[index + 1 :]:
            if first == second:
                continue
            if max(first[0], second[0]) <= min(first[1], second[1]):
                errors.append(
                    "scene unit ranges overlap ambiguously: "
                    f"{first[0]}-{first[1]} and {second[0]}-{second[1]}; "
                    "use non-overlapping ranges, except for distinct sub-scenes that target the same overlong unit"
                )

    for (start, end), grouped in sorted(groups.items()):
        duration = _section_unit_range_duration(section, start, end)
        if len(grouped) > 1 and (start != end or duration <= max_scene_seconds + 0.01):
            errors.append(
                f"unit range {start}-{end} has {len(grouped)} competing scenes; "
                "multiple scenes may share a range only when one script unit is longer than max_scene_seconds"
            )
        if duration > hard_cap + 0.01:
            if start != end:
                errors.append(
                    f"unit range {start}-{end} lasts {duration:.2f}s, above the {hard_cap:.2f}s hard cap; "
                    "split it into non-overlapping semantic unit ranges"
                )
                continue
            required_count = max(2, math.ceil(duration / hard_cap))
            if len(grouped) != required_count:
                errors.append(
                    f"overlong unit {start} lasts {duration:.2f}s and requires exactly "
                    f"{required_count} distinct visual treatments; found {len(grouped)}"
                )
            signatures = [_provider_visual_signature(scene) for scene in grouped]
            if (
                len(set(signatures)) != len(signatures)
                and duplicate_subscene_policy == "fail"
            ):
                errors.append(
                    f"overlong unit {start} contains duplicated render payloads; every sub-scene must use a distinct visual treatment"
                )
    return dedupe(errors)


def _section_unit_range_duration(section: dict[str, Any], start_unit: int, end_unit: int) -> float:
    units = [
        unit
        for unit in section.get("script_units", [])
        if start_unit <= safe_int(unit.get("order"), 0) <= end_unit
    ]
    if not units:
        return 0.0
    start = safe_float(units[0].get("start_seconds"), 0.0)
    end = safe_float(units[-1].get("end_seconds"), start)
    return max(0.0, end - start)


def _provider_visual_signature(scene: dict[str, Any]) -> str:
    payload_raw = clean_text(scene.get("payload_json", ""))
    try:
        payload = json.loads(payload_raw) if payload_raw else {}
    except json.JSONDecodeError:
        payload = payload_raw
    if isinstance(payload, dict):
        payload = _semantic_visual_payload(payload)
    return json.dumps(
        {
            "render_kind": clean_text(scene.get("render_kind", "")),
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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
    try:
        result = chain.invoke(prompt_inputs)
    except Exception as exc:
        duration = time.time() - started
        llm_calls.append(
            build_llm_call_log(
                module_name=module_name,
                provider=config["provider"],
                model=config["model"],
                rendered_prompt=rendered_prompt,
                raw_response=None,
                parsed_output=None,
                metadata=metadata,
                duration_seconds=duration,
                parse_error=f"{type(exc).__name__}: {exc}",
            )
        )
        raise
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
        detail = clean_text(str(parsing_error)) or "parsed output was empty"
        error = ValueError(f"LLM structured output failed for {module_name}: {detail}")
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


def _exception_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _is_content_filter_error(exc: Exception) -> bool:
    status_code = _exception_status_code(exc)
    text = str(exc).casefold().replace("_", " ")
    markers = ("content filter", "high risk", "highrisk")
    return status_code in {400, 403} and any(marker in text for marker in markers)


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
    bookend_drafts: dict[str, dict[str, Any]],
    story_drafts: dict[str, dict[str, Any]],
    config: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    script_provenance: dict[str, Any],
    voiceover_provenance: dict[str, Any] | None,
    asset_catalog: dict[str, Any],
    asset_catalog_provenance: dict[str, Any] | None,
    visual_editor_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scene_timeline = _build_scene_timeline(
        story_sections=story_sections,
        script_units=script_units,
        stories=stories,
        source_index=source_index,
        bookend_drafts=bookend_drafts,
        story_drafts=story_drafts,
        asset_catalog_index=_asset_catalog_index(asset_catalog),
        config=config,
    )
    asset_manifest = _build_asset_manifest(scene_timeline)
    total_duration = _total_duration(script_units, voiceover_package, video_packet)
    coverage = _coverage_report(scene_timeline, script_units, total_duration, config)
    visual_scene_plan = {
        "package_type": PACKAGE_TYPE,
        "selected_format": SUPPORTED_FORMAT,
        "planning_strategy": (
            "episode_director_plus_bookends_plus_per_story_plus_bounded_editor"
            if (visual_editor_report or {}).get("enabled")
            else "episode_director_plus_bookends_plus_per_story"
        ),
        "llm_routes": _llm_route_summary(config),
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
        "asset_catalog": asset_catalog,
        "story_time_ranges": story_ranges,
        "planner_warnings": _planner_warnings(story_drafts),
        "visual_editor": visual_editor_report or {
            "enabled": False,
            "reviewed_story_count": 0,
            "revision_count": 0,
            "failure_count": 0,
            "stories": [],
        },
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
    return visual_scene_plan


def _build_scene_timeline(
    *,
    story_sections: list[dict[str, Any]],
    script_units: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    source_index: dict[str, Any],
    story_drafts: dict[str, dict[str, Any]],
    config: dict[str, Any],
    bookend_drafts: dict[str, dict[str, Any]] | None = None,
    asset_catalog_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    asset_catalog_index = asset_catalog_index or {}
    bookend_drafts = bookend_drafts or {}
    stories_by_id = {clean_text(story.get("story_id", "")): story for story in stories}
    policy = config["scene_policy"]
    counts: Counter[str] = Counter()
    stitched: list[dict[str, Any]] = []
    for section in story_sections:
        story_id = clean_text(section.get("story_id", ""))
        story = stories_by_id.get(story_id, {})
        story_draft = story_drafts.get(story_id, {})
        if (
            section.get("section_type") == "story"
            and story_draft.get("planning_failed")
            and not config.get("allow_deterministic_story_fallbacks")
        ):
            # Keep the partial plan diagnostic-only. Filling an entire failed
            # story with generic kinetic scenes hides the real planner defect.
            continue
        candidates = []
        if section.get("section_type") == "story":
            candidates = _normalize_story_candidate_scenes(
                story=story,
                section=section,
                source_index=source_index,
                story_draft=story_draft,
                asset_catalog_index=asset_catalog_index,
                counts=counts,
                config=config,
            )
        else:
            candidates = _normalize_bookend_candidate_scenes(
                section=section,
                source_index=source_index,
                bookend_draft=bookend_drafts.get(
                    clean_text(section.get("section_type")), {}
                ),
                asset_catalog_index=asset_catalog_index,
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
                allow_unplanned_range_fallback=(
                    section.get("section_type") == "story"
                    and bool(config.get("allow_deterministic_story_fallbacks"))
                    and bool(story_draft.get("fallback_used"))
                ),
            )
        )
    return _finalize_scene_order(stitched, policy)


def _normalize_story_candidate_scenes(
    *,
    story: dict[str, Any],
    section: dict[str, Any],
    source_index: dict[str, Any],
    story_draft: dict[str, Any],
    asset_catalog_index: dict[str, Any],
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
        draft_start = safe_int(draft.get("start_unit_order"), 0)
        draft_end = safe_int(draft.get("end_unit_order"), 0)
        draft = _prepare_story_scene_draft(
            draft,
            story_id=story_id,
            section=section,
            source_index=source_index,
            asset_catalog_index=asset_catalog_index,
            config=config,
        )
        start_unit = min(section_end, max(section_start, safe_int(draft.get("start_unit_order"), section_start)))
        end_unit = min(section_end, max(start_unit, safe_int(draft.get("end_unit_order"), start_unit)))
        render_kind = _normalize_render_kind(draft, policy, counts, story_id, source_index)
        catalog_asset, catalog_errors = _catalog_asset_for_scene(
            draft,
            story_id=story_id,
            render_kind=render_kind,
            catalog_index=asset_catalog_index,
        )
        if catalog_errors:
            raise ValueError("; ".join(catalog_errors))
        if catalog_asset:
            draft = _scene_with_catalog_asset(draft, catalog_asset)
        source_record_key, url = _source_for_scene(draft, story_id, render_kind, source_index)
        script_excerpt = _section_unit_excerpt(section, start_unit, end_unit)
        payload = _payload_for_scene(
            draft=draft,
            render_kind=render_kind,
            story_id=story_id,
            source_record_key=source_record_key,
            url=url,
            script_excerpt=script_excerpt,
            source_index=source_index,
            asset_catalog_index=asset_catalog_index,
        )
        payload = _payload_with_recipe(payload, draft)
        grounding = _semantic_grounding_for_scene(
            draft=draft,
            render_kind=render_kind,
            story_id=story_id,
            source_record_key=source_record_key,
            url=url,
            payload=payload,
            source_index=source_index,
        )
        candidates.append(
            {
                "planner_order": safe_int(draft.get("order"), len(candidates) + 1),
                "story_id": story_id,
                "story_title": clean_text(story.get("story_title", "")),
                "section_type": "story",
                "start_unit_order": start_unit,
                "end_unit_order": end_unit,
                "render_kind": render_kind,
                "script_excerpt": script_excerpt,
                "visual_intent": clean_text(draft.get("visual_intent", "")) or _default_visual_intent(render_kind),
                "payload": payload,
                "source_record_keys": grounding["evidence_record_keys"],
                "evidence_truth_ids": grounding["evidence_truth_ids"],
                "source_urls": _scene_source_urls(url, payload),
                "semantic_grounding": grounding,
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
    opening_anchor = next(
        (
            candidate
            for candidate in candidates
            if safe_int(candidate.get("start_unit_order"), section_start) <= section_start
            <= safe_int(candidate.get("end_unit_order"), section_start)
            and clean_text(candidate.get("render_kind"))
            in {"context_image_scene", "broll_video_scene", "logo_reveal_scene"}
            and clean_text((candidate.get("payload") or {}).get("asset_id"))
        ),
        None,
    )
    allowed_kinds = set(policy["allowed_render_kinds"])
    if "story_transition_scene" in allowed_kinds:
        title_kind = "story_transition_scene"
    elif "transition_stinger_scene" in allowed_kinds:
        title_kind = "transition_stinger_scene"
    else:
        title_kind = "logo_reveal_scene"
    story_number = safe_int((story.get("video_segment") or {}).get("segment_order"), 1)
    title_payload = {
        "recipe_id": "chapter_opener",
        "story_number": str(story_number),
        "eyebrow": f"STORY {story_number}",
        "headline": display_title,
        "subtitle": subtitle,
        "accent_words": [],
        "motion_style": "editorial_wipe",
        "voice_behavior": "continue",
        "configured_title_seconds": safe_float(title_card.get("duration_seconds"), 2.8),
    }
    if opening_anchor and title_kind == "story_transition_scene":
        opening_payload = opening_anchor.get("payload") or {}
        opening_kind = clean_text(opening_anchor.get("render_kind"))
        title_payload.update(
            {
                "asset_id": clean_text(opening_payload.get("asset_id")),
                "background_media_type": {
                    "context_image_scene": "image",
                    "broll_video_scene": "video",
                    "logo_reveal_scene": "logo",
                }[opening_kind],
                "background_render_kind": opening_kind,
                "background_motion_style": clean_text(opening_payload.get("motion_style"))
                or "slow_push",
                "primary_entity": clean_text(opening_payload.get("primary_entity")),
                "entities": normalize_text_list(opening_payload.get("entities")),
                "logo_strategy": clean_text(opening_payload.get("logo_strategy")),
            }
        )
    if title_kind == "transition_stinger_scene":
        title_payload = {
            "transition_label": subtitle or display_title,
            "subtitle": display_title if subtitle else "",
            "background_motif": "newsroom_grid",
            "motion_style": "signal_wipe",
            "eyebrow": f"STORY {story_number}",
            "voice_behavior": "continue",
            "configured_title_seconds": safe_float(title_card.get("duration_seconds"), 2.8),
        }
    if title_kind == "logo_reveal_scene":
        primary_entity = _primary_entity_for_story(story_id, source_index)
        title_payload = {
            "entities": [primary_entity] if primary_entity else [],
            "primary_entity": primary_entity,
            "logo_strategy": "simple_icons_then_favicon_then_text",
            "companion_text": display_title,
            "motion_style": "spotlight",
            "voice_behavior": "continue",
        }
    title_candidate = {
        "planner_order": 0,
        "story_id": story_id,
        "story_title": clean_text(story.get("story_title", "")),
        "section_type": "story",
        "start_unit_order": section_start,
        "end_unit_order": section_start,
        "render_kind": title_kind,
        "script_excerpt": _section_unit_excerpt(section, section_start, section_start),
        "visual_intent": (
            "Overlay the story title on the semantically selected opening media while narration continues."
            if opening_anchor
            else "Introduce the story with a short moving title while narration continues."
        ),
        "payload": title_payload,
        "source_record_keys": list((opening_anchor or {}).get("source_record_keys", [])),
        "source_urls": list((opening_anchor or {}).get("source_urls", [])),
        "semantic_grounding": {
            "status": "grounded",
            "basis": "editorial_transition",
            "evidence_record_keys": [],
            "evidence_text": clean_text(title_payload.get("transition_label") or title_payload.get("companion_text", "")),
            "errors": [],
        },
        "reason": (
            "Deterministic story-title overlay using the story planner's opening catalog asset."
            if opening_anchor
            else "Deterministic story-title reset anchored to the canonical transition beat."
        ),
    }
    return [title_candidate, *remaining]


def _normalize_bookend_candidate_scenes(
    *,
    section: dict[str, Any],
    source_index: dict[str, Any],
    bookend_draft: dict[str, Any],
    asset_catalog_index: dict[str, Any],
    counts: Counter[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    policy = config["scene_policy"]
    section_type = clean_text(section.get("section_type"))
    section_start = safe_int(section.get("start_unit_order"), 1)
    section_end = safe_int(section.get("end_unit_order"), section_start)
    candidates: list[dict[str, Any]] = []
    for raw_draft in sorted(
        [scene for scene in bookend_draft.get("scene_timeline", []) if isinstance(scene, dict)],
        key=lambda scene: safe_int(scene.get("order"), 999999),
    ):
        draft, owner_story_id = _prepare_bookend_scene_draft(
            raw_draft,
            section=section,
            source_index=source_index,
            asset_catalog_index=asset_catalog_index,
            config=config,
        )
        start_unit = min(
            section_end,
            max(section_start, safe_int(draft.get("start_unit_order"), section_start)),
        )
        end_unit = min(
            section_end,
            max(start_unit, safe_int(draft.get("end_unit_order"), start_unit)),
        )
        render_kind = _normalize_render_kind(
            draft,
            policy,
            counts,
            owner_story_id,
            source_index,
        )
        catalog_asset, catalog_errors = _catalog_asset_for_scene(
            draft,
            story_id=owner_story_id,
            render_kind=render_kind,
            catalog_index=asset_catalog_index,
        )
        if catalog_errors:
            raise ValueError("; ".join(catalog_errors))
        if catalog_asset:
            draft = _scene_with_catalog_asset(draft, catalog_asset)
        source_record_key, url = _source_for_scene(
            draft,
            owner_story_id,
            render_kind,
            source_index,
        )
        script_excerpt = _section_unit_excerpt(section, start_unit, end_unit)
        payload = _payload_for_scene(
            draft=draft,
            render_kind=render_kind,
            story_id=owner_story_id,
            source_record_key=source_record_key,
            url=url,
            script_excerpt=script_excerpt,
            source_index=source_index,
            asset_catalog_index=asset_catalog_index,
        )
        payload = _payload_with_recipe(payload, draft)
        grounding = _semantic_grounding_for_scene(
            draft=draft,
            render_kind=render_kind,
            story_id=owner_story_id,
            source_record_key=source_record_key,
            url=url,
            payload=payload,
            source_index=source_index,
        )
        candidates.append(
            {
                "planner_order": safe_int(draft.get("order"), len(candidates) + 1),
                "story_id": "",
                "story_title": "",
                "section_type": section_type,
                "start_unit_order": start_unit,
                "end_unit_order": end_unit,
                "render_kind": render_kind,
                "script_excerpt": script_excerpt,
                "visual_intent": clean_text(draft.get("visual_intent"))
                or _default_visual_intent(render_kind),
                "payload": payload,
                "source_record_keys": grounding["evidence_record_keys"],
                "evidence_truth_ids": grounding["evidence_truth_ids"],
                "source_urls": _scene_source_urls(url, payload),
                "semantic_grounding": grounding,
                "reason": clean_text(draft.get("reason")),
            }
        )
    return candidates


def _expand_provider_scene_draft(draft: dict[str, Any]) -> dict[str, Any]:
    payload_raw = clean_text(draft.get("payload_json", ""))
    if not payload_raw:
        return dict(draft)
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("visual scene payload_json is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("visual scene payload_json must encode an object")
    expanded = dict(payload)
    expanded.update(draft)
    return expanded


def _stitch_section(
    *,
    section: dict[str, Any],
    candidates: list[dict[str, Any]],
    script_units: list[dict[str, Any]],
    story: dict[str, Any],
    source_index: dict[str, Any],
    counts: Counter[str],
    policy: dict[str, Any],
    allow_unplanned_range_fallback: bool = False,
) -> list[dict[str, Any]]:
    start_unit = safe_int(section.get("start_unit_order"), 1)
    end_unit = safe_int(section.get("end_unit_order"), start_unit)
    if start_unit < 1 or end_unit < start_unit:
        return []
    scenes: list[dict[str, Any]] = []
    cursor = start_unit
    usable_candidates = sorted(
        candidates,
        key=lambda scene: (
            safe_int(scene.get("start_unit_order"), 999999),
            safe_int(scene.get("end_unit_order"), 999999),
            safe_int(scene.get("planner_order"), 999999),
        ),
    )
    candidate_groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for candidate in usable_candidates:
        key = (
            min(end_unit, max(start_unit, safe_int(candidate.get("start_unit_order"), start_unit))),
            min(end_unit, max(start_unit, safe_int(candidate.get("end_unit_order"), start_unit))),
        )
        candidate_groups.setdefault(key, []).append(candidate)

    for (candidate_start, candidate_end), grouped_candidates in candidate_groups.items():
        if candidate_end < candidate_start:
            raise ValueError(f"Invalid visual candidate unit range {candidate_start}-{candidate_end}")
        if candidate_start < cursor:
            raise ValueError(
                f"Visual candidate unit range {candidate_start}-{candidate_end} overlaps a previously stitched range"
            )
        if candidate_start > cursor:
            if not allow_unplanned_range_fallback:
                raise ValueError(
                    f"Visual plan leaves script units {cursor}-{candidate_start - 1} uncovered"
                )
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
        if len(grouped_candidates) == 1:
            candidate = grouped_candidates[0]
            full_slice = _range_time_slice(candidate_start, candidate_end, script_units)
            duration = max(
                0.0,
                safe_float(full_slice.get("end_seconds"), 0.0)
                - safe_float(full_slice.get("start_seconds"), 0.0),
            )
            hard_cap = _effective_hard_max_scene_seconds(policy)
            if candidate_start == candidate_end and duration > hard_cap + 0.01:
                required_count = max(2, math.ceil(duration / hard_cap))
                raise ValueError(
                    f"Overlong visual unit {candidate_start} requires {required_count} "
                    "distinct planner scenes; production will not clone one visual treatment"
                )
            else:
                candidate_scene = _scene_from_candidate_slice(candidate, full_slice, script_units)
                if candidate_scene["duration_seconds"] > hard_cap + 0.01:
                    raise ValueError(
                        f"Visual candidate range {candidate_start}-{candidate_end} exceeds "
                        "hard_max_scene_seconds; split it at a semantic unit boundary"
                    )
                scenes.append(candidate_scene)
                counts[clean_text(candidate.get("render_kind", ""))] += 1
        else:
            grouped_candidates = _timing_continuation_variants(grouped_candidates)
            unit_slices = _semantic_candidate_time_slices(
                candidate_start,
                candidate_end,
                len(grouped_candidates),
                script_units,
            )
            for candidate, unit_slice in zip(grouped_candidates, unit_slices, strict=True):
                scenes.append(_scene_from_candidate_slice(candidate, unit_slice, script_units))
                counts[clean_text(candidate.get("render_kind", ""))] += 1
        cursor = candidate_end + 1
        if cursor > end_unit:
            break
    if cursor <= end_unit:
        if not allow_unplanned_range_fallback:
            raise ValueError(f"Visual plan leaves script units {cursor}-{end_unit} uncovered")
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


def _timing_continuation_variants(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Turn repeated timing slices into one continuous visual treatment."""

    if len(candidates) < 2:
        return candidates
    signatures = [_render_payload_signature(candidate) for candidate in candidates]
    if len(set(signatures)) == len(signatures):
        return candidates

    first = candidates[0]
    group_id = clean_text(
        f"{first.get('story_id', 'episode')}:{first.get('start_unit_order', 0)}:"
        f"{first.get('end_unit_order', 0)}"
    )
    variants: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        variant = dict(candidate)
        payload = (
            dict(candidate.get("payload", {}))
            if isinstance(candidate.get("payload"), dict)
            else {}
        )
        payload.update(
            {
                "continuation_group_id": group_id,
                "continuation_index": index,
                "continuation_count": len(candidates),
            }
        )
        render_kind = clean_text(candidate.get("render_kind"))
        if render_kind == "simple_explainer_scene":
            labels = [
                clean_text(item.get("label"))
                for item in payload.get("items", [])
                if isinstance(item, dict) and clean_text(item.get("label"))
            ]
            if labels:
                payload["focus_item_label"] = labels[(index - 1) % len(labels)]
        elif render_kind == "source_article_scene":
            payload["crop_strategy"] = (
                "headline_then_body" if index == 1 else "target_text_focus"
            )
            payload["motion_style"] = (
                "slow_push" if index == 1 else "highlight_scan"
            )
        elif render_kind in {"context_image_scene", "broll_video_scene"}:
            payload["shot_style"] = "wide" if index == 1 else "detail"
            payload["motion_style"] = "slow_push" if index == 1 else "detail_zoom"
        variant["payload"] = payload
        variants.append(variant)
    return variants


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
    if clean_text(section.get("section_type")) in {"intro", "closing"}:
        # Bookend beats often tease different stories or perform different jobs.
        # Preserve those authored boundaries instead of merging unrelated ideas
        # into one long text scene. A single authored beat may still exceed the
        # render cap, so split that beat without crossing into its neighbor.
        unit_slices = []
        hard_cap = _effective_hard_max_scene_seconds(policy)
        for order in range(start_unit, end_unit + 1):
            unit_slice = _range_time_slice(order, order, script_units)
            duration = max(
                0.0,
                safe_float(unit_slice.get("end_seconds"), 0.0)
                - safe_float(unit_slice.get("start_seconds"), 0.0),
            )
            if duration > hard_cap + 0.01:
                unit_slices.extend(
                    _fixed_time_slices(order, order, script_units, policy)
                )
            else:
                unit_slices.append(unit_slice)
    else:
        unit_slices = _unit_time_slices(start_unit, end_unit, script_units, policy)
    for group_index, unit_slice in enumerate(unit_slices, start=1):
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
    unit_slice = _range_time_slice(start_unit, end_unit, script_units)
    duration = safe_float(unit_slice.get("end_seconds"), 0.0) - safe_float(unit_slice.get("start_seconds"), 0.0)
    if duration > _effective_hard_max_scene_seconds(policy) + 0.01:
        raise ValueError(
            "A semantic visual candidate cannot be copied across timing slices; "
            "request distinct planner sub-scenes for the overlong narration range"
        )
    return [_scene_from_candidate_slice(candidate, unit_slice, script_units)]


def _range_time_slice(
    start_unit: int,
    end_unit: int,
    script_units: list[dict[str, Any]],
) -> dict[str, Any]:
    range_units = script_units[start_unit - 1 : end_unit]
    if not range_units:
        return {
            "start_unit_order": start_unit,
            "end_unit_order": end_unit,
            "unit_orders": list(range(start_unit, end_unit + 1)),
            "start_seconds": 0.0,
            "end_seconds": 0.0,
        }
    return {
        "start_unit_order": start_unit,
        "end_unit_order": end_unit,
        "unit_orders": [safe_int(unit.get("order"), start_unit) for unit in range_units],
        "start_seconds": round(safe_float(range_units[0].get("start_seconds"), 0.0), 2),
        "end_seconds": round(
            safe_float(
                range_units[-1].get("end_seconds"),
                safe_float(range_units[0].get("start_seconds"), 0.0),
            ),
            2,
        ),
    }


def _semantic_candidate_time_slices(
    start_unit: int,
    end_unit: int,
    candidate_count: int,
    script_units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    full_slice = _range_time_slice(start_unit, end_unit, script_units)
    start_seconds = safe_float(full_slice.get("start_seconds"), 0.0)
    end_seconds = safe_float(full_slice.get("end_seconds"), start_seconds)
    duration = max(0.0, end_seconds - start_seconds)
    count = max(1, candidate_count)
    balanced = duration / count if count else duration
    slices: list[dict[str, Any]] = []
    cursor = start_seconds
    for index in range(count):
        slice_end = end_seconds if index == count - 1 else cursor + balanced
        slices.append(
            {
                **full_slice,
                "start_seconds": round(cursor, 2),
                "end_seconds": round(slice_end, 2),
                "semantic_subscene_index": index + 1,
                "semantic_subscene_count": count,
            }
        )
        cursor = slice_end
    return slices


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
                "slice_index": slice_index + 1,
                "slice_count": slice_count,
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


def _visual_beats_for_slice(
    unit_slice: dict[str, Any],
    script_units: list[dict[str, Any]],
    scene_start_seconds: float,
    *,
    text_override: str = "",
) -> list[dict[str, Any]]:
    orders = {safe_int(order, 0) for order in unit_slice.get("unit_orders", [])}
    beats: list[dict[str, Any]] = []
    for unit in script_units:
        order = safe_int(unit.get("order"), 0)
        if order not in orders:
            continue
        if text_override and len(orders) == 1:
            start = scene_start_seconds
            end = safe_float(unit_slice.get("end_seconds"), start)
        else:
            start = safe_float(unit.get("start_seconds"), scene_start_seconds)
            end = safe_float(unit.get("end_seconds"), start)
        text = clean_text(text_override) if text_override and len(orders) == 1 else clean_text(unit.get("text", ""))
        if not text:
            continue
        beats.append(
            {
                "unit_order": order,
                "beat_id": clean_text(unit.get("beat_id", "")),
                "beat_type": clean_text(unit.get("beat_type", "")),
                "beat_function": clean_text(unit.get("beat_function", "")),
                "support_truth_ids": list(unit.get("support_truth_ids", [])),
                "creative_device": clean_text(unit.get("creative_device", "")) or "none",
                "visual_goal": clean_text(unit.get("visual_goal", "")),
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "relative_start_seconds": round(max(0.0, start - scene_start_seconds), 2),
                "relative_end_seconds": round(max(0.0, end - scene_start_seconds), 2),
                "text": text,
                "visual_action": clean_text((unit.get("visual_brief") or {}).get("visual_intent", "")) or "reveal_point",
                "visual_brief": unit.get("visual_brief", {}),
                "source_record_keys": unit.get("source_record_keys", []),
                "emphasis_words": meaningful_words(text)[:4],
            }
        )
    return beats


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
    del counts, group_index
    story_id = clean_text(section.get("story_id", ""))
    section_type = clean_text(section.get("section_type", ""))
    excerpt = _script_excerpt_for_time_slice(script_units, unit_slice)
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
    first_key = hinted_keys[0] if hinted_keys else ""
    record = source_index["records_by_key"].get(first_key, {})
    url = clean_text(record.get("url", ""))
    allowed = set(policy.get("allowed_render_kinds", []))
    use_source = (
        section_type == "story"
        and visual_intent == "source_proof"
        and bool(first_key)
        and bool(url)
        and "source_article_scene" in allowed
    )
    if use_source:
        render_kind = "source_article_scene"
    elif "editorial_text_scene" in allowed:
        render_kind = "editorial_text_scene"
    else:
        render_kind = "kinetic_type_scene"
    if render_kind not in allowed:
        raise ValueError(
            "The planner left narration uncovered, but the safe fallback render kind "
            f"{render_kind!r} is not allowed by config.scene_policy.allowed_render_kinds."
        )
    draft = {
        "render_kind": render_kind,
        "source_record_key": first_key,
        "url": url,
        "target_text": (record.get("screenshot_target_candidates") or [record.get("title", "")])[0] if record else "",
        "overlay_headline": clean_text(story.get("story_title", "")) or short_text(excerpt, 70),
        "highlight_phrases": [_short_phrase(excerpt)],
        "phrases": [_short_phrase(excerpt)],
        "headline": _short_phrase(excerpt),
        "accent_words": meaningful_words(excerpt)[:2],
        "composition": "editorial_center",
        "motion_style": "word_reveal",
        "emphasis_words": meaningful_words(excerpt)[:4],
        "evidence_record_keys": [first_key] if use_source else hinted_keys,
        "evidence_truth_ids": dedupe(
            [
                clean_text(truth_id)
                for unit in covered_units
                for truth_id in (unit.get("support_truth_ids") or [])
                if clean_text(truth_id)
            ]
        ),
        "evidence_text": excerpt,
        "grounding_basis": "selected_record" if use_source else "script_beat",
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
        "evidence_truth_ids": list(draft.get("evidence_truth_ids") or []),
        "source_urls": [source_url] if source_url else [],
        "semantic_grounding": _semantic_grounding_for_scene(
            draft=draft,
            render_kind=render_kind,
            story_id=story_id,
            source_record_key=source_record_key,
            url=source_url,
            payload=payload,
            source_index=source_index,
        ),
        "reason": "Safe exact-narration fallback for an uncovered planner range.",
    }


def _scene_from_candidate_slice(candidate: dict[str, Any], unit_slice: dict[str, Any], script_units: list[dict[str, Any]]) -> dict[str, Any]:
    start_seconds = safe_float(unit_slice.get("start_seconds"), 0.0)
    end_seconds = safe_float(unit_slice.get("end_seconds"), start_seconds)
    payload = dict(candidate.get("payload", {})) if isinstance(candidate.get("payload"), dict) else {}
    is_subscene = safe_int(unit_slice.get("semantic_subscene_count"), 1) > 1 or safe_int(unit_slice.get("slice_count"), 1) > 1
    planned_excerpt = clean_text(candidate.get("script_excerpt", ""))
    active_excerpt = planned_excerpt if is_subscene and planned_excerpt else _script_excerpt_for_time_slice(script_units, unit_slice)
    beats = _visual_beats_for_slice(
        unit_slice,
        script_units,
        start_seconds,
        text_override=active_excerpt if is_subscene else "",
    )
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
        "script_excerpt": active_excerpt,
        "visual_intent": clean_text(candidate.get("visual_intent", "")),
        "payload": payload,
        "source_record_keys": candidate.get("source_record_keys", []),
        "evidence_truth_ids": candidate.get("evidence_truth_ids", []),
        "source_urls": candidate.get("source_urls", []),
        "semantic_grounding": candidate.get("semantic_grounding", {}),
        "reason": clean_text(candidate.get("reason", "")),
    }


def _script_excerpt_for_time_slice(
    script_units: list[dict[str, Any]],
    unit_slice: dict[str, Any],
) -> str:
    start_unit = safe_int(unit_slice.get("start_unit_order"), 1)
    end_unit = safe_int(unit_slice.get("end_unit_order"), start_unit)
    full_excerpt = _script_excerpt(script_units, start_unit, end_unit)
    slice_count = safe_int(unit_slice.get("slice_count"), 1)
    slice_index = safe_int(unit_slice.get("slice_index"), 1)
    if slice_count <= 1 or start_unit != end_unit:
        return full_excerpt
    return _text_partition(full_excerpt, slice_count)[min(max(slice_index - 1, 0), slice_count - 1)]


def _text_partition(text: str, count: int) -> list[str]:
    count = max(1, count)
    words = clean_text(text).split()
    if not words:
        return [""] * count
    partitions: list[str] = []
    for index in range(count):
        start = round(index * len(words) / count)
        end = round((index + 1) * len(words) / count)
        partitions.append(" ".join(words[start:end]).strip())
    return partitions


def _finalize_scene_order(scenes: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = sorted(scenes, key=lambda scene: (safe_float(scene.get("start_seconds"), 0.0), safe_int(scene.get("script_unit_start"), 0)))
    hard_max_scene_seconds = _effective_hard_max_scene_seconds(policy)
    _close_timeline_gaps(ordered, hard_max_scene_seconds)
    ordered = _compact_scene_timeline(ordered, policy)
    _close_timeline_gaps(ordered, hard_max_scene_seconds)
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
    max_scene_seconds = safe_float(policy.get("max_scene_seconds"), 14.0)
    compacted = list(scenes)

    def merge_at(index: int) -> None:
        merged = _merge_adjacent_scenes(compacted[index], compacted[index + 1])
        compacted[index : index + 2] = [merged]

    if policy.get("compact_per_chunk_scenes", True):
        changed = True
        while changed:
            changed = False
            for index in range(len(compacted) - 1):
                if _should_merge_semantic_neighbors(compacted[index], compacted[index + 1], policy):
                    merge_at(index)
                    changed = True
                    break
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
    if first_kind != second_kind or first_kind not in MERGEABLE_TEXT_RENDER_KINDS:
        return False
    start = safe_float(first.get("start_seconds"), 0.0)
    end = safe_float(second.get("end_seconds"), start)
    combined = max(0.0, end - start)
    max_seconds = safe_float(policy.get("max_scene_seconds"), 14.0)
    target_seconds = min(max_seconds, max(safe_float(policy.get("semantic_min_scene_seconds"), 5.0), safe_float(policy.get("semantic_target_scene_seconds"), 9.0)))
    if combined > target_seconds + 0.01:
        return False
    return True


def _is_story_title_interstitial(scene: dict[str, Any]) -> bool:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    return (
        clean_text(scene.get("render_kind", "")) in {"story_transition_scene", "transition_stinger_scene"}
        and clean_text(payload.get("voice_behavior", "")) == "continue"
    )


def _scene_headline(scene: dict[str, Any]) -> str:
    payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
    for key in ("headline", "overlay_headline", "companion_text", "transition_label"):
        value = clean_text(payload.get(key, "")).lower()
        if value:
            return value
    return ""


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
        "semantic_grounding": {
            "status": "grounded",
            "basis": "script_beat",
            "evidence_record_keys": dedupe([*first.get("source_record_keys", []), *second.get("source_record_keys", [])]),
            "evidence_text": script_excerpt,
            "errors": [],
        },
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
        "simple_explainer_scene": 21,
        "ranked_list_scene": 21,
        "bullet_build_scene": 22,
        "editorial_text_scene": 23,
        "kinetic_type_scene": 23,
        "recap_sequence_scene": 24,
        "story_transition_scene": 25,
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
        current_units = [
            safe_int(unit_order, 0)
            for unit_order in current.get("covered_unit_orders", [])
            if safe_int(unit_order, 0) > 0
        ]
        next_units = [
            safe_int(unit_order, 0)
            for unit_order in next_scene.get("covered_unit_orders", [])
            if safe_int(unit_order, 0) > 0
        ]
        if current_units and next_units and min(next_units) > max(current_units) + 1:
            # A missing script-unit range is a planning failure, not dead air
            # that may be hidden by stretching the following scene backward.
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
                "beat_function": unit.get("beat_function", ""),
                "support_truth_ids": unit.get("support_truth_ids", []),
                "creative_device": unit.get("creative_device", "none"),
                "visual_goal": unit.get("visual_goal", ""),
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
    del counts, story_id, source_index
    allowed = set(policy["allowed_render_kinds"])
    render_kind = clean_text(draft.get("render_kind", ""))
    if render_kind in OLD_CARD_RENDER_KINDS:
        return render_kind
    if render_kind not in allowed:
        return render_kind
    return render_kind


def _payload_for_scene(
    *,
    draft: dict[str, Any],
    render_kind: str,
    story_id: str,
    source_record_key: str,
    url: str,
    script_excerpt: str,
    source_index: dict[str, Any],
    asset_catalog_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset_id = clean_text(draft.get("asset_id"))
    catalog_asset = (
        (asset_catalog_index or {}).get("assets_by_id", {}).get(asset_id)
        if asset_id
        else None
    )
    if render_kind in {"context_image_scene", "broll_video_scene"}:
        search_queries = normalize_text_list(draft.get("search_queries"))
        if not search_queries:
            search_queries = dedupe(
                [
                    clean_text(draft.get("primary_entity", "")),
                    clean_text(draft.get("headline", "")),
                    short_text(script_excerpt, 120),
                ]
            )
        return {
            "asset_id": asset_id,
            "search_queries": search_queries[:3],
            "must_show": normalize_text_list(draft.get("must_show"))[:5],
            "must_avoid": normalize_text_list(draft.get("must_avoid"))[:5],
            "annotations": normalize_text_list(
                draft.get("annotations") or draft.get("callouts")
            )[:3],
            "shot_style": short_text(clean_text(draft.get("shot_style")) or "wide", 48),
            "overlay_headline": short_text(
                clean_text(
                    draft.get("overlay_headline")
                    or draft.get("media_overlay_headline")
                ),
                54,
            ),
            "motion_style": clean_text(
                draft.get("motion_style") or draft.get("media_motion_style")
            )
            or ("editorial_crop" if render_kind == "broll_video_scene" else "slow_push"),
            "show_overlay": bool(
                draft.get("show_overlay", draft.get("show_media_overlay", False))
            ),
        }
    if render_kind == "source_article_scene":
        record = source_index["records_by_key"].get(source_record_key, {}) if source_record_key else {}
        target_text = _truth_bound_screenshot_target(
            draft=draft,
            record=record,
            source_record_key=source_record_key,
            source_index=source_index,
            requested_text=clean_text(draft.get("target_text", "")) or script_excerpt,
        )
        return {
            "asset_id": asset_id,
            "url": url,
            "source_record_key": source_record_key,
            "target_text": short_text(target_text or script_excerpt, 260),
            "highlight_phrases": normalize_text_list(draft.get("highlight_phrases"))[:4],
            "crop_strategy": clean_text(draft.get("crop_strategy", "")) or "target_text_focus",
            "overlay_headline": short_text(clean_text(draft.get("overlay_headline", "")) or script_excerpt, 70),
            "motion_style": clean_text(draft.get("source_motion_style", "")) or "slow_push",
        }
    if render_kind == "quote_or_claim_highlight_scene":
        record = source_index["records_by_key"].get(source_record_key, {}) if source_record_key else {}
        claim_text = clean_text(draft.get("claim_text", "")) or clean_text(draft.get("target_text", "")) or _short_phrase(script_excerpt)
        supporting_text = _truth_bound_screenshot_target(
            draft=draft,
            record=record,
            source_record_key=source_record_key,
            source_index=source_index,
            requested_text=clean_text(draft.get("supporting_text", "")) or claim_text or script_excerpt,
        )
        return {
            "asset_id": asset_id,
            "url": url,
            "source_record_key": source_record_key,
            "target_text": short_text(supporting_text, 260),
            "claim_text": short_text(claim_text, 90),
            "supporting_text": short_text(supporting_text, 260),
            "highlight_phrases": dedupe([*normalize_text_list(draft.get("highlight_phrases")), claim_text])[:4],
            "overlay_headline": short_text(clean_text(draft.get("overlay_headline", "")) or claim_text or script_excerpt, 70),
            "motion_style": clean_text(draft.get("source_motion_style", "")) or "highlight_scan",
        }
    if render_kind == "logo_reveal_scene":
        primary_entity = clean_text(draft.get("primary_entity", "")) or _primary_entity_for_story(story_id, source_index)
        entities = dedupe([primary_entity, *normalize_text_list(draft.get("entities"))])[:4]
        return {
            "asset_id": asset_id,
            "entities": entities,
            "primary_entity": primary_entity,
            "logo_strategy": clean_text(draft.get("logo_strategy", "")) or "simple_icons_then_favicon_then_text",
            "favicon_domain_url": url,
            "companion_text": clean_text(draft.get("companion_text", "")) or _short_phrase(script_excerpt),
            "motion_style": clean_text(draft.get("logo_motion_style", "")) or "pop_reveal",
            "catalog_source": clean_text((catalog_asset or {}).get("source_name")),
        }
    if render_kind == "editorial_text_scene":
        headline = clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt)
        return {
            "eyebrow": short_text(clean_text(draft.get("eyebrow", "")), 28),
            "headline": short_text(headline, 92),
            "accent_words": normalize_text_list(draft.get("accent_words"))[:5],
            "supporting_text": short_text(clean_text(draft.get("supporting_text", "")), 110),
            "composition": clean_text(draft.get("composition", "")) or "editorial_center",
            "motion_style": clean_text(draft.get("motion_style", "")) or "word_reveal",
        }
    if render_kind == "simple_explainer_scene":
        raw_items = draft.get("items") if isinstance(draft.get("items"), list) else draft.get("steps", [])
        items: list[dict[str, str]] = []
        for item in raw_items:
            if isinstance(item, dict):
                label = clean_text(item.get("label", "")) or clean_text(item.get("name", ""))
                detail = clean_text(item.get("detail", "")) or clean_text(item.get("description", ""))
            else:
                label = clean_text(item)
                detail = ""
            if label:
                items.append({"label": short_text(label, 34), "detail": short_text(detail, 56)})
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 76),
            "items": items[:4],
            "connector_label": short_text(clean_text(draft.get("connector_label", "")), 28),
            "focus_item_label": short_text(clean_text(draft.get("focus_item_label", "")), 34),
            "orientation": clean_text(draft.get("orientation", "")) or "horizontal",
            "motion_style": clean_text(draft.get("motion_style", "")) or "sequential_focus",
        }
    if render_kind == "story_transition_scene":
        headline = clean_text(draft.get("headline", "")) or clean_text(draft.get("transition_label", "")) or _short_phrase(script_excerpt)
        return {
            "story_number": short_text(clean_text(draft.get("story_number", "")), 16),
            "eyebrow": short_text(clean_text(draft.get("eyebrow", "")), 28),
            "headline": short_text(headline, 120),
            "subtitle": short_text(clean_text(draft.get("subtitle", "")), 80),
            "accent_words": normalize_text_list(draft.get("accent_words"))[:5],
            "motion_style": clean_text(draft.get("motion_style", "")) or "editorial_wipe",
            "voice_behavior": clean_text(draft.get("voice_behavior", "")) or "continue",
        }
    if render_kind == "entity_compare_scene":
        primary_entity = clean_text(draft.get("primary_entity", "")) or _primary_entity_for_story(story_id, source_index)
        entity_items = normalize_text_list(draft.get("entities"))
        entities = dedupe([primary_entity, *entity_items])[:4]
        notes = [short_text(item, 52) for item in normalize_text_list(draft.get("entity_notes"))]
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or clean_text(draft.get("companion_text", "")) or _short_phrase(script_excerpt), 72),
            "entities": entities,
            "comparison_axis": short_text(clean_text(draft.get("comparison_axis", "")), 52),
            "entity_notes": notes[: len(entities)],
            "motion_style": clean_text(draft.get("comparison_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "versus",
        }
    if render_kind == "data_counter_scene":
        metrics = _metrics_from_draft(draft, script_excerpt)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "metrics": metrics[:3],
            "emphasis_label": short_text(clean_text(draft.get("emphasis_label", "")), 44),
            "motion_style": clean_text(draft.get("data_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "count_up",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "trend_line_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "trend_direction": clean_text(draft.get("trend_direction", "")),
            "y_axis_label": short_text(clean_text(draft.get("y_axis_label", "")), 32),
            "x_axis_label": short_text(clean_text(draft.get("x_axis_label", "")), 32),
            "annotations": _annotations_from_draft(draft, script_excerpt),
            "motion_style": clean_text(draft.get("trend_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "draw_line",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "bar_chart_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "bars": _bars_from_draft(draft, script_excerpt)[:5],
            "unit": short_text(clean_text(draft.get("unit", "")), 12),
            "emphasis_label": short_text(clean_text(draft.get("emphasis_label", "")), 44),
            "motion_style": clean_text(draft.get("chart_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "grow_bars",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "bar_race_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "items": _race_items_from_draft(draft, script_excerpt)[:5],
            "unit": short_text(clean_text(draft.get("unit", "")), 12),
            "leader_label": short_text(clean_text(draft.get("leader_label", "")), 48),
            "motion_style": clean_text(draft.get("race_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "rank_shift",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "ranked_list_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "items": _ranked_items_from_draft(draft, script_excerpt)[:5],
            "emphasis_label": short_text(clean_text(draft.get("emphasis_label", "")), 44),
            "motion_style": clean_text(draft.get("ranked_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "staggered_rank",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "benchmark_delta_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "benchmarks": _benchmarks_from_draft(draft, script_excerpt)[:3],
            "winner_label": short_text(clean_text(draft.get("winner_label", "")), 48),
            "motion_style": clean_text(draft.get("benchmark_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "delta_snap",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "ecosystem_map_scene":
        nodes = _nodes_from_draft(draft)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "nodes": nodes[:6],
            "edges": _edges_from_draft(draft, nodes),
            "focus_entity": short_text(clean_text(draft.get("focus_entity", "")) or clean_text(draft.get("primary_entity", "")) or (nodes[0]["label"] if nodes else ""), 36),
            "motion_style": clean_text(draft.get("map_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "pulse_connections",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "architecture_flow_scene":
        steps = _flow_steps_from_draft(draft, script_excerpt)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "steps": steps[:6],
            "flow_direction": clean_text(draft.get("flow_direction", "")) or "left_to_right",
            "active_step_label": short_text(clean_text(draft.get("active_step_label", "")), 44),
            "motion_style": clean_text(draft.get("flow_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "packet_flow",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "process_zoom_scene":
        steps = _flow_steps_from_draft(draft, script_excerpt)
        focus = clean_text(draft.get("focus_step_label", "")) or clean_text(draft.get("active_step_label", "")) or _focus_step_from_steps(steps)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "steps": steps[:6],
            "focus_step_label": short_text(focus, 44),
            "zoom_note": short_text(clean_text(draft.get("zoom_note", "")) or clean_text(draft.get("metric_context", "")), 86),
            "motion_style": clean_text(draft.get("zoom_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "focus_zoom",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "browser_walkthrough_scene":
        return {
            "asset_id": asset_id,
            "headline": short_text(clean_text(draft.get("headline", "")) or clean_text(draft.get("overlay_headline", "")) or _short_phrase(script_excerpt), 64),
            "url": clean_text(url),
            "source_record_key": source_record_key,
            "walkthrough_steps": _walkthrough_steps_from_draft(draft, script_excerpt)[:5],
            "focus_text": short_text(clean_text(draft.get("focus_text", "")) or clean_text(draft.get("target_text", "")) or _short_phrase(script_excerpt), 76),
            "motion_style": clean_text(draft.get("browser_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "guided_scroll",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "decision_tree_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "root_label": short_text(clean_text(draft.get("root_label", "")), 42),
            "branches": _decision_branches_from_draft(draft, script_excerpt)[:5],
            "selected_path_label": short_text(clean_text(draft.get("selected_path_label", "")), 48),
            "motion_style": clean_text(draft.get("decision_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "branch_glow",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "capability_matrix_scene":
        columns = _matrix_columns_from_draft(draft)[:5]
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "columns": columns,
            "rows": _matrix_rows_from_draft(draft, script_excerpt, columns)[:5],
            "highlight_cell": short_text(clean_text(draft.get("highlight_cell", "")), 40),
            "motion_style": clean_text(draft.get("matrix_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "cell_scan",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "timeline_zoom_scene":
        events = _timeline_events_from_draft(draft, script_excerpt)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "events": events[:5],
            "focus_event_label": short_text(clean_text(draft.get("focus_event_label", "")), 44),
            "zoom_note": short_text(clean_text(draft.get("zoom_note", "")), 86),
            "motion_style": clean_text(draft.get("timeline_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "event_zoom",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "document_stack_scene":
        documents = _documents_from_draft(draft, script_excerpt)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "documents": documents[:5],
            "focus_document_label": short_text(clean_text(draft.get("focus_document_label", "")), 46),
            "motion_style": clean_text(draft.get("document_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "parallax_stack",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "signal_radar_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "signals": _signals_from_draft(draft, script_excerpt)[:7],
            "scan_label": short_text(clean_text(draft.get("scan_label", "")), 44),
            "motion_style": clean_text(draft.get("radar_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "radar_sweep",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "interface_transform_scene":
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "before": _interface_panel_from_draft(draft.get("before"), "Before", script_excerpt),
            "after": _interface_panel_from_draft(draft.get("after"), "After", script_excerpt, flow=True),
            "transformation_label": short_text(clean_text(draft.get("transformation_label", "")), 48),
            "motion_style": clean_text(draft.get("transform_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "panel_morph",
            "background_motif": clean_text(draft.get("background_motif", "")) or "device_glow",
        }
    if render_kind == "transition_stinger_scene":
        label = clean_text(draft.get("transition_label", "")) or clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt)
        subtitle = clean_text(draft.get("transition_subtitle", "")) or clean_text(draft.get("companion_text", ""))
        return {
            "transition_label": short_text(label, 48),
            "subtitle": short_text(subtitle, 60),
            "motion_style": clean_text(draft.get("stinger_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "signal_wipe",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    if render_kind == "bullet_build_scene":
        points = [short_text(item, 68) for item in normalize_text_list(draft.get("points"))]
        if not points:
            points = _points_from_text(script_excerpt, max_points=4, max_chars=64)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "points": points[:4],
            "emphasis_words": dedupe([*normalize_text_list(draft.get("emphasis_words")), *meaningful_words(script_excerpt)])[:6],
            "build_style": clean_text(draft.get("build_style", "")) or "numbered_build",
            "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
        }
    if render_kind == "recap_sequence_scene":
        items = [short_text(item, 62) for item in normalize_text_list(draft.get("recap_items"))]
        if not items:
            items = _points_from_text(script_excerpt, max_points=5, max_chars=58)
        return {
            "headline": short_text(clean_text(draft.get("headline", "")) or _short_phrase(script_excerpt), 64),
            "recap_items": items[:6],
            "final_takeaway": short_text(clean_text(draft.get("final_takeaway", "")) or _short_phrase(script_excerpt), 84),
            "motion_style": clean_text(draft.get("recap_motion_style", "")) or clean_text(draft.get("motion_style", "")) or "story_rhythm",
            "background_motif": clean_text(draft.get("background_motif", "")) or "abstract_ai",
        }
    phrases = normalize_text_list(draft.get("phrases"))
    if not phrases:
        phrases = [phrase for phrase in [_short_phrase(script_excerpt)] if phrase]
    return {
        "phrases": [short_text(phrase, 54) for phrase in phrases[:3]],
        "emphasis_words": normalize_text_list(draft.get("emphasis_words"))[:6],
        "animation_style": clean_text(draft.get("animation_style", "")) or "typewriter",
        "background_motif": clean_text(draft.get("background_motif", "")) or "newsroom_grid",
    }


def _payload_with_recipe(
    payload: dict[str, Any],
    draft: dict[str, Any],
) -> dict[str, Any]:
    recipe_id = clean_text(draft.get("recipe_id"))
    if not recipe_id:
        return payload
    return {**payload, "recipe_id": recipe_id}


def _build_asset_manifest(scene_timeline: list[dict[str, Any]]) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    for scene in scene_timeline:
        render_kind = scene["render_kind"]
        asset_type = {
            "source_article_scene": "source_screenshot",
            "quote_or_claim_highlight_scene": "source_screenshot",
            "browser_walkthrough_scene": "source_screenshot",
            "context_image_scene": "context_image",
            "broll_video_scene": "broll_video",
            "logo_reveal_scene": "logo_asset",
            "editorial_text_scene": "none",
            "simple_explainer_scene": "none",
            "story_transition_scene": "none",
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


def _script_story_truth_indexes(request: VisualPlannerRequest) -> list[dict[str, Any]]:
    script_generation = request.input.script_generation
    if script_generation is None:
        return []
    indexes = script_generation.data.script_package.get("story_truth_indexes", [])
    return [item for item in indexes if isinstance(item, dict)]


def _build_source_index(
    stories: list[dict[str, Any]],
    *,
    story_truth_indexes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    records_by_key: dict[str, dict[str, Any]] = {}
    record_keys_by_story: dict[str, list[str]] = {}
    source_urls: set[str] = set()
    story_identity_by_id: dict[str, dict[str, Any]] = {}
    truth_items_by_story: dict[str, list[dict[str, Any]]] = {}
    truth_items_by_id: dict[str, dict[str, Any]] = {}
    truth_items_by_record: dict[str, list[dict[str, Any]]] = {}

    for index in story_truth_indexes or []:
        indexed_story_id = clean_text(index.get("story_id"))
        if not indexed_story_id:
            continue
        items = [item for item in index.get("items", []) if isinstance(item, dict)]
        truth_items_by_story[indexed_story_id] = items
        for item in items:
            truth_id = clean_text(item.get("truth_id"))
            if truth_id:
                indexed_item = {**item, "story_id": indexed_story_id}
                truth_items_by_id[truth_id] = indexed_item
                record_key = clean_text(item.get("record_key"))
                if record_key:
                    truth_items_by_record.setdefault(record_key, []).append(indexed_item)

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
                "full_record": dict(record),
                "record_key": key,
                "story_id": story_id,
                "url": url,
                "title": clean_text(record.get("title", "")),
                "source_name": clean_text(record.get("source_name") or record.get("source", "")),
                "source_group": clean_text(record.get("source_group", "")),
                "published_at": clean_text(record.get("published_at", "")),
                "summary_or_description": clean_text(record.get("summary") or record.get("description") or ""),
                "content": clean_text(record.get("content") or record.get("text") or ""),
                "screenshot_target_candidates": dedupe(
                    [
                        *[
                            clean_text(item.get("source_text"))
                            for item in truth_items_by_record.get(key, [])
                            if clean_text(item.get("source_field")) in {"content", "title"}
                            and clean_text(item.get("source_text"))
                        ],
                        *screenshot_target_candidates(record),
                    ]
                ),
                "truth_screenshot_targets": [
                    {
                        "truth_id": clean_text(item.get("truth_id")),
                        "source_text": clean_text(item.get("source_text")),
                        "source_field": clean_text(item.get("source_field")),
                        "source_order": safe_int(item.get("source_order"), 0),
                    }
                    for item in truth_items_by_record.get(key, [])
                    if clean_text(item.get("source_text"))
                ],
            }
            record_keys_by_story[story_id].append(key)
            if url:
                source_urls.add(url)
    return {
        "records_by_key": records_by_key,
        "record_keys_by_story": record_keys_by_story,
        "source_urls": source_urls,
        "story_identity_by_id": story_identity_by_id,
        "truth_items_by_story": truth_items_by_story,
        "truth_items_by_id": truth_items_by_id,
        "truth_items_by_record": truth_items_by_record,
    }


def _story_for_prompt(
    story: dict[str, Any],
    source_index: dict[str, Any],
    config: dict[str, Any],
    *,
    script_units: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    story_id = clean_text(story.get("story_id", ""))
    source_policy = config["source_policy"]
    all_keys = source_index["record_keys_by_story"].get(story_id, [])

    referenced_truth_ids = {
        clean_text(truth_id)
        for unit in (script_units or [])
        if isinstance(unit, dict)
        for truth_id in (unit.get("support_truth_ids") or [])
        if clean_text(truth_id)
    }
    records: list[dict[str, Any]] = []
    for key in all_keys:
        record = source_index["records_by_key"].get(key, {})
        referenced_by_beats = [
            {
                "unit_id": unit.get("unit_id", ""),
                "beat_id": unit.get("beat_id", ""),
                "text": short_text(unit.get("text", ""), 260),
            }
            for unit in (script_units or [])
            if isinstance(unit, dict) and key in (unit.get("source_record_keys") or [])
        ]
        full_record = (
            record.get("full_record")
            if isinstance(record.get("full_record"), dict)
            else {}
        )
        records.append(
            {
                **full_record,
                "record_key": key,
                "title": record.get("title", ""),
                "source_name": record.get("source_name", ""),
                "source_group": record.get("source_group", ""),
                "url": record.get("url", ""),
                "published_at": record.get("published_at", ""),
                "summary_or_description": record.get("summary_or_description", ""),
                "content": record.get("content", ""),
                "screenshot_target_candidates": list(record.get("screenshot_target_candidates", [])),
                "truth_screenshot_targets": [
                    target
                    for target in record.get("truth_screenshot_targets", [])
                    if clean_text(target.get("truth_id")) in referenced_truth_ids
                ],
                "referenced_by_beats": referenced_by_beats,
            }
        )
    serialized_context_chars = len(json.dumps(records, ensure_ascii=False, default=str))
    max_context_chars = int(source_policy["max_story_context_chars"])
    if serialized_context_chars > max_context_chars:
        raise ValueError(
            f"story {story_id} full visual-planning context is {serialized_context_chars} chars, "
            f"above source_policy.max_story_context_chars={max_context_chars}; "
            "use a model with sufficient context or raise the explicit resource limit"
        )
    return {
        "story_id": story_id,
        "rank": story.get("rank"),
        "priority_bucket": clean_text(story.get("priority_bucket", "")),
        "story_title": clean_text(story.get("story_title", "")),
        "story_identity": story.get("story_identity", {}),
        "video_segment": story.get("video_segment", {}),
        "source_groups": story.get("source_groups", []),
        "numeric_truth_items": [
            {
                "truth_id": clean_text(item.get("truth_id")),
                "record_key": clean_text(item.get("record_key")),
                "value_text": clean_text(item.get("value_text")),
                "source_text": short_text(clean_text(item.get("source_text")), 320),
            }
            for item in source_index.get("truth_items_by_story", {}).get(story_id, [])
            if clean_text(item.get("truth_type")) == "metric"
            and clean_text(item.get("value_text"))
            and clean_text(item.get("truth_id")) in referenced_truth_ids
        ],
        "records": records,
        "context_telemetry": {
            "context_mode": "complete_selected_story_records",
            "record_count": len(records),
            "record_keys": list(all_keys),
            "serialized_record_chars": serialized_context_chars,
            "records_truncated": False,
        },
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


def _visual_capabilities_for_prompt(
    config: dict[str, Any],
    *,
    include_system_managed: bool = True,
    allowed_render_kinds: list[str] | None = None,
) -> dict[str, Any]:
    allowed = set(
        allowed_render_kinds
        if allowed_render_kinds is not None
        else config["scene_policy"]["allowed_render_kinds"]
    )
    if not include_system_managed:
        allowed.discard("story_transition_scene")
    catalog_required = {
        clean_text(kind)
        for kind in config.get("asset_availability_policy", {}).get(
            "catalog_asset_required_render_kinds", []
        )
        if clean_text(kind)
    }
    capabilities = config.get("visual_capabilities", {})
    recipe_policy = config.get("recipe_policy", {})
    recipes_enabled = bool(recipe_policy.get("enabled", True))
    allowed_recipe_ids = list(recipe_policy.get("allowed_recipe_ids") or RECIPE_REGISTRY)
    required_backends = list(
        recipe_policy.get("required_backend_support") or ["remotion", "hyperframes"]
    )
    prompt_capabilities: dict[str, Any] = {}
    for key, value in capabilities.items():
        if key not in allowed or not isinstance(value, dict):
            continue
        capability = dict(value)
        structural_contract = prompt_payload_contract(key)
        recipes = (
            recipe_specs_for_prompt(
                key,
                allowed_recipe_ids=allowed_recipe_ids,
                required_backends=required_backends,
            )
            if recipes_enabled
            else []
        )
        if recipes_enabled and bool(recipe_policy.get("require_recipe_id", True)) and not recipes:
            continue
        if recipes:
            capability["available_recipes"] = recipes
            if bool(recipe_policy.get("require_recipe_id", True)):
                required = dict(structural_contract.get("required") or {})
                required["recipe_id"] = "one exact available_recipes[].recipe_id value"
                structural_contract["required"] = required
            else:
                optional = dict(structural_contract.get("optional") or {})
                optional["recipe_id"] = "one exact available_recipes[].recipe_id value"
                structural_contract["optional"] = optional
        if key in catalog_required and structural_contract:
            required = dict(structural_contract.get("required") or {})
            optional = dict(structural_contract.get("optional") or {})
            required["asset_id"] = (
                "exact available story-owned catalog asset ID compatible with this render kind"
            )
            optional.pop("asset_id", None)
            optional.pop("search_queries", None)
            optional.pop("must_show", None)
            optional.pop("must_avoid", None)
            structural_contract["required"] = required
            if optional:
                structural_contract["optional"] = optional
            else:
                structural_contract.pop("optional", None)
        configured_contract = capability.get("payload_field_contract")
        if isinstance(configured_contract, dict):
            capability["configured_payload_notes"] = configured_contract
        if structural_contract:
            capability["payload_field_contract"] = structural_contract
        capability["common_scene_field_contract"] = {
            "payload_json": (
                "required non-empty string containing one valid JSON object that follows "
                "payload_field_contract exactly"
            ),
            "evidence_text": (
                "required concise explanation copied or faithfully condensed from the active "
                "script beat"
                if key in EVIDENCE_BOUND_RENDER_KINDS
                else "may be empty when the selected asset and record keys provide grounding"
            ),
            "evidence_record_keys": "list[str] using only record keys owned by this story",
            "evidence_truth_ids": (
                "list[str] using exact eligible truth IDs; use [] when no factual display requires one"
            ),
        }
        prompt_capabilities[key] = capability
    return prompt_capabilities


def _scene_recipe_policy_errors(
    scene: dict[str, Any],
    *,
    config: dict[str, Any],
) -> list[str]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    recipe_id = clean_text(scene.get("recipe_id") or payload.get("recipe_id"))
    if not recipe_id:
        policy = config.get("recipe_policy", {})
        if bool(policy.get("enabled", True)) and bool(policy.get("require_recipe_id", True)):
            return ["payload.recipe_id is required by config.recipe_policy"]
        return []
    policy = config.get("recipe_policy", {})
    if not bool(policy.get("enabled", True)):
        return [f"recipe {recipe_id!r} is disabled by config.recipe_policy"]
    allowed = set(policy.get("allowed_recipe_ids") or RECIPE_REGISTRY)
    if recipe_id not in allowed:
        return [f"recipe {recipe_id!r} is not enabled by config.recipe_policy"]
    recipe = RECIPE_REGISTRY.get(recipe_id, {})
    required = set(policy.get("required_backend_support") or [])
    supported = set(recipe.get("supported_backends") or [])
    missing = sorted(required - supported)
    if missing:
        return [f"recipe {recipe_id!r} does not support required backends {missing}"]
    return []


def _canonical_screenshot_target(record: dict[str, Any], requested_text: str) -> str:
    candidates = dedupe(
        [
            clean_text(candidate)
            for candidate in record.get("screenshot_target_candidates", [])
            if clean_text(candidate)
        ]
    )
    if not candidates:
        return clean_text(record.get("title", ""))

    requested = clean_text(requested_text)
    exact = next(
        (candidate for candidate in candidates if candidate.casefold() == requested.casefold()),
        "",
    )
    return exact or candidates[0]


def _truth_bound_screenshot_target(
    *,
    draft: dict[str, Any],
    record: dict[str, Any],
    source_record_key: str,
    source_index: dict[str, Any],
    requested_text: str,
) -> str:
    truth_items = []
    for truth_id in draft.get("evidence_truth_ids", []):
        item = source_index.get("truth_items_by_id", {}).get(clean_text(truth_id), {})
        if (
            clean_text(item.get("record_key")) == source_record_key
            and clean_text(item.get("source_text"))
            and clean_text(item.get("source_field")) in {"content", "title"}
        ):
            truth_items.append(item)
    if truth_items:
        requested = clean_text(requested_text).casefold()
        exact = next(
            (
                clean_text(item.get("source_text"))
                for item in truth_items
                if clean_text(item.get("source_text")).casefold() == requested
            ),
            "",
        )
        if exact:
            return exact
        return clean_text(truth_items[0].get("source_text"))
    return _canonical_screenshot_target(record, requested_text)


def _source_for_scene(
    draft: dict[str, Any],
    story_id: str,
    render_kind: str,
    source_index: dict[str, Any],
) -> tuple[str, str]:
    if render_kind not in SOURCE_BOUND_RENDER_KINDS | {"logo_reveal_scene"}:
        return "", ""
    evidence_keys = [clean_text(key) for key in draft.get("evidence_record_keys", []) if clean_text(key)]
    requested_key = clean_text(draft.get("source_record_key", "")) or (evidence_keys[0] if evidence_keys else "")
    requested_url = clean_text(draft.get("url", ""))
    story_keys = source_index["record_keys_by_story"].get(story_id, [])
    if requested_key in story_keys:
        record = source_index["records_by_key"].get(requested_key, {})
        canonical_url = clean_text(record.get("url", ""))
        if requested_url and requested_url != canonical_url:
            return "", ""
        if canonical_url.startswith(("http://", "https://")):
            return requested_key, canonical_url
    return "", ""


def _semantic_grounding_for_scene(
    *,
    draft: dict[str, Any],
    render_kind: str,
    story_id: str,
    source_record_key: str,
    url: str,
    payload: dict[str, Any],
    source_index: dict[str, Any],
) -> dict[str, Any]:
    requested_keys = dedupe(
        [
            *[clean_text(key) for key in draft.get("evidence_record_keys", []) if clean_text(key)],
            source_record_key,
        ]
    )
    story_keys = set(source_index.get("record_keys_by_story", {}).get(story_id, []))
    valid_keys = [key for key in requested_keys if key in story_keys]
    invalid_keys = [key for key in requested_keys if key not in story_keys]
    requested_truth_ids = dedupe(
        [clean_text(value) for value in draft.get("evidence_truth_ids", []) if clean_text(value)]
    )
    truth_items_by_id = source_index.get("truth_items_by_id", {})
    valid_truth_items = [
        truth_items_by_id[truth_id]
        for truth_id in requested_truth_ids
        if truth_id in truth_items_by_id
        and clean_text(truth_items_by_id[truth_id].get("story_id")) == story_id
    ]
    invalid_truth_ids = [
        truth_id
        for truth_id in requested_truth_ids
        if truth_id not in truth_items_by_id
        or clean_text(truth_items_by_id[truth_id].get("story_id")) != story_id
    ]
    evidence_text = clean_text(draft.get("evidence_text", ""))
    basis = clean_text(draft.get("grounding_basis", "")) or "script_beat"
    errors: list[str] = []

    if invalid_keys:
        errors.append(f"evidence_record_keys are not owned by this story: {invalid_keys}")
    if invalid_truth_ids:
        errors.append(f"evidence_truth_ids are not owned by this story: {invalid_truth_ids}")
    if render_kind in SOURCE_BOUND_RENDER_KINDS:
        if not source_record_key:
            errors.append("source-bound scene requires an exact selected-story source_record_key")
        if not clean_text(url).startswith(("http://", "https://")):
            errors.append("source-bound scene requires the canonical selected-record URL")
    if render_kind in EVIDENCE_BOUND_RENDER_KINDS:
        if not valid_keys and basis != "script_beat":
            errors.append(
                "semantic graphic requires selected-story evidence_record_keys or grounding_basis='script_beat'"
            )
        if not evidence_text:
            errors.append("semantic graphic requires a concise evidence_text explanation")
    errors.extend(_payload_grounding_errors(render_kind, payload))
    return {
        "status": "grounded" if not errors else "invalid",
        "basis": basis,
        "evidence_record_keys": valid_keys,
        "evidence_truth_ids": [clean_text(item.get("truth_id")) for item in valid_truth_items],
        "evidence_text": short_text(evidence_text, 360),
        "errors": errors,
    }


def _payload_grounding_errors(render_kind: str, payload: dict[str, Any]) -> list[str]:
    return validate_scene_payload(render_kind, payload)


def _episode_style(episode_direction: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    style = dict(config["style"])
    style.update({
        "visual_language": clean_text(episode_direction.get("visual_language")) or config["style"]["visual_language"],
        "pacing_notes": clean_text(episode_direction.get("pacing_notes")) or config["style"]["motion_style"],
        "recurring_motifs": [clean_text(item) for item in episode_direction.get("recurring_motifs", []) if clean_text(item)],
        "typography_notes": clean_text(episode_direction.get("typography_notes")) or config["style"]["typography"],
        "color_notes": clean_text(episode_direction.get("color_notes")) or config["style"]["color_system"],
        "scene_mix_notes": clean_text(episode_direction.get("scene_mix_notes", "")),
        "transition_notes": clean_text(episode_direction.get("transition_notes", "")),
        "avoid_patterns": [clean_text(item) for item in episode_direction.get("avoid_patterns", []) if clean_text(item)],
    })
    return style


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
                "planning_failed": bool(draft.get("planning_failed")),
                "planning_failure_reason": clean_text(draft.get("planning_failure_reason", "")),
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
    target_max = safe_float(config["scene_policy"].get("max_scene_seconds"), 14.0)
    configured_hard_max = _hard_max_scene_seconds(config["scene_policy"])
    max_allowed = _effective_hard_max_scene_seconds(config["scene_policy"])
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
        "target_max_scene_seconds": target_max,
        "hard_max_scene_seconds": configured_hard_max,
        "hard_cap_tolerance_seconds": max(
            0.0,
            safe_float(config["scene_policy"].get("hard_cap_tolerance_seconds"), 0.0),
        ),
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
    planning_failures = _story_planner_failures(visual_scene_plan)
    if planning_failures:
        errors.append(
            "Story-level visual planning failed for "
            f"{len(planning_failures)} story section(s): {planning_failures[:8]}"
        )
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
    warnings.extend(_scene_cap_warnings(scenes, config["scene_policy"]))
    duplicate_visuals = _adjacent_duplicate_visual_payloads(scenes)
    if duplicate_visuals:
        warnings.append(
            "Adjacent scenes repeat the same render payload; visual-editor or human review is recommended: "
            f"{duplicate_visuals[:8]}"
        )
    for scene in scenes:
        grounding = scene.get("semantic_grounding") if isinstance(scene.get("semantic_grounding"), dict) else {}
        grounding_errors = grounding.get("errors") if isinstance(grounding.get("errors"), list) else []
        if clean_text(grounding.get("status", "")) != "grounded" or grounding_errors:
            errors.append(
                f"{scene.get('scene_id')} {scene.get('render_kind')} has invalid semantic grounding: "
                f"{grounding_errors or ['semantic_grounding.status is not grounded']}"
            )
    coverage = visual_scene_plan.get("coverage", {})
    if not planning_failures:
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
        if story_plan.get("planning_failed"):
            continue
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
    catalog_index = _asset_catalog_index(visual_scene_plan.get("asset_catalog", {}))
    catalog_required_kinds = {
        clean_text(kind)
        for kind in config.get("asset_availability_policy", {}).get(
            "catalog_asset_required_render_kinds", []
        )
        if clean_text(kind)
    }
    anchored_story_ids: set[str] = set()
    for scene in scenes:
        payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
        render_kind = clean_text(scene.get("render_kind"))
        if render_kind in catalog_required_kinds and not clean_text(payload.get("asset_id")):
            errors.append(
                f"{scene.get('scene_id')} {render_kind} requires an available catalog asset_id"
            )
            continue
        if not clean_text(payload.get("asset_id")):
            continue
        asset, asset_errors = _catalog_asset_for_scene(
            payload,
            story_id=clean_text(scene.get("story_id")),
            render_kind=render_kind,
            catalog_index=catalog_index,
        )
        errors.extend(f"{scene.get('scene_id')} {error}" for error in asset_errors)
        if asset:
            anchored_story_ids.add(clean_text(scene.get("story_id")))
    if config.get("require_real_anchor_per_story"):
        for story_plan in visual_scene_plan.get("story_plans", []):
            story_id = clean_text(story_plan.get("story_id"))
            if story_plan.get("planning_failed"):
                continue
            available = catalog_index.get("assets_by_story", {}).get(story_id, [])
            if available and story_id not in anchored_story_ids:
                message = f"{story_id} has no scene using a verified catalog asset_id"
                if clean_text(config.get("real_anchor_failure_mode", "warn")) == "fail":
                    errors.append(message)
                else:
                    warnings.append(message)

    media_scenes = [scene for scene in scenes if scene.get("render_kind") in {"context_image_scene", "broll_video_scene"}]
    for scene in media_scenes:
        payload = scene.get("payload", {}) if isinstance(scene.get("payload"), dict) else {}
        if clean_text(payload.get("asset_id")):
            continue
        queries = payload.get("search_queries") if isinstance(payload.get("search_queries"), list) else []
        if not any(clean_text(query) for query in queries):
            errors.append(f"{scene.get('scene_id')} {scene.get('render_kind')} is missing search_queries")
    kind_counts = Counter(scene.get("render_kind", "") for scene in scenes)
    max_same = safe_int(config["scene_policy"].get("max_consecutive_same_kind"), 2)
    repetitive_runs = _same_kind_runs_over_limit(scenes, max_same)
    if repetitive_runs:
        warnings.append(f"Visual rhythm has repeated scene-kind runs over limit: {repetitive_runs[:5]}")
    if scenes:
        mix_policy = config.get("visual_mix_policy", {})
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
        max_text_scene_ratio = safe_float(
            mix_policy.get("target_max_text_like_scene_ratio"),
            0.45,
        )
        max_text_duration_ratio = safe_float(
            mix_policy.get("target_max_text_like_duration_ratio"),
            0.45,
        )
        if text_like_count / len(scenes) > max_text_scene_ratio:
            warnings.append(f"Text-like visual mix is high: {text_like_count}/{len(scenes)} scenes.")
        if total_duration > 0 and text_like_duration / total_duration > max_text_duration_ratio:
            warnings.append(f"Text-like visual duration is high: {round(text_like_duration, 2)}/{round(total_duration, 2)} seconds.")
    return {"passed": not errors, "errors": errors, "warnings": warnings}


def _adjacent_duplicate_visual_payloads(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    duplicates: list[dict[str, Any]] = []
    for first, second in zip(scenes, scenes[1:]):
        if clean_text(first.get("story_id", "")) != clean_text(second.get("story_id", "")):
            continue
        if clean_text(first.get("render_kind", "")) != clean_text(second.get("render_kind", "")):
            continue
        if _is_timing_continuation_pair(first, second):
            continue
        if _render_payload_signature(first) != _render_payload_signature(second):
            continue
        duplicates.append(
            {
                "first_scene_id": clean_text(first.get("scene_id", "")),
                "second_scene_id": clean_text(second.get("scene_id", "")),
                "render_kind": clean_text(first.get("render_kind", "")),
            }
        )
    return duplicates


def _is_timing_continuation_pair(
    first: dict[str, Any],
    second: dict[str, Any],
) -> bool:
    first_payload = first.get("payload") if isinstance(first.get("payload"), dict) else {}
    second_payload = second.get("payload") if isinstance(second.get("payload"), dict) else {}
    group_id = clean_text(first_payload.get("continuation_group_id"))
    return bool(
        group_id
        and group_id == clean_text(second_payload.get("continuation_group_id"))
        and safe_int(first_payload.get("continuation_count"), 0) > 1
        and safe_int(first_payload.get("continuation_count"), 0)
        == safe_int(second_payload.get("continuation_count"), 0)
        and safe_int(first_payload.get("continuation_index"), 0)
        != safe_int(second_payload.get("continuation_index"), 0)
    )


def _render_payload_signature(scene: dict[str, Any]) -> str:
    payload = dict(scene.get("payload", {})) if isinstance(scene.get("payload"), dict) else {}
    return json.dumps(
        _semantic_visual_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _semantic_visual_payload(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = dict(payload)
    for field in (
        "beats",
        "beat_count",
        "covered_text",
        "timing_phase",
        "timing_phase_count",
        "motion_style",
        "source_motion_style",
        "animation_style",
        "crop_strategy",
        "background_motif",
        "show_overlay",
        "continuation_group_id",
        "continuation_index",
        "continuation_count",
    ):
        semantic.pop(field, None)
    return semantic


def _scene_cap_warnings(scenes: list[dict[str, Any]], policy: dict[str, Any]) -> list[str]:
    config_fields = {
        "source_article_scene": "max_source_article_scenes",
        "context_image_scene": "max_context_image_scenes",
        "broll_video_scene": "max_broll_video_scenes",
        "logo_reveal_scene": "max_logo_reveal_scenes",
        "editorial_text_scene": "max_editorial_text_scenes",
        "simple_explainer_scene": "max_simple_explainer_scenes",
        "story_transition_scene": "max_story_transition_scenes",
        "kinetic_type_scene": "max_kinetic_type_scenes",
        "bullet_build_scene": "max_bullet_build_scenes",
        "quote_or_claim_highlight_scene": "max_quote_or_claim_highlight_scenes",
        "entity_compare_scene": "max_entity_compare_scenes",
        "recap_sequence_scene": "max_recap_sequence_scenes",
        "data_counter_scene": "max_data_counter_scenes",
        "trend_line_scene": "max_trend_line_scenes",
        "bar_chart_scene": "max_bar_chart_scenes",
        "bar_race_scene": "max_bar_race_scenes",
        "ranked_list_scene": "max_ranked_list_scenes",
        "benchmark_delta_scene": "max_benchmark_delta_scenes",
        "ecosystem_map_scene": "max_ecosystem_map_scenes",
        "architecture_flow_scene": "max_architecture_flow_scenes",
        "process_zoom_scene": "max_process_zoom_scenes",
        "browser_walkthrough_scene": "max_browser_walkthrough_scenes",
        "decision_tree_scene": "max_decision_tree_scenes",
        "capability_matrix_scene": "max_capability_matrix_scenes",
        "timeline_zoom_scene": "max_timeline_zoom_scenes",
        "document_stack_scene": "max_document_stack_scenes",
        "signal_radar_scene": "max_signal_radar_scenes",
        "interface_transform_scene": "max_interface_transform_scenes",
        "transition_stinger_scene": "max_transition_stinger_scenes",
    }
    counts = Counter(clean_text(scene.get("render_kind", "")) for scene in scenes)
    warnings: list[str] = []
    for render_kind, field in config_fields.items():
        limit = safe_int(policy.get(field), 999999)
        if counts.get(render_kind, 0) > limit:
            warnings.append(
                f"{render_kind} count {counts[render_kind]} exceeds scene_policy.{field}={limit}; "
                "visual-editor or human review is recommended"
            )
    return warnings


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


def _story_planner_failures(visual_scene_plan: dict[str, Any]) -> list[str]:
    return dedupe(
        [
            clean_text(plan.get("story_id", ""))
            for plan in visual_scene_plan.get("story_plans", [])
            if isinstance(plan, dict)
            and plan.get("planning_failed")
            and clean_text(plan.get("story_id", ""))
        ]
    )


def _provider_failover_summary(llm_calls: list[dict[str, Any]]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for call in llm_calls:
        metadata = call.get("metadata") if isinstance(call.get("metadata"), dict) else {}
        if metadata.get("route_attempt") != "content_filter_fallback":
            continue
        events.append(
            {
                "module_name": clean_text(call.get("module_name", "")),
                "story_id": clean_text(metadata.get("story_id", "")) or None,
                "trigger": clean_text(metadata.get("fallback_trigger", "")) or "content_filter",
                "from_provider": clean_text(metadata.get("fallback_from_provider", "")),
                "from_model": clean_text(metadata.get("fallback_from_model", "")),
                "to_provider": clean_text(call.get("provider", "")),
                "to_model": clean_text(call.get("model", "")),
            }
        )
    return {
        "content_filter_fallback_call_count": len(events),
        "events": events,
    }


def _build_summary(visual_scene_plan: dict[str, Any], llm_calls: list[dict[str, Any]], failure_reason: str) -> dict[str, Any]:
    scenes = visual_scene_plan.get("scene_timeline", [])
    kinds = [scene.get("render_kind", "") for scene in scenes]
    coverage = visual_scene_plan.get("coverage", {})
    story_planner_fallbacks = _story_planner_fallbacks(visual_scene_plan)
    story_planner_failures = _story_planner_failures(visual_scene_plan)
    story_planner_parse_errors = [
        call
        for call in visual_scene_plan.get("planning_calls", [])
        if clean_text(call.get("module_name", "")) == STORY_VISUAL_PLANNER_PROMPT_MODULE
        and (
            clean_text(call.get("parse_error", ""))
            or clean_text((call.get("metadata") if isinstance(call.get("metadata"), dict) else {}).get("parse_error", ""))
        )
    ]
    story_planner_validation_failures = []
    for call in visual_scene_plan.get("planning_calls", []):
        if clean_text(call.get("module_name", "")) != STORY_VISUAL_PLANNER_PROMPT_MODULE:
            continue
        metadata = call.get("metadata") if isinstance(call.get("metadata"), dict) else {}
        validation_errors = (
            metadata.get("validation_errors")
            if isinstance(metadata.get("validation_errors"), list)
            else []
        )
        if validation_errors:
            story_planner_validation_failures.append(
                {
                    "story_id": clean_text(metadata.get("story_id", "")),
                    "attempt": safe_int(metadata.get("attempt"), 0),
                    "validation_errors": [clean_text(item) for item in validation_errors],
                }
            )
    story_planner_fallback_reasons = [
        {
            "story_id": clean_text(plan.get("story_id", "")),
            "fallback_reason": clean_text(plan.get("fallback_reason", "")),
        }
        for plan in visual_scene_plan.get("story_plans", [])
        if isinstance(plan, dict) and clean_text(plan.get("fallback_reason", ""))
    ]
    story_planner_failure_reasons = [
        {
            "story_id": clean_text(plan.get("story_id", "")),
            "planning_failure_reason": clean_text(plan.get("planning_failure_reason", "")),
        }
        for plan in visual_scene_plan.get("story_plans", [])
        if isinstance(plan, dict) and clean_text(plan.get("planning_failure_reason", ""))
    ]
    timing_continuation_scenes = [
        scene
        for scene in scenes
        if safe_int(
            (scene.get("payload") if isinstance(scene.get("payload"), dict) else {}).get(
                "continuation_count"
            ),
            0,
        )
        > 1
    ]
    timing_continuation_groups = dedupe(
        [
            clean_text(
                (
                    scene.get("payload")
                    if isinstance(scene.get("payload"), dict)
                    else {}
                ).get("continuation_group_id")
            )
            for scene in timing_continuation_scenes
            if clean_text(
                (
                    scene.get("payload")
                    if isinstance(scene.get("payload"), dict)
                    else {}
                ).get("continuation_group_id")
            )
        ]
    )
    editor_report = (
        visual_scene_plan.get("visual_editor")
        if isinstance(visual_scene_plan.get("visual_editor"), dict)
        else {}
    )
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
        "editorial_text_scene_count": kinds.count("editorial_text_scene"),
        "simple_explainer_scene_count": kinds.count("simple_explainer_scene"),
        "story_transition_scene_count": kinds.count("story_transition_scene"),
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
        "adjacent_duplicate_visual_count": len(_adjacent_duplicate_visual_payloads(scenes)),
        "llm_call_count": len(llm_calls),
        "provider_failover": _provider_failover_summary(llm_calls),
        "visual_editor_enabled": bool(editor_report.get("enabled")),
        "visual_editor_reviewed_story_count": safe_int(
            editor_report.get("reviewed_story_count"), 0
        ),
        "visual_editor_revision_count": safe_int(editor_report.get("revision_count"), 0),
        "visual_editor_failure_count": safe_int(editor_report.get("failure_count"), 0),
        "story_planner_fallback_count": len(story_planner_fallbacks),
        "story_planner_fallback_story_ids": story_planner_fallbacks,
        "story_planner_fallback_reasons": story_planner_fallback_reasons,
        "story_planner_failure_count": len(story_planner_failures),
        "story_planner_failure_story_ids": story_planner_failures,
        "story_planner_failure_reasons": story_planner_failure_reasons,
        "story_planner_parse_error_count": len(story_planner_parse_errors),
        "story_planner_validation_failure_count": len(story_planner_validation_failures),
        "story_planner_validation_failures": story_planner_validation_failures,
        "timing_continuation_scene_count": len(timing_continuation_scenes),
        "timing_continuation_group_count": len(timing_continuation_groups),
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
                    "beat_function": clean_text(beat.get("beat_function", "")),
                    "support_truth_ids": list(beat.get("support_truth_ids", [])),
                    "creative_device": clean_text(beat.get("creative_device", "")) or "none",
                    "visual_goal": clean_text(beat.get("visual_goal", "")),
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
            item["beat_function"] = beat.get("beat_function", item.get("beat_function", ""))
            item["support_truth_ids"] = list(beat.get("support_truth_ids", []))
            item["creative_device"] = beat.get("creative_device", item.get("creative_device", "none"))
            item["visual_goal"] = beat.get("visual_goal", item.get("visual_goal", ""))
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


def _episode_script_context(script_units: list[dict[str, Any]]) -> dict[str, Any]:
    units = [deepcopy(unit) for unit in script_units if isinstance(unit, dict)]
    return {
        "units": units,
        "telemetry": {
            "context_mode": "complete_timed_script_units",
            "unit_count": len(units),
            "unit_ids": [clean_text(unit.get("unit_id")) for unit in units],
            "serialized_unit_chars": len(
                json.dumps(units, ensure_ascii=False, default=str)
            ),
            "units_truncated": False,
        },
    }


def _story_coverage_contract(
    section: dict[str, Any],
    *,
    max_scene_seconds: float = 14.0,
    hard_max_scene_seconds: float | None = None,
    hard_cap_tolerance_seconds: float = 0.0,
    unit_assignment_mode: str = "one_scene_per_script_unit",
) -> dict[str, Any]:
    section_start = safe_int(section.get("start_unit_order"), 1)
    section_end = safe_int(section.get("end_unit_order"), section_start)
    title_unit_order = section_start if section.get("title_card") else None
    required_start = section_start + (1 if title_unit_order is not None else 0)
    max_scene_seconds = max(1.0, max_scene_seconds)
    configured_hard_cap = (
        max_scene_seconds
        if hard_max_scene_seconds is None
        else max(max_scene_seconds, hard_max_scene_seconds)
    )
    tolerance = max(0.0, hard_cap_tolerance_seconds)
    hard_cap = configured_hard_cap + tolerance
    deterministic_splits = []
    required_unit_orders = list(range(required_start, section_end + 1))
    for unit in section.get("script_units", []):
        unit_order = safe_int(unit.get("order"), 0)
        if unit_order < required_start or unit_order > section_end:
            continue
        duration = safe_float(unit.get("duration_seconds"), 0.0)
        if duration <= 0:
            duration = max(
                0.0,
                safe_float(unit.get("end_seconds"), 0.0)
                - safe_float(unit.get("start_seconds"), 0.0),
            )
        if duration > hard_cap + 0.01:
            deterministic_splits.append(
                {
                    "unit_order": unit_order,
                    "duration_seconds": round(duration, 2),
                    "slice_count": max(2, math.ceil(duration / hard_cap)),
                }
            )
    split_counts = {
        safe_int(item.get("unit_order"), 0): safe_int(item.get("slice_count"), 1)
        for item in deterministic_splits
    }
    required_scene_slots = [
        {
            "slot_id": f"unit_{unit_order:03d}_slice_{slice_index:02d}",
            "start_unit_order": unit_order,
            "end_unit_order": unit_order,
            "slice_index": slice_index,
            "slice_count": split_counts.get(unit_order, 1),
        }
        for unit_order in required_unit_orders
        for slice_index in range(1, split_counts.get(unit_order, 1) + 1)
    ]
    return {
        "target_max_scene_seconds": max_scene_seconds,
        "hard_max_scene_seconds": configured_hard_cap,
        "hard_cap_tolerance_seconds": tolerance,
        "effective_hard_max_scene_seconds": hard_cap,
        "unit_assignment_mode": unit_assignment_mode,
        "title_unit_order": title_unit_order,
        "required_unit_orders": required_unit_orders,
        "required_scene_slots": required_scene_slots,
        "deterministic_timing_splits": deterministic_splits,
        "coverage_rule": (
            "Return exactly one scene for every required_scene_slots entry using that "
            "entry's start_unit_order and end_unit_order. When one unit has multiple slots, "
            "prefer different supported visual treatments for those slots, but repeat the "
            "same honest treatment rather than inventing unsupported content. Do not combine "
            "adjacent script units into one scene, skip a slot, or author seconds. "
            "Deterministic stitching assigns exact timing and continuation phases."
        ),
    }


def _hard_max_scene_seconds(policy: dict[str, Any]) -> float:
    target = max(1.0, safe_float(policy.get("max_scene_seconds"), 14.0))
    configured = safe_float(policy.get("hard_max_scene_seconds"), target)
    return max(target, configured)


def _effective_hard_max_scene_seconds(policy: dict[str, Any]) -> float:
    return _hard_max_scene_seconds(policy) + max(
        0.0,
        safe_float(policy.get("hard_cap_tolerance_seconds"), 0.0),
    )


def _script_units_for_bookend_prompt(
    script_units: list[dict[str, Any]],
    *,
    source_index: dict[str, Any],
) -> list[dict[str, Any]]:
    truth_items_by_id = source_index.get("truth_items_by_id", {})
    output: list[dict[str, Any]] = []
    for unit in script_units:
        eligible_truth_items = []
        for truth_id in unit.get("support_truth_ids", []):
            item = truth_items_by_id.get(clean_text(truth_id), {})
            if not isinstance(item, dict) or not clean_text(item.get("source_text")):
                continue
            eligible_truth_items.append(
                {
                    "truth_id": clean_text(item.get("truth_id")),
                    "story_id": clean_text(item.get("story_id")),
                    "record_key": clean_text(item.get("record_key")),
                    "truth_type": clean_text(item.get("truth_type")),
                    "value_text": clean_text(item.get("value_text")),
                    "source_text": short_text(clean_text(item.get("source_text")), 320),
                }
            )
        output.append(
            {
                "unit_id": unit.get("unit_id"),
                "order": unit.get("order"),
                "start_seconds": unit.get("start_seconds"),
                "end_seconds": unit.get("end_seconds"),
                "duration_seconds": unit.get("duration_seconds"),
                "text": clean_text(unit.get("text")),
                "beat_id": unit.get("beat_id", ""),
                "beat_type": unit.get("beat_type", ""),
                "beat_function": unit.get("beat_function", ""),
                "creative_device": unit.get("creative_device", "none"),
                "visual_goal": unit.get("visual_goal", ""),
                "source_record_keys": unit.get("source_record_keys", []),
                "support_truth_ids": unit.get("support_truth_ids", []),
                "eligible_truth_items": eligible_truth_items,
                "visual_brief": unit.get("visual_brief", {}),
            }
        )
    return output


def _script_units_for_story_prompt(
    script_units: list[dict[str, Any]],
    *,
    source_index: dict[str, Any],
    story_id: str,
) -> list[dict[str, Any]]:
    truth_items_by_id = source_index.get("truth_items_by_id", {})

    def eligible_metrics(unit: dict[str, Any]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for truth_id in unit.get("support_truth_ids", []):
            item = truth_items_by_id.get(clean_text(truth_id), {})
            if (
                clean_text(item.get("story_id")) != story_id
                or clean_text(item.get("truth_type")) != "metric"
                or not clean_text(item.get("value_text"))
            ):
                continue
            items.append(
                {
                    "truth_id": clean_text(item.get("truth_id")),
                    "record_key": clean_text(item.get("record_key")),
                    "value_text": clean_text(item.get("value_text")),
                    "source_text": short_text(clean_text(item.get("source_text")), 260),
                }
            )
        return items

    def eligible_source_targets(unit: dict[str, Any]) -> list[dict[str, Any]]:
        allowed_record_keys = {
            clean_text(value)
            for value in unit.get("source_record_keys", [])
            if clean_text(value)
        }
        items: list[dict[str, Any]] = []
        for truth_id in unit.get("support_truth_ids", []):
            item = truth_items_by_id.get(clean_text(truth_id), {})
            record_key = clean_text(item.get("record_key"))
            if (
                clean_text(item.get("story_id")) != story_id
                or not record_key
                or (allowed_record_keys and record_key not in allowed_record_keys)
                or clean_text(item.get("source_field")) not in {"content", "title"}
                or not clean_text(item.get("source_text"))
            ):
                continue
            items.append(
                {
                    "truth_id": clean_text(item.get("truth_id")),
                    "record_key": record_key,
                    "source_text": short_text(clean_text(item.get("source_text")), 360),
                    "source_field": clean_text(item.get("source_field")),
                    "source_order": safe_int(item.get("source_order"), 0),
                }
            )
        return items

    output: list[dict[str, Any]] = []
    for unit in script_units:
        metric_items = eligible_metrics(unit)
        source_targets = eligible_source_targets(unit)
        output.append(
            {
                "unit_id": unit.get("unit_id"),
                "order": unit.get("order"),
                "start_seconds": unit.get("start_seconds"),
                "end_seconds": unit.get("end_seconds"),
                "duration_seconds": unit.get("duration_seconds"),
                "text": clean_text(unit.get("text", "")),
                "beat_id": unit.get("beat_id", ""),
                "beat_type": unit.get("beat_type", ""),
                "beat_function": unit.get("beat_function", ""),
                "support_truth_ids": unit.get("support_truth_ids", []),
                "eligible_numeric_truth_items": metric_items,
                "numeric_graphics_allowed": bool(metric_items),
                "eligible_source_screenshot_targets": source_targets,
                "creative_device": unit.get("creative_device", "none"),
                "visual_goal": unit.get("visual_goal", ""),
                "source_record_keys": unit.get("source_record_keys", []),
                "visual_brief": unit.get("visual_brief", {}),
            }
        )
    return output


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
                "provider": call.get("provider"),
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
        return ""
    return " ".join(words[:7]).strip(" ,.;:")


def _points_from_text(text: str, *, max_points: int = 4, max_chars: int = 64) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return []
    sentences = [clean_text(item) for item in re.split(r"(?<=[.!?])\s+", normalized) if clean_text(item)]
    points = [short_text(sentence, max_chars).strip(" ,.;:") for sentence in sentences if count_words(sentence) >= 3]
    if len(points) < max_points:
        chunks = re.split(r"\b(?:and|but|while|because|with|where)\b|[,;:]", normalized)
        points.extend(short_text(clean_text(chunk), max_chars).strip(" ,.;:") for chunk in chunks if count_words(chunk) >= 3)
    return dedupe([point for point in points if point])[:max_points] or [
        phrase for phrase in [_short_phrase(normalized)] if phrase
    ]


def _metrics_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    del script_excerpt
    metrics: list[dict[str, str]] = []
    for item in draft.get("metrics", []):
        if not isinstance(item, dict):
            continue
        value = short_text(clean_text(item.get("value", "")), 18)
        label = short_text(clean_text(item.get("label", "")) or clean_text(item.get("name", "")), 32)
        if value and label:
            metrics.append(
                {
                    "label": label,
                    "value": value,
                    "unit": short_text(clean_text(item.get("unit", "")), 12),
                    "context": short_text(clean_text(item.get("context", "")), 58),
                }
            )
    if clean_text(draft.get("metric_value", "")) and clean_text(draft.get("metric_label", "")):
        metrics.append(
            {
                "label": short_text(clean_text(draft.get("metric_label", "")), 32),
                "value": short_text(clean_text(draft.get("metric_value", "")), 18),
                "unit": short_text(clean_text(draft.get("metric_unit", "")), 12),
                "context": short_text(clean_text(draft.get("metric_context", "")), 58),
            }
        )
    return metrics




def _bars_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    del script_excerpt
    bars: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("bars", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", ""))
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
    return bars




def _ranked_items_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str | int]]:
    del script_excerpt
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
    return items


def _race_items_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    del script_excerpt
    items: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("items", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", ""))
        start_value = clean_text(item.get("start_value", ""))
        end_value = clean_text(item.get("end_value", "")) or clean_text(item.get("value", ""))
        if label and start_value and end_value:
            items.append(
                {
                    "label": short_text(label, 30),
                    "start_value": short_text(start_value, 18),
                    "end_value": short_text(end_value, 18),
                    "display_value": short_text(clean_text(item.get("display_value", "")) or end_value, 18),
                }
            )
    return items




def _benchmarks_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    del script_excerpt
    benchmarks: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("benchmarks", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", ""))
        before = clean_text(item.get("before", ""))
        after = clean_text(item.get("after", ""))
        delta = clean_text(item.get("delta", ""))
        if label and (before or after or delta):
            benchmarks.append(
                {
                    "label": short_text(label, 28),
                    "before": short_text(before, 18),
                    "after": short_text(after, 18),
                    "delta": short_text(delta, 18),
                    "unit": short_text(clean_text(item.get("unit", "")), 12),
                    "context": short_text(clean_text(item.get("context", "")) or clean_text(item.get("detail", "")), 48),
                }
            )
    return benchmarks


def _walkthrough_steps_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    return _flow_steps_from_draft({"steps": draft.get("walkthrough_steps", [])}, script_excerpt)




def _decision_branches_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    return _flow_steps_from_draft({"steps": draft.get("branches", [])}, script_excerpt)


def _matrix_columns_from_draft(draft: dict[str, Any]) -> list[str]:
    columns = [short_text(clean_text(item), 18) for item in draft.get("columns", []) if clean_text(item)]
    return columns[:5]




def _matrix_rows_from_draft(
    draft: dict[str, Any],
    script_excerpt: str,
    columns: list[str],
) -> list[dict[str, Any]]:
    del script_excerpt
    rows: list[dict[str, Any]] = []
    for item in draft.get("rows", []):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", ""))
        supplied_values = item.get("values") if isinstance(item.get("values"), list) else []
        if supplied_values:
            values = [short_text(clean_text(value), 18) for value in supplied_values]
        else:
            normalized_item = {
                re.sub(r"[^a-z0-9]+", "_", clean_text(key).lower()).strip("_"): value
                for key, value in item.items()
            }
            values = [
                short_text(
                    clean_text(
                        normalized_item.get(
                            re.sub(r"[^a-z0-9]+", "_", clean_text(column).lower()).strip("_"),
                            "",
                        )
                    ),
                    18,
                )
                for column in columns
            ]
        rows.append(
            {
                "label": short_text(label, 24),
                "values": values,
                "highlight": short_text(clean_text(item.get("highlight", "")), 18),
            }
        )
    return [row for row in rows if row["label"]]




def _timeline_events_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    del script_excerpt
    events: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("events", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", ""))
        events.append(
            {
                "label": short_text(label, 34),
                "date": short_text(clean_text(item.get("date", "")), 14),
                "detail": short_text(clean_text(item.get("detail", "")), 46),
                "importance": short_text(clean_text(item.get("importance", "")), 18),
            }
        )
    return [event for event in events if event["label"]]






def _documents_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    del script_excerpt
    documents: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("documents", []), start=1):
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title", ""))
        documents.append(
            {
                "title": short_text(title, 42),
                "source": short_text(clean_text(item.get("source", "")), 22),
                "document_type": short_text(clean_text(item.get("document_type", "")), 18),
                "date": short_text(clean_text(item.get("date", "")), 20),
                "detail": short_text(clean_text(item.get("detail", "")), 46),
                "status": short_text(clean_text(item.get("status", "")), 18),
                "asset_id": clean_text(item.get("asset_id", "")),
                "source_record_key": clean_text(item.get("source_record_key", "")),
                "url": clean_text(item.get("url", "")),
                "target_text": short_text(clean_text(item.get("target_text", "")), 260),
            }
        )
    return [document for document in documents if document["title"]]


def _scene_source_urls(primary_url: str, payload: dict[str, Any]) -> list[str]:
    urls = [clean_text(primary_url)] if clean_text(primary_url) else []
    for document in payload.get("documents", []):
        if isinstance(document, dict):
            url = clean_text(document.get("url"))
            if url.startswith(("http://", "https://")):
                urls.append(url)
    return dedupe(urls)




def _signals_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    del script_excerpt
    signals: list[dict[str, str]] = []
    for index, item in enumerate(draft.get("signals", []), start=1):
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label", "")) or clean_text(item.get("name", ""))
        strength = clean_text(item.get("strength", ""))
        signals.append(
            {
                "label": short_text(label, 28),
                "strength": short_text(strength, 12),
                "detail": short_text(clean_text(item.get("detail", "")) or clean_text(item.get("context", "")), 32),
            }
        )
    return [signal for signal in signals if signal["label"] and signal["strength"]]




def _interface_panel_from_draft(value: Any, fallback_label: str, script_excerpt: str, *, flow: bool = False) -> dict[str, Any]:
    del fallback_label, script_excerpt, flow
    source = value if isinstance(value, dict) else {}
    items = [short_text(clean_text(item), 34) for item in source.get("items", []) if clean_text(item)]
    return {
        "label": short_text(clean_text(source.get("label", "")), 28),
        "detail": short_text(clean_text(source.get("detail", "")), 44),
        "items": items[:4],
    }








def _annotations_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[str]:
    del script_excerpt
    annotations = [short_text(clean_text(item), 42) for item in draft.get("annotations", []) if clean_text(item)]
    return dedupe([item for item in annotations if item])[:3]






def _nodes_from_draft(draft: dict[str, Any]) -> list[dict[str, str]]:
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
    return nodes




def _edges_from_draft(draft: dict[str, Any], nodes: list[dict[str, str]]) -> list[dict[str, str]]:
    node_ids = {node["id"] for node in nodes}
    edges: list[dict[str, str]] = []
    for item in draft.get("edges", []):
        if not isinstance(item, dict):
            continue
        source = clean_text(item.get("from", "")) or clean_text(item.get("source", ""))
        target = clean_text(item.get("to", "")) or clean_text(item.get("target", ""))
        if source in node_ids and target in node_ids and source != target:
            label = short_text(clean_text(item.get("label", "")), 22)
            if label:
                edges.append({"from": source, "to": target, "label": label})
    return edges[:8]




def _flow_steps_from_draft(draft: dict[str, Any], script_excerpt: str) -> list[dict[str, str]]:
    del script_excerpt
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
    return steps


def _focus_step_from_steps(steps: list[dict[str, str]]) -> str:
    if not steps:
        return ""
    if len(steps) >= 3:
        return clean_text(steps[1].get("label", "")) or clean_text(steps[2].get("label", ""))
    return clean_text(steps[-1].get("label", ""))




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
    if render_kind == "editorial_text_scene":
        return "Use clean editorial typography to punctuate one concise idea without a card."
    if render_kind == "simple_explainer_scene":
        return "Explain one short relationship or process with a few clear labels and restrained connectors."
    if render_kind == "story_transition_scene":
        return "Introduce the next roundup story with a clean editorial chapter transition."
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
