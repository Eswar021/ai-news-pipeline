from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_MAX_BULLET_BUILD_SCENES,
    DEFAULT_MAX_CONSECUTIVE_SAME_KIND,
    DEFAULT_MAX_ARCHITECTURE_FLOW_SCENES,
    DEFAULT_MAX_BAR_CHART_SCENES,
    DEFAULT_MAX_BAR_RACE_SCENES,
    DEFAULT_MAX_BENCHMARK_DELTA_SCENES,
    DEFAULT_MAX_BROWSER_WALKTHROUGH_SCENES,
    DEFAULT_MAX_BROLL_VIDEO_SCENES,
    DEFAULT_MAX_CAPABILITY_MATRIX_SCENES,
    DEFAULT_MAX_CONTEXT_IMAGE_SCENES,
    DEFAULT_MAX_DATA_COUNTER_SCENES,
    DEFAULT_MAX_DECISION_TREE_SCENES,
    DEFAULT_MAX_DOCUMENT_STACK_SCENES,
    DEFAULT_MAX_ECOSYSTEM_MAP_SCENES,
    DEFAULT_MAX_ENTITY_COMPARE_SCENES,
    DEFAULT_MAX_INTERFACE_TRANSFORM_SCENES,
    DEFAULT_MAX_KINETIC_TYPE_SCENES,
    DEFAULT_MAX_LOGO_REVEAL_SCENES,
    DEFAULT_MAX_QUOTE_OR_CLAIM_SCENES,
    DEFAULT_MAX_RECAP_SEQUENCE_SCENES,
    DEFAULT_MAX_PROCESS_ZOOM_SCENES,
    DEFAULT_MAX_RANKED_LIST_SCENES,
    DEFAULT_MAX_SIGNAL_RADAR_SCENES,
    DEFAULT_MAX_TIMELINE_ZOOM_SCENES,
    DEFAULT_MAX_TREND_LINE_SCENES,
    DEFAULT_MAX_TRANSITION_STINGER_SCENES,
    DEFAULT_MAX_RECORD_CHARS,
    DEFAULT_MAX_RECORDS_PER_STORY,
    DEFAULT_MAX_SCENES,
    DEFAULT_MAX_SCENE_SECONDS,
    DEFAULT_MAX_SCENES_PER_STORY,
    DEFAULT_MAX_SOURCE_ARTICLE_SCENES,
    DEFAULT_MIN_SCENE_SECONDS,
    DEFAULT_MIN_SCENES_PER_STORY,
    DEFAULT_VISUAL_CAPABILITIES,
    RENDER_KINDS,
)


VisualPlannerStatus = Literal["ok", "failed"]
LLMProvider = Literal["openai", "gemini", "lmstudio"]
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


class VisualsRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class VisualStyleConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    visual_language: str = "premium YouTube AI news motion graphics"
    motion_style: str = "fast editorial cuts, article zooms, logo reveals, kinetic type"
    color_system: str = "dark graphite newsroom with electric cyan, warm white, and restrained red accents"
    typography: str = "bold broadcast sans, large kinetic phrases, minimal small text"
    avoid: list[str] = Field(
        default_factory=lambda: [
            "PPT-style cards",
            "generic timeline cards",
            "static slide-deck layouts",
            "walls of text",
        ]
    )


class ScenePolicyConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    target_aspect_ratio: str = "16:9"
    max_scenes: int = DEFAULT_MAX_SCENES
    min_scene_seconds: float = DEFAULT_MIN_SCENE_SECONDS
    max_scene_seconds: float = DEFAULT_MAX_SCENE_SECONDS
    semantic_min_scene_seconds: float = 5.0
    semantic_target_scene_seconds: float = 9.0
    semantic_max_units_per_scene: int = 4
    compact_per_chunk_scenes: bool = True
    min_scenes_per_story: int = DEFAULT_MIN_SCENES_PER_STORY
    max_scenes_per_story: int = DEFAULT_MAX_SCENES_PER_STORY
    max_source_article_scenes: int = DEFAULT_MAX_SOURCE_ARTICLE_SCENES
    max_context_image_scenes: int = DEFAULT_MAX_CONTEXT_IMAGE_SCENES
    max_broll_video_scenes: int = DEFAULT_MAX_BROLL_VIDEO_SCENES
    max_logo_reveal_scenes: int = DEFAULT_MAX_LOGO_REVEAL_SCENES
    max_kinetic_type_scenes: int = DEFAULT_MAX_KINETIC_TYPE_SCENES
    max_bullet_build_scenes: int = DEFAULT_MAX_BULLET_BUILD_SCENES
    max_quote_or_claim_highlight_scenes: int = DEFAULT_MAX_QUOTE_OR_CLAIM_SCENES
    max_entity_compare_scenes: int = DEFAULT_MAX_ENTITY_COMPARE_SCENES
    max_recap_sequence_scenes: int = DEFAULT_MAX_RECAP_SEQUENCE_SCENES
    max_data_counter_scenes: int = DEFAULT_MAX_DATA_COUNTER_SCENES
    max_trend_line_scenes: int = DEFAULT_MAX_TREND_LINE_SCENES
    max_bar_chart_scenes: int = DEFAULT_MAX_BAR_CHART_SCENES
    max_bar_race_scenes: int = DEFAULT_MAX_BAR_RACE_SCENES
    max_ranked_list_scenes: int = DEFAULT_MAX_RANKED_LIST_SCENES
    max_benchmark_delta_scenes: int = DEFAULT_MAX_BENCHMARK_DELTA_SCENES
    max_ecosystem_map_scenes: int = DEFAULT_MAX_ECOSYSTEM_MAP_SCENES
    max_architecture_flow_scenes: int = DEFAULT_MAX_ARCHITECTURE_FLOW_SCENES
    max_process_zoom_scenes: int = DEFAULT_MAX_PROCESS_ZOOM_SCENES
    max_browser_walkthrough_scenes: int = DEFAULT_MAX_BROWSER_WALKTHROUGH_SCENES
    max_decision_tree_scenes: int = DEFAULT_MAX_DECISION_TREE_SCENES
    max_capability_matrix_scenes: int = DEFAULT_MAX_CAPABILITY_MATRIX_SCENES
    max_timeline_zoom_scenes: int = DEFAULT_MAX_TIMELINE_ZOOM_SCENES
    max_document_stack_scenes: int = DEFAULT_MAX_DOCUMENT_STACK_SCENES
    max_signal_radar_scenes: int = DEFAULT_MAX_SIGNAL_RADAR_SCENES
    max_interface_transform_scenes: int = DEFAULT_MAX_INTERFACE_TRANSFORM_SCENES
    max_transition_stinger_scenes: int = DEFAULT_MAX_TRANSITION_STINGER_SCENES
    max_consecutive_same_kind: int = DEFAULT_MAX_CONSECUTIVE_SAME_KIND
    allowed_render_kinds: list[RenderKind] = Field(default_factory=lambda: list(RENDER_KINDS))

    @model_validator(mode="after")
    def validate_scene_policy(self) -> "ScenePolicyConfig":
        if self.max_scenes < 3 or self.max_scenes > 120:
            raise ValueError("scene_policy.max_scenes must be between 3 and 120")
        if self.min_scene_seconds <= 0 or self.max_scene_seconds <= 0:
            raise ValueError("scene_policy scene seconds must be positive")
        if self.min_scene_seconds > self.max_scene_seconds:
            raise ValueError("scene_policy.min_scene_seconds must be <= max_scene_seconds")
        if self.semantic_min_scene_seconds <= 0 or self.semantic_target_scene_seconds <= 0:
            raise ValueError("scene_policy semantic scene seconds must be positive")
        if self.semantic_min_scene_seconds > self.max_scene_seconds:
            raise ValueError("scene_policy.semantic_min_scene_seconds must be <= max_scene_seconds")
        if self.semantic_target_scene_seconds > self.max_scene_seconds:
            raise ValueError("scene_policy.semantic_target_scene_seconds must be <= max_scene_seconds")
        if self.semantic_max_units_per_scene < 1:
            raise ValueError("scene_policy.semantic_max_units_per_scene must be at least 1")
        if self.min_scenes_per_story < 1:
            raise ValueError("scene_policy.min_scenes_per_story must be at least 1")
        if self.max_scenes_per_story < self.min_scenes_per_story:
            raise ValueError("scene_policy.max_scenes_per_story must be >= min_scenes_per_story")
        if self.max_consecutive_same_kind < 1:
            raise ValueError("scene_policy.max_consecutive_same_kind must be at least 1")
        if not self.allowed_render_kinds:
            raise ValueError("scene_policy.allowed_render_kinds must not be empty")
        return self


class SourcePolicyConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    use_selected_stories_only: bool = True
    include_full_records: bool = True
    max_records_per_story_for_prompt: int = DEFAULT_MAX_RECORDS_PER_STORY
    max_record_chars_for_prompt: int = DEFAULT_MAX_RECORD_CHARS

    @model_validator(mode="after")
    def validate_source_policy(self) -> "SourcePolicyConfig":
        if not self.use_selected_stories_only:
            raise ValueError("source_policy.use_selected_stories_only must be true")
        if not self.include_full_records:
            raise ValueError("source_policy.include_full_records must be true")
        if self.max_records_per_story_for_prompt < 1:
            raise ValueError("source_policy.max_records_per_story_for_prompt must be at least 1")
        if self.max_record_chars_for_prompt < 300:
            raise ValueError("source_policy.max_record_chars_for_prompt must be at least 300")
        return self


class VisualCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    description: str
    best_for: list[str] = Field(default_factory=list)
    required_payload_fields: list[str] = Field(default_factory=list)
    avoid_when: list[str] = Field(default_factory=list)
    render_notes: str = ""

    @field_validator("description")
    @classmethod
    def description_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("visual capability descriptions must not be empty")
        return value


def default_visual_capabilities() -> dict[str, VisualCapabilityConfig]:
    return {
        key: VisualCapabilityConfig.model_validate(value)
        for key, value in DEFAULT_VISUAL_CAPABILITIES.items()
    }


class VisualPlannerConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: LLMProvider
    model: str
    base_url: str | None = None
    prompt_version: str
    temperature: float = 0.3
    words_per_minute: int = 150
    allow_deterministic_story_fallbacks: bool = False
    style: VisualStyleConfig = Field(default_factory=VisualStyleConfig)
    scene_policy: ScenePolicyConfig = Field(default_factory=ScenePolicyConfig)
    source_policy: SourcePolicyConfig = Field(default_factory=SourcePolicyConfig)
    visual_capabilities: dict[str, VisualCapabilityConfig] = Field(default_factory=default_visual_capabilities)

    @field_validator("model", "prompt_version")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.model and config.prompt_version must not be empty")
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("config.temperature must be between 0 and 2")
        return value

    @field_validator("words_per_minute")
    @classmethod
    def words_per_minute_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("config.words_per_minute must be at least 1")
        return value

    @model_validator(mode="after")
    def capabilities_must_cover_allowed_render_kinds(self) -> "VisualPlannerConfig":
        missing = [
            render_kind
            for render_kind in self.scene_policy.allowed_render_kinds
            if render_kind not in self.visual_capabilities
        ]
        if missing:
            raise ValueError(f"config.visual_capabilities is missing allowed render kinds: {missing}")
        return self


class ScriptGenerationData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    selected_format: str | None = None
    script_package: dict[str, Any]


class ScriptGenerationEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: ScriptGenerationData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VideoPackagingData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    selected_format: str
    script_app: str | None = None
    video_packet: dict[str, Any]


class VideoPackagingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: VideoPackagingData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VisualPlannerInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    video_packaging: VideoPackagingEnvelope
    script_generation: ScriptGenerationEnvelope | None = None
    script_text: str | None = None
    script_source: str | None = None
    voiceover: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_one_script_source(self) -> "VisualPlannerInput":
        has_script_generation = self.script_generation is not None
        has_script_text = bool((self.script_text or "").strip())
        if has_script_generation == has_script_text:
            raise ValueError("Provide exactly one of input.script_generation or input.script_text")
        return self


class VisualPlannerRequest(BaseModel):
    run: VisualsRun
    config: VisualPlannerConfig
    input: VisualPlannerInput


class VisualPlannerData(BaseModel):
    run_id: str
    generated_at: str
    selected_format: str
    visual_scene_plan: dict[str, Any]


class VisualPlannerSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    script_word_count: int
    voiceover_duration_seconds: float
    story_count: int
    scene_count: int
    source_article_scene_count: int
    logo_reveal_scene_count: int
    kinetic_type_scene_count: int
    llm_call_count: int
    failure_reason: str = ""


class VisualPlannerHandoff(BaseModel):
    ready_for_visual_asset_resolution: bool
    ready_for_visual_media_discovery: bool
    next_module: str
    selected_format: str


class VisualPlannerResponse(BaseModel):
    status: VisualPlannerStatus
    data: VisualPlannerData
    summary: VisualPlannerSummary
    handoff: VisualPlannerHandoff
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
