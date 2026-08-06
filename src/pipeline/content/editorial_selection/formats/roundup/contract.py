from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.pipeline.llm import LLMProvider

from .config import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CALL_CONTEXT_CHARS,
    DEFAULT_MAX_CALL_CONTEXT_TOKENS,
    DEFAULT_MAX_CANDIDATE_STORIES,
    DEFAULT_MAX_SCREENING_ROUNDS,
    DEFAULT_MAX_STORY_CONTEXT_CHARS,
    DEFAULT_MAX_STORY_CONTEXT_TOKENS,
    DEFAULT_SCREENING_SHORTLIST_PER_BATCH,
    DEFAULT_SLATE_REVIEW_MAX_ATTEMPTS,
    DEFAULT_SLATE_REVIEW_RECOVERY_CANDIDATE_COUNT,
    DEFAULT_TARGET_FINALIST_STORIES,
    DEFAULT_TOKENIZER_ENCODING,
)


SelectionStatus = Literal["ok", "failed"]
StoryRole = Literal["lead", "major", "brief"]


class EditorialSelectionRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class ChannelContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    channel_name: str
    content_promise: str = ""
    audience: str = "AI-curious professionals"

    @field_validator("channel_name")
    @classmethod
    def channel_name_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.channel.channel_name must not be empty")
        return value


class SlateReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: LLMProvider | None = None
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    prompt_version: str = "v1"
    max_attempts: int = DEFAULT_SLATE_REVIEW_MAX_ATTEMPTS
    recovery_candidate_count: int = DEFAULT_SLATE_REVIEW_RECOVERY_CANDIDATE_COUNT
    duplicate_audit_enabled: bool = False
    duplicate_audit_prompt_version: str = "v1"

    @field_validator("prompt_version", "duplicate_audit_prompt_version")
    @classmethod
    def prompt_version_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.slate_review prompt versions must not be empty")
        return value

    @field_validator("model")
    @classmethod
    def model_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("config.slate_review.model must not be empty when provided")
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float | None) -> float | None:
        if value is not None and (value < 0 or value > 2):
            raise ValueError("config.slate_review.temperature must be between 0 and 2")
        return value

    @field_validator("max_attempts")
    @classmethod
    def attempts_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("config.slate_review.max_attempts must be between 1 and 5")
        return value

    @field_validator("recovery_candidate_count")
    @classmethod
    def recovery_count_must_be_bounded(cls, value: int) -> int:
        if value < 0 or value > 20:
            raise ValueError(
                "config.slate_review.recovery_candidate_count must be between 0 and 20"
            )
        return value


class RoundupEditorialSelectionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    target_format: Literal["roundup"] = "roundup"
    provider: LLMProvider
    model: str
    base_url: str | None = None
    prompt_version: str = "v1"
    temperature: float = 0.2
    min_stories: int = 3
    max_stories: int = 5
    max_candidate_stories: int = DEFAULT_MAX_CANDIDATE_STORIES
    screening_shortlist_per_batch: int = DEFAULT_SCREENING_SHORTLIST_PER_BATCH
    target_finalist_stories: int | None = DEFAULT_TARGET_FINALIST_STORIES
    max_screening_rounds: int = DEFAULT_MAX_SCREENING_ROUNDS
    max_story_context_chars: int = DEFAULT_MAX_STORY_CONTEXT_CHARS
    max_call_context_chars: int = DEFAULT_MAX_CALL_CONTEXT_CHARS
    max_story_context_tokens: int = DEFAULT_MAX_STORY_CONTEXT_TOKENS
    max_call_context_tokens: int = DEFAULT_MAX_CALL_CONTEXT_TOKENS
    tokenizer_encoding: str = DEFAULT_TOKENIZER_ENCODING
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    channel: ChannelContext
    slate_review: SlateReviewConfig = Field(default_factory=SlateReviewConfig)

    @field_validator("model", "prompt_version", "tokenizer_encoding")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "config model, prompt_version, and tokenizer_encoding must not be empty"
            )
        return value

    @field_validator(
        "min_stories",
        "max_stories",
        "max_candidate_stories",
        "screening_shortlist_per_batch",
        "max_screening_rounds",
        "max_story_context_chars",
        "max_call_context_chars",
        "max_story_context_tokens",
        "max_call_context_tokens",
        "max_attempts",
    )
    @classmethod
    def positive_values(cls, value: int) -> int:
        if value < 1:
            raise ValueError("editorial selection limits must be positive")
        return value

    @field_validator("target_finalist_stories")
    @classmethod
    def finalist_target_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("config.target_finalist_stories must be positive")
        return value

    @field_validator("max_attempts")
    @classmethod
    def attempts_must_be_bounded(cls, value: int) -> int:
        if value > 5:
            raise ValueError("config.max_attempts must be at most 5")
        return value

    @field_validator("max_screening_rounds")
    @classmethod
    def screening_rounds_must_be_bounded(cls, value: int) -> int:
        if value > 8:
            raise ValueError("config.max_screening_rounds must be at most 8")
        return value

    @field_validator("max_story_context_chars", "max_call_context_chars")
    @classmethod
    def context_limits_must_be_bounded(cls, value: int) -> int:
        if value < 10_000 or value > 2_000_000:
            raise ValueError(
                "editorial selection context limits must be between 10000 and 2000000"
            )
        return value

    @field_validator("max_story_context_tokens", "max_call_context_tokens")
    @classmethod
    def token_limits_must_be_bounded(cls, value: int) -> int:
        if value < 1_000 or value > 2_000_000:
            raise ValueError(
                "editorial selection token limits must be between 1000 and 2000000"
            )
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("config.temperature must be between 0 and 2")
        return value

    @model_validator(mode="after")
    def validate_bounds(self) -> "RoundupEditorialSelectionConfig":
        if self.min_stories > self.max_stories:
            raise ValueError("config.min_stories must be <= config.max_stories")
        if self.max_candidate_stories < self.max_stories:
            raise ValueError("config.max_candidate_stories must be >= config.max_stories")
        if (
            self.target_finalist_stories is not None
            and self.target_finalist_stories < self.max_stories
        ):
            raise ValueError(
                "config.target_finalist_stories must be >= config.max_stories"
            )
        if (
            self.target_finalist_stories is not None
            and self.target_finalist_stories > self.max_candidate_stories
        ):
            raise ValueError(
                "config.target_finalist_stories must be <= config.max_candidate_stories"
            )
        if self.screening_shortlist_per_batch < self.max_stories:
            raise ValueError(
                "config.screening_shortlist_per_batch must be >= config.max_stories"
            )
        if self.screening_shortlist_per_batch >= self.max_candidate_stories:
            raise ValueError(
                "config.screening_shortlist_per_batch must be < config.max_candidate_stories"
            )
        if self.max_call_context_chars < self.max_story_context_chars:
            raise ValueError(
                "config.max_call_context_chars must be >= max_story_context_chars"
            )
        if self.max_call_context_tokens < self.max_story_context_tokens:
            raise ValueError(
                "config.max_call_context_tokens must be >= max_story_context_tokens"
            )
        return self


