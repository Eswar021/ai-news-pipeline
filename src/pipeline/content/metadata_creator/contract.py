from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_MAX_TAGS,
    DEFAULT_THUMBNAIL_TEXT_OPTION_COUNT,
    DEFAULT_TITLE_OPTION_COUNT,
)


MetadataStatus = Literal["ok", "failed"]
LLMProvider = Literal["openai", "gemini", "lmstudio", "moonshot"]


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
    chapter_title_max_chars: int = 64
    blocked_tags: list[str] = Field(default_factory=list)

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

    @field_validator("chapter_title_max_chars")
    @classmethod
    def chapter_title_limit_must_be_valid(cls, value: int) -> int:
        if value < 24 or value > 100:
            raise ValueError("metadata_policy.chapter_title_max_chars must be between 24 and 100")
        return value

    @field_validator("blocked_tags")
    @classmethod
    def policy_lists_must_contain_strings(cls, value: list[str]) -> list[str]:
        return list(
            dict.fromkeys(
                item.strip().casefold()
                for item in value
                if isinstance(item, str) and item.strip()
            )
        )


class MemoryContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    recent_title_angles: list[Any] = Field(default_factory=list)


class ProviderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thinking: Literal["enabled", "disabled"] | None = None
    omit_temperature: bool = False
    request_timeout_seconds: float = Field(default=300.0, ge=10.0, le=1800.0)


class StructuredOutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["json_schema", "function_calling", "json_mode"] = "json_schema"
    strict: bool = True


class MetadataLLMRetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_attempts: int = 2
    max_structured_output_attempts: int = 2
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 10.0

    @model_validator(mode="after")
    def retry_policy_must_be_bounded(self) -> "MetadataLLMRetryConfig":
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("llm_retry.max_attempts must be between 1 and 5")
        if self.max_structured_output_attempts < 1 or self.max_structured_output_attempts > 3:
            raise ValueError("llm_retry.max_structured_output_attempts must be between 1 and 3")
        if self.initial_delay_seconds < 0.1 or self.initial_delay_seconds > 30:
            raise ValueError("llm_retry.initial_delay_seconds must be between 0.1 and 30")
        if self.max_delay_seconds < self.initial_delay_seconds or self.max_delay_seconds > 120:
            raise ValueError("llm_retry.max_delay_seconds must be between initial_delay_seconds and 120")
        return self


class ContentFilterFallbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: LLMProvider
    model: str
    base_url: str | None = None
    provider_options: ProviderOptions = Field(default_factory=ProviderOptions)
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)
    llm_retry: MetadataLLMRetryConfig | None = None
    temperature: float = 0.4

    @field_validator("model")
    @classmethod
    def fallback_model_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content_filter_fallback model must not be empty")
        return value.strip()

    @field_validator("temperature")
    @classmethod
    def fallback_temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("content_filter_fallback temperature must be between 0 and 2")
        return value


class MetadataConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: LLMProvider
    model: str
    base_url: str | None = None
    provider_options: ProviderOptions = Field(default_factory=ProviderOptions)
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)
    llm_retry: MetadataLLMRetryConfig = Field(default_factory=MetadataLLMRetryConfig)
    content_filter_fallback: ContentFilterFallbackConfig | None = None
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
