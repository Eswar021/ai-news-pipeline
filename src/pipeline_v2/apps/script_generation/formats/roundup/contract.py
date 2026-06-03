from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_MAX_REVISION_PASSES,
    DEFAULT_REFLECTION_ENABLED,
    DEFAULT_REFLECTION_TARGET_SCORE,
    DEFAULT_SCRIPT_WORKER_COUNT,
)


ScriptGenerationStatus = Literal["ok", "failed"]
LLMProvider = Literal["openai", "gemini", "lmstudio"]


class ScriptGenerationRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class ScriptStyle(BaseModel):
    model_config = ConfigDict(extra="allow")

    audience: str
    tone: str
    avoid: list[str]

    @field_validator("audience", "tone")
    @classmethod
    def style_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("script_style audience and tone must not be empty")
        return value

    @field_validator("avoid")
    @classmethod
    def avoid_items_must_be_strings(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]


class SourcePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_selected_stories_only: bool
    include_full_records: bool

    @model_validator(mode="after")
    def only_full_selected_story_records_are_supported(self) -> "SourcePolicy":
        if not self.use_selected_stories_only:
            raise ValueError("source_policy.use_selected_stories_only must be true for roundup script generation")
        if not self.include_full_records:
            raise ValueError("source_policy.include_full_records must be true for the first roundup script app")
        return self


class ReflectionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = DEFAULT_REFLECTION_ENABLED
    max_revision_passes: int = DEFAULT_MAX_REVISION_PASSES
    target_score: int = DEFAULT_REFLECTION_TARGET_SCORE

    @field_validator("max_revision_passes")
    @classmethod
    def revision_passes_must_be_bounded(cls, value: int) -> int:
        if value < 0:
            raise ValueError("reflection.max_revision_passes must be non-negative")
        if value > 3:
            raise ValueError("reflection.max_revision_passes should stay <= 3 for notebook runs")
        return value

    @field_validator("target_score")
    @classmethod
    def target_score_must_be_valid(cls, value: int) -> int:
        if value < 1 or value > 10:
            raise ValueError("reflection.target_score must be between 1 and 10")
        return value


class RoundupScriptConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: LLMProvider
    model: str
    base_url: str | None = None
    prompt_version: str
    temperature: float
    words_per_minute: int
    duration_tolerance_seconds: int
    worker_count: int = DEFAULT_SCRIPT_WORKER_COUNT
    script_style: ScriptStyle
    source_policy: SourcePolicy
    reflection: ReflectionConfig = Field(default_factory=ReflectionConfig)

    @field_validator("model", "prompt_version")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("script config model and prompt_version must not be empty")
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("config.temperature must be between 0 and 2")
        return value

    @field_validator("words_per_minute", "worker_count")
    @classmethod
    def positive_int_fields(cls, value: int) -> int:
        if value < 1:
            raise ValueError("config.words_per_minute and worker_count must be at least 1")
        return value

    @field_validator("duration_tolerance_seconds")
    @classmethod
    def duration_tolerance_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("config.duration_tolerance_seconds must be non-negative")
        return value


class VideoPacket(BaseModel):
    model_config = ConfigDict(extra="allow")

    packet_type: str
    selected_format: str
    script_app: str
    target_duration_seconds: int
    intro_seconds: int
    closing_seconds: int
    segment_seconds: int | None = None
    story_count: int | None = None
    selected_story_ids: list[str] = Field(default_factory=list)
    stories: list[dict[str, Any]]
    format_contract: dict[str, Any] = Field(default_factory=dict)

    @field_validator("packet_type", "selected_format", "script_app")
    @classmethod
    def packet_text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("video_packet packet_type, selected_format, and script_app must not be empty")
        return value

    @field_validator("target_duration_seconds")
    @classmethod
    def target_duration_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("video_packet.target_duration_seconds must be positive")
        return value

    @field_validator("intro_seconds", "closing_seconds")
    @classmethod
    def bookend_seconds_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("video_packet intro_seconds and closing_seconds must be non-negative")
        return value


class VideoPackagingData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    selected_format: str
    script_app: str
    video_packet: VideoPacket


class VideoPackagingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: VideoPackagingData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class ScriptGenerationInput(BaseModel):
    video_packaging: VideoPackagingEnvelope


class ScriptGenerationRequest(BaseModel):
    run: ScriptGenerationRun
    config: RoundupScriptConfig
    input: ScriptGenerationInput


class ScriptGenerationData(BaseModel):
    run_id: str
    generated_at: str
    selected_format: str
    script_package: dict[str, Any]


class ScriptGenerationSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    section_count: int
    story_section_count: int
    total_word_count: int
    estimated_duration_seconds: float
    llm_call_count: int
    failure_reason: str = ""


class ScriptGenerationHandoff(BaseModel):
    ready_for_verification: bool


class ScriptGenerationResponse(BaseModel):
    status: ScriptGenerationStatus
    data: ScriptGenerationData
    summary: ScriptGenerationSummary
    handoff: ScriptGenerationHandoff
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
