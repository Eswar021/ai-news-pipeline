from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_BATCH_CONTEXT_CHARS,
    DEFAULT_MAX_RECORD_CONTEXT_CHARS,
)


TriageStatus = Literal["ok", "partial", "failed"]
LLMProvider = Literal["openai", "gemini", "lmstudio"]
TriageAction = Literal["advance", "reserve", "quarantine"]
TriageMode = Literal["authoritative"]


class EditorialTriageRun(BaseModel):
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
    allowed_topics: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)

    @field_validator("channel_name")
    @classmethod
    def channel_name_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.channel.channel_name must not be empty")
        return value


class EditorialTriageConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    mode: TriageMode = "authoritative"
    provider: LLMProvider
    model: str
    base_url: str | None = None
    prompt_version: str = "v1"
    temperature: float = 0.1
    batch_size: int = DEFAULT_BATCH_SIZE
    max_record_context_chars: int = DEFAULT_MAX_RECORD_CONTEXT_CHARS
    max_batch_context_chars: int = DEFAULT_MAX_BATCH_CONTEXT_CHARS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    story_mapping_actions: list[TriageAction] = Field(
        default_factory=lambda: ["advance", "reserve"]
    )
    channel: ChannelContext

    @field_validator("model", "prompt_version")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config model and prompt_version must not be empty")
        return value

    @field_validator("batch_size")
    @classmethod
    def batch_size_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 30:
            raise ValueError("config.batch_size must be between 1 and 30")
        return value

    @field_validator("max_record_context_chars", "max_batch_context_chars")
    @classmethod
    def context_limits_must_be_bounded(cls, value: int) -> int:
        if value < 10_000 or value > 2_000_000:
            raise ValueError("editorial triage context limits must be between 10000 and 2000000")
        return value

    @model_validator(mode="after")
    def batch_context_must_fit_one_complete_record(self) -> "EditorialTriageConfig":
        if self.max_batch_context_chars < self.max_record_context_chars:
            raise ValueError(
                "config.max_batch_context_chars must be >= max_record_context_chars"
            )
        return self

    @field_validator("max_attempts")
    @classmethod
    def attempts_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("config.max_attempts must be between 1 and 5")
        return value

    @field_validator("story_mapping_actions")
    @classmethod
    def story_mapping_actions_must_be_useful(cls, value: list[TriageAction]) -> list[TriageAction]:
        actions = list(dict.fromkeys(value))
        if not actions:
            raise ValueError("config.story_mapping_actions must not be empty")
        if "quarantine" in actions:
            raise ValueError("config.story_mapping_actions cannot include quarantine")
        return actions

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("config.temperature must be between 0 and 2")
        return value


class EvidencePrepData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)


class EvidencePrepEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: EvidencePrepData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class NewsCollectionData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    candidate_ledger: list[dict[str, Any]] = Field(default_factory=list)


class NewsCollectionEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: NewsCollectionData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class EditorialTriageInput(BaseModel):
    evidence_prep: EvidencePrepEnvelope
    news_collection: NewsCollectionEnvelope | None = None


class EditorialTriageRequest(BaseModel):
    run: EditorialTriageRun
    config: EditorialTriageConfig
    input: EditorialTriageInput


class TriageDecisionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_key: str
    topic_relevance: Literal["high", "medium", "low", "none", "uncertain"]
    newsworthiness: Literal["high", "medium", "low", "uncertain"]
    audience_value: Literal["high", "medium", "low", "uncertain"]
    content_usability: Literal["strong", "usable", "weak", "unusable", "uncertain"]
    likely_content_type: Literal[
        "news_event",
        "product_release",
        "research",
        "tutorial",
        "analysis",
        "community_project",
        "opinion",
        "promotion_or_deal",
        "listing_or_navigation",
        "other",
    ]
    novelty: Literal["new", "follow_up", "evergreen", "duplicate_like", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    possible_story_keys: list[str]
    recommended_action: TriageAction


class TriageBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[TriageDecisionDraft]


class EditorialTriageData(BaseModel):
    run_id: str
    generated_at: str
    mode: TriageMode
    input_record_count: int
    decision_count: int
    decisions: list[dict[str, Any]]
    pools: dict[str, list[str]]


class EditorialTriageSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_record_count: int
    decision_count: int
    resolved_count: int
    unresolved_count: int
    action_counts: dict[str, int]
    batch_count: int
    failed_batch_count: int
    llm_call_count: int
    failure_reason: str = ""


class EditorialTriageHandoff(BaseModel):
    authoritative: bool
    ready_for_editorial_review: bool
    ready_for_story_mapping: bool


class EditorialTriageResponse(BaseModel):
    status: TriageStatus
    data: EditorialTriageData
    summary: EditorialTriageSummary
    handoff: EditorialTriageHandoff
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