class StoryMappingData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    stories: list[dict[str, Any]]


class StoryMappingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: StoryMappingData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class EditorialSelectionInput(BaseModel):
    story_mapping: StoryMappingEnvelope


class EditorialSelectionRequest(BaseModel):
    run: EditorialSelectionRun
    config: RoundupEditorialSelectionConfig
    input: EditorialSelectionInput


class SelectedStoryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    role: StoryRole
    selection_reason: str
    viewer_payoff: str
    confidence: float = Field(ge=0, le=1)


class NonSelectedStoryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    action: Literal["reserve", "reject"]
    reason: str
    confidence: float = Field(ge=0, le=1)


class RoundupSlateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_shape: Literal["cohesive_theme", "mixed_news_roundup"]
    episode_thesis: str = Field(
        description="A truthful shared thesis, or an empty string for a heterogeneous roundup."
    )
    ordering_rationale: str
    selected: list[SelectedStoryDraft]
    non_selected: list[NonSelectedStoryDraft]
    human_review_warning: str = ""


class DuplicateStoryGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_ids: list[str] = Field(min_length=2)
    relationship: Literal[
        "same_event",
        "same_editorial_story",
        "immediate_follow_up",
    ]
    reason: str


class DuplicateAuditStoryAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    event_summary: str
    duplicate_group_id: str
    reason: str


class FocusedDuplicateStoryGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    story_ids: list[str] = Field(min_length=2)
    relationship: Literal[
        "same_event",
        "same_editorial_story",
        "immediate_follow_up",
    ]
    preferred_story_id: str
    reason: str


class RoundupDuplicateAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessments: list[DuplicateAuditStoryAssessment]
    duplicate_story_groups: list[FocusedDuplicateStoryGroup]
    audit_summary: str


class RoundupSlateReviewDraft(RoundupSlateDraft):
    review_changed: bool
    review_reason: str
    diversity_assessment: Literal["strong", "acceptable", "repetitive"] = "acceptable"
    diversity_reason: str = ""
    duplicate_story_groups: list[DuplicateStoryGroup] = Field(default_factory=list)


class CandidateScreenDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    action: Literal["shortlist"]
    reason: str
    confidence: float = Field(ge=0, le=1)


class CandidateScreenDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[CandidateScreenDecision]


class EditorialSelectionData(BaseModel):
    run_id: str
    generated_at: str
    selected_format: Literal["roundup"]
    editorial_slate: dict[str, Any]


class EditorialSelectionSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_story_count: int
    evaluated_story_count: int
    selected_story_count: int
    reserve_story_count: int
    rejected_story_count: int
    llm_call_count: int
    failure_reason: str = ""


class EditorialSelectionHandoff(BaseModel):
    ready_for_video_packaging: bool
    selected_format: Literal["roundup"]


class EditorialSelectionResponse(BaseModel):
    status: SelectionStatus
    data: EditorialSelectionData
    summary: EditorialSelectionSummary
    handoff: EditorialSelectionHandoff
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
