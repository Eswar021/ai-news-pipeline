from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import (
    DEFAULT_MAX_TAGS,
    DEFAULT_THUMBNAIL_TEXT_OPTION_COUNT,
    DEFAULT_TITLE_OPTION_COUNT,
)


MetadataStatus = Literal["ok", "failed"]
LLMProvider = Literal["openai", "gemini", "lmstudio"]


class MetadataRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class ChannelConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    channel_name: str
    content_promise: str = ""

    @field_validator("channel_name")
    @classmethod
    def channel_name_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.channel.channel_name must not be empty")
        return value


class MetadataPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    title_option_count: int = DEFAULT_TITLE_OPTION_COUNT
    thumbnail_text_option_count: int = DEFAULT_THUMBNAIL_TEXT_OPTION_COUNT
    max_tags: int = DEFAULT_MAX_TAGS
    include_source_urls: bool = True

    @field_validator("title_option_count")
    @classmethod
    def title_count_must_be_valid(cls, value: int) -> int:
        if value < 3 or value > 12:
            raise ValueError("metadata_policy.title_option_count must be between 3 and 12")
        return value

    @field_validator("thumbnail_text_option_count")
    @classmethod
    def thumbnail_count_must_be_valid(cls, value: int) -> int:
        if value < 3 or value > 8:
            raise ValueError("metadata_policy.thumbnail_text_option_count must be between 3 and 8")
        return value

    @field_validator("max_tags")
    @classmethod
    def max_tags_must_be_valid(cls, value: int) -> int:
        if value < 1 or value > 50:
            raise ValueError("metadata_policy.max_tags must be between 1 and 50")
        return value


class MemoryContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    recent_title_angles: list[Any] = Field(default_factory=list)


class MetadataConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: LLMProvider
    model: str
    base_url: str | None = None
    prompt_version: str
    temperature: float = 0.4
    channel: ChannelConfig
    metadata_policy: MetadataPolicy = Field(default_factory=MetadataPolicy)
    memory_context: MemoryContext = Field(default_factory=MemoryContext)

    @field_validator("model", "prompt_version")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config model and prompt_version must not be empty")
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("config.temperature must be between 0 and 2")
        return value


class ScriptGenerationData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    generated_at: str | None = None
    selected_format: str
    script_package: dict[str, Any]


class ScriptGenerationEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: ScriptGenerationData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VideoPackagingData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    generated_at: str | None = None
    selected_format: str
    script_app: str
    video_packet: dict[str, Any]


class VideoPackagingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: VideoPackagingData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class MetadataInput(BaseModel):
    script_generation: ScriptGenerationEnvelope
    video_packaging: VideoPackagingEnvelope


class MetadataRequest(BaseModel):
    run: MetadataRun
    config: MetadataConfig
    input: MetadataInput


class MetadataData(BaseModel):
    run_id: str
    generated_at: str
    selected_format: str
    metadata_package: dict[str, Any]


class MetadataSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    title_option_count: int
    thumbnail_option_count: int
    chapter_count: int
    tag_count: int
    source_url_count: int
    llm_call_count: int
    failure_reason: str = ""


class MetadataHandoff(BaseModel):
    ready_for_metadata_finalization: bool
    chapters_finalized: bool
    ready_for_media_production: bool


class MetadataResponse(BaseModel):
    status: MetadataStatus
    data: MetadataData
    summary: MetadataSummary
    handoff: MetadataHandoff
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
