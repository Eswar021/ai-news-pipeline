from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_MAX_RECORDS_PER_STORY_LABEL,
    DEFAULT_SEMANTIC_MERGE_GROUPS,
    DEFAULT_SEMANTIC_PRIMARY_THRESHOLD,
    DEFAULT_SEMANTIC_SUPPORTED_THRESHOLD,
    DEFAULT_SEMANTIC_TITLE_ANCHOR_THRESHOLD,
    DEFAULT_STORY_LABEL_PROMPT_VERSION,
    DEFAULT_STORY_LABEL_TEMPERATURE,
    DEFAULT_STORY_LABEL_WORKER_COUNT,
)
from .utils import parse_datetime


StoryMappingStatus = Literal["ok", "failed"]


class StoryMappingRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class CollectionWindow(BaseModel):
    model_config = ConfigDict(extra="allow")

    start: str
    end: str
    lookback_hours: int | float

    @field_validator("start", "end")
    @classmethod
    def endpoint_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.collection_window start/end must not be empty")
        return value

    @field_validator("lookback_hours")
    @classmethod
    def lookback_must_be_positive(cls, value: int | float) -> int | float:
        if value <= 0:
            raise ValueError("config.collection_window.lookback_hours must be positive")
        return value

    @model_validator(mode="after")
    def window_must_parse_and_be_ordered(self) -> "CollectionWindow":
        start = parse_datetime(self.start)
        end = parse_datetime(self.end)
        if start is None:
            raise ValueError("config.collection_window.start must be a valid datetime")
        if end is None:
            raise ValueError("config.collection_window.end must be a valid datetime")
        if start > end:
            raise ValueError("config.collection_window.start must be before end")
        return self


class ClusteringConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    max_pair_hours: float | None = None
    semantic_primary_threshold: float = DEFAULT_SEMANTIC_PRIMARY_THRESHOLD
    semantic_supported_threshold: float = DEFAULT_SEMANTIC_SUPPORTED_THRESHOLD
    semantic_title_anchor_threshold: float = DEFAULT_SEMANTIC_TITLE_ANCHOR_THRESHOLD
    semantic_merge_groups: list[str] = Field(default_factory=lambda: list(DEFAULT_SEMANTIC_MERGE_GROUPS))

    @field_validator(
        "semantic_primary_threshold",
        "semantic_supported_threshold",
        "semantic_title_anchor_threshold",
    )
    @classmethod
    def threshold_must_be_probability(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("semantic thresholds must be between 0 and 1")
        return value

    @field_validator("max_pair_hours")
    @classmethod
    def max_pair_hours_must_be_positive(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("config.clustering.max_pair_hours must be positive when provided")
        return value

    @field_validator("semantic_merge_groups")
    @classmethod
    def merge_groups_must_be_non_empty_strings(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("config.clustering.semantic_merge_groups must not be empty")
        for group in value:
            if not isinstance(group, str) or not group.strip():
                raise ValueError("config.clustering.semantic_merge_groups must contain non-empty strings")
        return value


class StoryLabelConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    provider: Literal["openai", "gemini", "lmstudio"] = "openai"
    base_url: str | None = None
    prompt_version: str = DEFAULT_STORY_LABEL_PROMPT_VERSION
    worker_count: int = DEFAULT_STORY_LABEL_WORKER_COUNT
    temperature: float = DEFAULT_STORY_LABEL_TEMPERATURE
    max_records_per_story: int = DEFAULT_MAX_RECORDS_PER_STORY_LABEL

    @field_validator("model", "prompt_version")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("story_label model and prompt_version must not be empty")
        return value

    @field_validator("worker_count", "max_records_per_story")
    @classmethod
    def positive_int_fields(cls, value: int) -> int:
        if value < 1:
            raise ValueError("story_label worker_count and max_records_per_story must be at least 1")
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("story_label.temperature must be between 0 and 2")
        return value


class StoryMappingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    embedding_model: str
    collection_window: CollectionWindow
    use_llm_story_labels: bool
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    story_label: StoryLabelConfig | None = None

    @field_validator("embedding_model")
    @classmethod
    def embedding_model_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.embedding_model must not be empty")
        return value

    @model_validator(mode="after")
    def validate_story_label_config(self) -> "StoryMappingConfig":
        if self.use_llm_story_labels and self.story_label is None:
            raise ValueError("config.story_label is required when use_llm_story_labels is true")
        return self


class EvidencePrepData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    record_count: int | None = None
    records: list[dict[str, Any]]


class EvidencePrepEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: EvidencePrepData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class StoryMappingInput(BaseModel):
    evidence_prep: EvidencePrepEnvelope


class StoryMappingRequest(BaseModel):
    run: StoryMappingRun
    config: StoryMappingConfig
    input: StoryMappingInput


class StoryMappingData(BaseModel):
    run_id: str
    generated_at: str
    story_count: int
    stories: list[dict[str, Any]]


class StoryMappingSummary(BaseModel):
    run_id: str
    generated_at: str
    status: StoryMappingStatus
    input_record_count: int
    story_count: int
    single_record_story_count: int
    multi_record_story_count: int
    semantic_merge_count: int
    dropped_singleton_count: int
    effective_max_pair_hours: float
    priority_bucket_counts: dict[str, int]
    source_group_mix: dict[str, int]
    llm_runtime: dict[str, Any]
    top_story_quality_flags: dict[str, int]
    top_stories: list[dict[str, Any]]


class StoryMappingHandoff(BaseModel):
    story_count: int
    ready_for_fact_packet: bool


class StoryMappingResponse(BaseModel):
    status: StoryMappingStatus
    data: StoryMappingData
    summary: StoryMappingSummary
    handoff: StoryMappingHandoff
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
