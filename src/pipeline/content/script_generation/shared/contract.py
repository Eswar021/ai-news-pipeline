"""Format-agnostic script-generation contract.

The config sub-models, the video-packaging input envelope, and the output
(beat/section/audio/checks) contracts are shared by every format. Each format
defines only its own ScriptConfig/ScriptPackage/Request/Response wrappers.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .defaults import (
    DEFAULT_DIAGNOSTIC_WORDS_PER_MINUTE,
    DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_LLM_RETRY_ENABLED,
    DEFAULT_LLM_RETRY_INITIAL_DELAY_SECONDS,
    DEFAULT_LLM_RETRY_MAX_ATTEMPTS,
    DEFAULT_LLM_RETRY_MAX_DELAY_SECONDS,
    DEFAULT_LLM_RETRY_MAX_STRUCTURED_OUTPUT_ATTEMPTS,
    DEFAULT_MAX_EPISODE_CONTEXT_CHARS,
    DEFAULT_MAX_REVISION_PASSES,
    DEFAULT_MAX_STORY_CONTEXT_CHARS,
    DEFAULT_REVIEW_ENABLED,
    DEFAULT_SCRIPT_WORKER_COUNT,
    DEFAULT_TITLE_CARD_SECONDS,
)


ScriptGenerationStatus = Literal["ok", "failed"]
LLMProvider = Literal["openai", "gemini", "lmstudio", "moonshot", "deepseek"]
ScriptLLMRole = Literal[
    "source_researcher",
    "director",
    "story_writer",
    "story_reviewer",
    "bookend_writer",
    "bookend_reviewer",
]


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


class OpinionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_first_person_editorial_opinion: bool = True
    forbid_fabricated_personal_experience: bool = True


class HumorPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    modes: list[str] = Field(default_factory=lambda: ["observational", "dry", "self_aware", "absurd_analogy"])
    density: Literal["none", "restrained", "moderate"] = "restrained"
    allow_callbacks: bool = True
    avoid: list[str] = Field(default_factory=lambda: ["forced meme references", "cruelty", "unsupported accusations"])


class LanguagePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefer: list[str] = Field(
        default_factory=lambda: ["concrete verbs", "varied sentence length", "plain-language mental models"]
    )
    avoid: list[str] = Field(
        default_factory=lambda: [
            "corporate press-release language",
            "generic importance claims",
            "article-summary transitions",
        ]
    )
    profanity_mode: Literal["avoid", "allow"] = "avoid"
    profanity_terms: list[str] = Field(default_factory=lambda: ["fuck", "fucking", "shit", "bullshit"])

    @field_validator("profanity_terms")
    @classmethod
    def profanity_terms_must_be_strings(cls, value: list[str]) -> list[str]:
        return list(
            dict.fromkeys(
                item.strip().casefold()
                for item in value
                if isinstance(item, str) and item.strip()
            )
        )


class ChannelVoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: str = "curious technical friend with a skeptical eyebrow"
    worldview: list[str] = Field(
        default_factory=lambda: [
            "optimistic about useful progress",
            "skeptical of marketing",
            "practical consequences over abstract importance",
        ]
    )
    energy: str = "energetic but not frantic"
    opinion: OpinionPolicy = Field(default_factory=OpinionPolicy)
    humor: HumorPolicy = Field(default_factory=HumorPolicy)
    language: LanguagePolicy = Field(default_factory=LanguagePolicy)

    @field_validator("persona", "energy")
    @classmethod
    def voice_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("channel_voice persona and energy must not be empty")
        return value.strip()


class StorytellingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_story_engine: bool = True
    require_viewer_payoff: bool = True
    allow_optional_truth_details: bool = True
    forbid_source_order_summary: bool = True
    max_must_communicate_truth_items: int = 4
    max_optional_truth_items: int = 10

    @field_validator("max_must_communicate_truth_items", "max_optional_truth_items")
    @classmethod
    def truth_selection_limits_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 20:
            raise ValueError("storytelling truth selection limits must be between 1 and 20")
        return value


class SourceContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_brief_max_attempts: int | None = Field(
        default=None,
        exclude=True,
        description="Deprecated frozen-run compatibility field; semantic source content is not code-retried.",
    )
    max_story_context_chars: int = DEFAULT_MAX_STORY_CONTEXT_CHARS
    max_episode_context_chars: int = DEFAULT_MAX_EPISODE_CONTEXT_CHARS

    @field_validator("max_story_context_chars", "max_episode_context_chars")
    @classmethod
    def context_limits_must_be_positive(cls, value: int) -> int:
        if value < 10_000:
            raise ValueError("source context resource limits must be at least 10000 characters")
        return value

    @model_validator(mode="after")
    def episode_limit_must_fit_at_least_one_story(self) -> "SourceContextConfig":
        if self.max_episode_context_chars < self.max_story_context_chars:
            raise ValueError("source_context.max_episode_context_chars must be >= max_story_context_chars")
        return self


class SourcePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_selected_stories_only: bool
    include_full_records: bool

    @model_validator(mode="after")
    def only_full_selected_story_records_are_supported(self) -> "SourcePolicy":
        if not self.use_selected_stories_only:
            raise ValueError("source_policy.use_selected_stories_only must be true for script generation")
        if not self.include_full_records:
            raise ValueError("source_policy.include_full_records must be true for script generation")
        return self


class LLMRetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = DEFAULT_LLM_RETRY_ENABLED
    max_attempts: int = DEFAULT_LLM_RETRY_MAX_ATTEMPTS
    max_structured_output_attempts: int = DEFAULT_LLM_RETRY_MAX_STRUCTURED_OUTPUT_ATTEMPTS
    initial_delay_seconds: float = DEFAULT_LLM_RETRY_INITIAL_DELAY_SECONDS
    max_delay_seconds: float = DEFAULT_LLM_RETRY_MAX_DELAY_SECONDS

    @model_validator(mode="after")
    def retry_policy_must_be_bounded(self) -> "LLMRetryConfig":
        if self.max_attempts < 1 or self.max_attempts > 8:
            raise ValueError("llm_retry.max_attempts must be between 1 and 8")
        if self.max_structured_output_attempts < 1 or self.max_structured_output_attempts > 3:
            raise ValueError("llm_retry.max_structured_output_attempts must be between 1 and 3")
        if self.initial_delay_seconds < 0.1 or self.initial_delay_seconds > 30:
            raise ValueError("llm_retry.initial_delay_seconds must be between 0.1 and 30")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("llm_retry.max_delay_seconds must be >= initial_delay_seconds")
        if self.max_delay_seconds > 120:
            raise ValueError("llm_retry.max_delay_seconds must be <= 120")
        return self


class SectionWritingGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_words: int | None = None
    beat_guidance: str
    editorial_goal: str

    @field_validator("suggested_words")
    @classmethod
    def suggested_words_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("writing_guidance suggested_words must be positive when provided")
        return value


class ReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = DEFAULT_REVIEW_ENABLED
    max_revision_passes: int = DEFAULT_MAX_REVISION_PASSES
    quality_criteria: list[str] = Field(
        default_factory=lambda: [
            "clear spoken explanation",
            "strong viewer value",
            "natural YouTube pacing",
            "no repetition or filler",
            "no hype or fake certainty",
        ]
    )

    @field_validator("max_revision_passes")
    @classmethod
    def revision_passes_must_be_bounded(cls, value: int) -> int:
        if value < 0:
            raise ValueError("review.max_revision_passes must be non-negative")
        if value > 1:
            raise ValueError("review.max_revision_passes must be <= 1")
        return value

    @field_validator("quality_criteria")
    @classmethod
    def quality_criteria_must_not_be_empty(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if not cleaned:
            raise ValueError("review.quality_criteria must contain at least one criterion")
        return cleaned


class ProviderOptions(BaseModel):
    model_config = ConfigDict(extra="allow")

    thinking: Literal["enabled", "disabled"] | None = None
    omit_temperature: bool = False
    request_timeout_seconds: float = Field(
        default=DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS,
        ge=10.0,
        le=1800.0,
    )


class StructuredOutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["json_schema", "function_calling", "json_mode"] = "json_schema"
    strict: bool = True


class ContentFilterFallbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: LLMProvider
    model: str
    temperature: float
    base_url: str | None = None
    provider_options: ProviderOptions = Field(default_factory=ProviderOptions)
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)
    llm_retry: LLMRetryConfig | None = None

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


class RoleLLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: LLMProvider
    model: str
    temperature: float
    base_url: str | None = None
    provider_options: ProviderOptions = Field(default_factory=ProviderOptions)
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)
    llm_retry: LLMRetryConfig | None = None
    content_filter_fallback: ContentFilterFallbackConfig | None = None

    @field_validator("model")
    @classmethod
    def role_model_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("llm_roles model must not be empty")
        return value.strip()

    @field_validator("temperature")
    @classmethod
    def role_temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("llm_roles temperature must be between 0 and 2")
        return value


class BaseScriptConfig(BaseModel):
    """Shared script-generation config. Formats subclass this (adding nothing, or
    format-specific extras) so each has a distinct type while sharing all fields.
    Note: `writing_guidance` is intentionally absent here — its section shape is
    format-specific; each format's config declares its own."""

    model_config = ConfigDict(extra="allow")

    provider: LLMProvider
    model: str
    base_url: str | None = None
    provider_options: ProviderOptions = Field(default_factory=ProviderOptions)
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)
    # Role keys are format-specific (roundup: story_writer/…; deep_dive:
    # section_writer/…). Each format's SCRIPT_LLM_ROLES tuple is the source of
    # truth at resolution, so the key type stays a generic string here.
    llm_roles: dict[str, RoleLLMConfig] = Field(default_factory=dict)
    prompt_version: str
    temperature: float
    diagnostic_words_per_minute: int = DEFAULT_DIAGNOSTIC_WORDS_PER_MINUTE
    worker_count: int = DEFAULT_SCRIPT_WORKER_COUNT
    title_card_seconds: float = DEFAULT_TITLE_CARD_SECONDS
    llm_retry: LLMRetryConfig = Field(default_factory=LLMRetryConfig)
    script_style: ScriptStyle
    channel_voice: ChannelVoiceConfig = Field(default_factory=ChannelVoiceConfig)
    storytelling: StorytellingConfig = Field(default_factory=StorytellingConfig)
    source_context: SourceContextConfig = Field(default_factory=SourceContextConfig)
    source_policy: SourcePolicy
    review: ReviewConfig = Field(default_factory=ReviewConfig)

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

    @field_validator("diagnostic_words_per_minute", "worker_count")
    @classmethod
    def positive_int_fields(cls, value: int) -> int:
        if value < 1:
            raise ValueError("config.diagnostic_words_per_minute and worker_count must be at least 1")
        return value

    @field_validator("title_card_seconds")
    @classmethod
    def title_card_seconds_must_be_bounded(cls, value: float) -> float:
        if value < 1.5 or value > 5:
            raise ValueError("config.title_card_seconds must be between 1.5 and 5 seconds")
        return value


class VideoPacket(BaseModel):
    model_config = ConfigDict(extra="allow")

    packet_type: str
    selected_format: str
    script_app: str
    duration_policy: dict[str, Any] = Field(default_factory=dict)
    target_duration_seconds: int | None = None
    intro_seconds: int | None = None
    closing_seconds: int | None = None
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

    @field_validator("target_duration_seconds", "intro_seconds", "closing_seconds", "segment_seconds")
    @classmethod
    def legacy_timing_fields_must_not_be_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("legacy video-packet timing fields must not be negative")
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


class DeliveryDirectionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    performance_intent: str = "Deliver this beat naturally and make its purpose clear."
    emotional_color: str = "engaged"
    pace: Literal["deliberate", "measured", "conversational", "brisk", "rapid"] = "conversational"
    energy: Literal["restrained", "warm", "engaged", "animated", "punchy"] = "engaged"
    emphasis_phrases: list[str] = Field(default_factory=list)
    pause_after: Literal["none", "micro", "short", "full_beat"] = "none"


class ScriptBeatContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    beat_order: int
    beat_type: Literal[
        "hook",
        "transition",
        "what_changed",
        "explanation",
        "example",
        "why_it_matters",
        "caveat",
        "takeaway",
        "intro",
        "conclusion",
    ]
    beat_function: Literal[
        "episode_hook",
        "episode_setup",
        "story_hook",
        "setup",
        "reveal",
        "explanation",
        "example",
        "reaction",
        "comic_release",
        "consequence",
        "caveat",
        "payoff",
        "bridge",
        "episode_payoff",
    ] = "explanation"
    story_id: str = ""
    narration_text: str
    word_count: int
    estimated_seconds: float
    source_record_keys: list[str] = Field(default_factory=list)
    support_truth_ids: list[str] = Field(default_factory=list)
    support_alignment: Literal["explicit", "unresolved", "not_applicable"] = "not_applicable"
    creative_device: Literal[
        "none",
        "analogy",
        "contrast",
        "rhetorical_question",
        "hypothetical",
        "observational_humor",
        "self_aware_humor",
        "callback",
    ] = "none"
    delivery_direction: DeliveryDirectionContract = Field(default_factory=DeliveryDirectionContract)

    @field_validator("beat_id", "narration_text")
    @classmethod
    def beat_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("script beat IDs and narration must not be empty")
        return value


class StoryTitleCardContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_title: str
    subtitle: str = ""
    duration_seconds: float
    voice_behavior: Literal["continue"]
    anchor_beat_id: str


class ScriptSectionContract(BaseModel):
    model_config = ConfigDict(extra="allow")

    section_id: str
    section_type: Literal["intro", "story", "closing"]
    section_order: int
    story_id: str = ""
    story_title: str = ""
    role: str = ""
    target_seconds: int | None = None
    word_budget: int | None = None
    title_card: StoryTitleCardContract | None = None
    beats: list[ScriptBeatContract]
    narration_text: str
    word_count: int
    estimated_seconds: float
    used_story_ids: list[str] = Field(default_factory=list)
    used_source_record_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def story_sections_require_title_cards(self) -> "ScriptSectionContract":
        if not self.beats:
            raise ValueError(f"{self.section_id} must contain script beats")
        if self.section_type == "story" and self.title_card is None:
            raise ValueError(f"{self.section_id} must contain a story title-card contract")
        if self.section_type != "story" and self.title_card is not None:
            raise ValueError(f"{self.section_id} must not contain a story title-card contract")
        return self


class FullScriptStatsContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_word_count: int
    estimated_duration_seconds: float
    section_order: list[str]
    beat_count: int


class ScriptAudioUnitContract(BaseModel):
    model_config = ConfigDict(extra="allow")

    audio_unit_id: str
    section_id: str
    section_type: Literal["intro", "story", "closing"]
    story_id: str = ""
    story_title: str = ""
    narration_text: str = ""
    beat_ids: list[str]


class ScriptAudioPlanContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_strategy: Literal["one_audio_unit_per_section_with_beat_anchors"]
    units: list[ScriptAudioUnitContract]


class ScriptChecksContract(BaseModel):
    model_config = ConfigDict(extra="allow")

    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ScriptGenerationSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    section_count: int
    story_section_count: int
    total_word_count: int
    estimated_duration_seconds: float
    llm_call_count: int
    failure_reason: str = ""


class ScriptGenerationHandoff(BaseModel):
    ready_for_metadata_creation: bool
    ready_for_voiceover: bool
