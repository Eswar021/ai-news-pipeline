from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_CANDIDATE_NEIGHBORS_PER_RECORD,
    DEFAULT_CANDIDATE_SIMILARITY_FLOOR,
    DEFAULT_CLUSTER_RECONCILIATION_MAX_ATTEMPTS,
    DEFAULT_CLUSTER_RECONCILIATION_MAX_COMPONENT_CHARS,
    DEFAULT_CLUSTER_RECONCILIATION_MAX_COMPONENT_TOKENS,
    DEFAULT_CLUSTER_RECONCILIATION_PROMPT_VERSION,
    DEFAULT_CLUSTER_RECONCILIATION_TOKENIZER_ENCODING,
    DEFAULT_CLUSTER_RECONCILIATION_WORKER_COUNT,
    DEFAULT_EVENT_IDENTITY_MAX_ATTEMPTS,
    DEFAULT_EVENT_IDENTITY_MAX_RECORD_CHARS,
    DEFAULT_EVENT_IDENTITY_PROMPT_VERSION,
    DEFAULT_EVENT_IDENTITY_WORKER_COUNT,
    DEFAULT_FINGERPRINT_CHUNK_CHARS,
    DEFAULT_MAX_FINGERPRINT_CHUNKS_PER_RECORD,
    DEFAULT_MAX_STORY_LABEL_CONTEXT_CHARS,
    DEFAULT_MAX_CANDIDATE_PAIRS,
    DEFAULT_PAIR_ADJUDICATION_BATCH_SIZE,
    DEFAULT_PAIR_ADJUDICATION_MAX_ATTEMPTS,
    DEFAULT_PAIR_ADJUDICATION_MAX_BATCH_CHARS,
    DEFAULT_PAIR_ADJUDICATION_MAX_SINGLE_PAIR_CHARS,
    DEFAULT_PAIR_ADJUDICATION_WORKER_COUNT,
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
    candidate_neighbors_per_record: int = DEFAULT_CANDIDATE_NEIGHBORS_PER_RECORD
    candidate_similarity_floor: float = DEFAULT_CANDIDATE_SIMILARITY_FLOOR
    fingerprint_chunk_chars: int = DEFAULT_FINGERPRINT_CHUNK_CHARS
    max_fingerprint_chunks_per_record: int = DEFAULT_MAX_FINGERPRINT_CHUNKS_PER_RECORD
    max_candidate_pairs: int = DEFAULT_MAX_CANDIDATE_PAIRS
    event_identity: "EventIdentityConfig" = Field(
        default_factory=lambda: EventIdentityConfig()
    )
    pair_adjudication: "PairAdjudicationConfig" = Field(
        default_factory=lambda: PairAdjudicationConfig()
    )
    cluster_reconciliation: "ClusterReconciliationConfig" = Field(
        default_factory=lambda: ClusterReconciliationConfig()
    )

    @field_validator("candidate_neighbors_per_record")
    @classmethod
    def neighbor_count_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 40:
            raise ValueError("config.clustering.candidate_neighbors_per_record must be between 1 and 40")
        return value

    @field_validator("candidate_similarity_floor")
    @classmethod
    def similarity_floor_must_be_valid(cls, value: float) -> float:
        if value < -1 or value > 1:
            raise ValueError("config.clustering.candidate_similarity_floor must be between -1 and 1")
        return value

    @field_validator("fingerprint_chunk_chars")
    @classmethod
    def fingerprint_chunk_size_must_be_bounded(cls, value: int) -> int:
        if value < 500 or value > 8_000:
            raise ValueError("config.clustering.fingerprint_chunk_chars must be between 500 and 8000")
        return value

    @field_validator("max_fingerprint_chunks_per_record")
    @classmethod
    def fingerprint_chunk_limit_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 512:
            raise ValueError(
                "config.clustering.max_fingerprint_chunks_per_record must be between 1 and 512"
            )
        return value

    @field_validator("max_candidate_pairs")
    @classmethod
    def max_candidate_pairs_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 5000:
            raise ValueError("config.clustering.max_candidate_pairs must be between 1 and 5000")
        return value

    @field_validator("max_pair_hours")
    @classmethod
    def max_pair_hours_must_be_positive(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("config.clustering.max_pair_hours must be positive when provided")
        return value


class PairFullRecordReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "gemini", "lmstudio"] = "openai"
    model: str = "gpt-4o"
    base_url: str | None = None
    temperature: float = 0.0

    @field_validator("model")
    @classmethod
    def model_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pair_adjudication.full_record_review.model must not be empty")
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError(
                "pair_adjudication.full_record_review.temperature must be between 0 and 2"
            )
        return value


class PairAdjudicationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    provider: Literal["openai", "gemini", "lmstudio"] = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    prompt_version: str = "v1"
    temperature: float = 0.0
    batch_size: int = DEFAULT_PAIR_ADJUDICATION_BATCH_SIZE
    worker_count: int = DEFAULT_PAIR_ADJUDICATION_WORKER_COUNT
    max_attempts: int = DEFAULT_PAIR_ADJUDICATION_MAX_ATTEMPTS
    max_batch_chars: int = DEFAULT_PAIR_ADJUDICATION_MAX_BATCH_CHARS
    max_single_pair_chars: int = DEFAULT_PAIR_ADJUDICATION_MAX_SINGLE_PAIR_CHARS
    confirm_same_event_with_full_records: bool = True
    review_ambiguous_pairs_with_full_records: bool = True
    full_record_review_relationships: list[
        Literal["follow_up", "broader_story_arc", "uncertain"]
    ] = Field(default_factory=lambda: ["follow_up", "broader_story_arc", "uncertain"])
    full_record_review: PairFullRecordReviewConfig | None = None

    @field_validator("model", "prompt_version")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pair_adjudication model and prompt_version must not be empty")
        return value

    @field_validator("batch_size")
    @classmethod
    def batch_size_must_be_bounded(cls, value: int) -> int:
        if value != 1:
            raise ValueError(
                "pair_adjudication.batch_size must be 1 so each semantic judgment sees only one pair"
            )
        return value

    @field_validator("worker_count")
    @classmethod
    def worker_count_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 8:
            raise ValueError("pair_adjudication.worker_count must be between 1 and 8")
        return value

    @field_validator("max_attempts")
    @classmethod
    def attempts_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("pair_adjudication.max_attempts must be between 1 and 5")
        return value

    @field_validator("max_batch_chars", "max_single_pair_chars")
    @classmethod
    def context_char_limits_must_be_bounded(cls, value: int) -> int:
        if value < 10_000 or value > 500_000:
            raise ValueError("pair_adjudication context limits must be between 10000 and 500000")
        return value

    @model_validator(mode="after")
    def single_pair_limit_must_cover_batch_target(self):
        if self.max_single_pair_chars < self.max_batch_chars:
            raise ValueError("pair_adjudication.max_single_pair_chars must be >= max_batch_chars")
        return self

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("pair_adjudication.temperature must be between 0 and 2")
        return value


class EventIdentityConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    provider: Literal["openai", "gemini", "lmstudio"] = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    prompt_version: str = DEFAULT_EVENT_IDENTITY_PROMPT_VERSION
    temperature: float = 0.0
    worker_count: int = DEFAULT_EVENT_IDENTITY_WORKER_COUNT
    max_attempts: int = DEFAULT_EVENT_IDENTITY_MAX_ATTEMPTS
    max_record_chars: int = DEFAULT_EVENT_IDENTITY_MAX_RECORD_CHARS

    @field_validator("model", "prompt_version")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("event_identity model and prompt_version must not be empty")
        return value

    @field_validator("worker_count")
    @classmethod
    def worker_count_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 12:
            raise ValueError("event_identity.worker_count must be between 1 and 12")
        return value

    @field_validator("max_attempts")
    @classmethod
    def attempts_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("event_identity.max_attempts must be between 1 and 5")
        return value

    @field_validator("max_record_chars")
    @classmethod
    def record_limit_must_be_bounded(cls, value: int) -> int:
        if value < 10_000 or value > 2_000_000:
            raise ValueError("event_identity.max_record_chars must be between 10000 and 2000000")
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("event_identity.temperature must be between 0 and 2")
        return value


class ClusterReconciliationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    provider: Literal["openai", "gemini", "lmstudio"] = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    prompt_version: str = DEFAULT_CLUSTER_RECONCILIATION_PROMPT_VERSION
    temperature: float = 0.0
    worker_count: int = DEFAULT_CLUSTER_RECONCILIATION_WORKER_COUNT
    max_attempts: int = DEFAULT_CLUSTER_RECONCILIATION_MAX_ATTEMPTS
    max_component_chars: int = DEFAULT_CLUSTER_RECONCILIATION_MAX_COMPONENT_CHARS
    max_component_tokens: int = DEFAULT_CLUSTER_RECONCILIATION_MAX_COMPONENT_TOKENS
    tokenizer_encoding: str = DEFAULT_CLUSTER_RECONCILIATION_TOKENIZER_ENCODING

    @field_validator("model", "prompt_version", "tokenizer_encoding")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "cluster_reconciliation model, prompt_version, and tokenizer_encoding "
                "must not be empty"
            )
        return value

    @field_validator("worker_count")
    @classmethod
    def worker_count_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 8:
            raise ValueError("cluster_reconciliation.worker_count must be between 1 and 8")
        return value

    @field_validator("max_attempts")
    @classmethod
    def attempts_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("cluster_reconciliation.max_attempts must be between 1 and 5")
        return value

    @field_validator("max_component_chars")
    @classmethod
    def component_limit_must_be_bounded(cls, value: int) -> int:
        if value < 10_000 or value > 2_000_000:
            raise ValueError(
                "cluster_reconciliation.max_component_chars must be between 10000 and 2000000"
            )
        return value

    @field_validator("max_component_tokens")
    @classmethod
    def component_token_limit_must_be_bounded(cls, value: int) -> int:
        if value < 1_000 or value > 120_000:
            raise ValueError(
                "cluster_reconciliation.max_component_tokens must be between 1000 and 120000"
            )
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("cluster_reconciliation.temperature must be between 0 and 2")
        return value


ClusteringConfig.model_rebuild()


class StoryLabelConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    provider: Literal["openai", "gemini", "lmstudio"] = "openai"
    base_url: str | None = None
    prompt_version: str = DEFAULT_STORY_LABEL_PROMPT_VERSION
    worker_count: int = DEFAULT_STORY_LABEL_WORKER_COUNT
    temperature: float = DEFAULT_STORY_LABEL_TEMPERATURE
    max_story_context_chars: int = DEFAULT_MAX_STORY_LABEL_CONTEXT_CHARS

    @field_validator("model", "prompt_version")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("story_label model and prompt_version must not be empty")
        return value

    @field_validator("worker_count")
    @classmethod
    def positive_int_fields(cls, value: int) -> int:
        if value < 1:
            raise ValueError("story_label.worker_count must be at least 1")
        return value

    @field_validator("max_story_context_chars")
    @classmethod
    def story_context_limit_must_be_bounded(cls, value: int) -> int:
        if value < 10_000 or value > 2_000_000:
            raise ValueError(
                "story_label.max_story_context_chars must be between 10000 and 2000000"
            )
        return value

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("story_label.temperature must be between 0 and 2")
        return value


class RankingConfig(BaseModel):
    """Objective measurements only; editorial ordering belongs to editorial_selection."""

    model_config = ConfigDict(extra="allow")

    mode: Literal["telemetry_only"] = "telemetry_only"


class TriagePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    eligible_actions: list[Literal["advance", "reserve"]] = Field(
        default_factory=lambda: ["advance", "reserve"]
    )

    @field_validator("eligible_actions")
    @classmethod
    def actions_must_not_be_empty(cls, value: list[str]) -> list[str]:
        actions = list(dict.fromkeys(value))
        if not actions:
            raise ValueError("config.triage_policy.eligible_actions must not be empty")
        return actions

class StoryMappingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    embedding_model: str
    collection_window: CollectionWindow
    use_llm_story_labels: bool
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    triage_policy: TriagePolicy = Field(default_factory=TriagePolicy)
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
    editorial_triage: "EditorialTriageEnvelope | None" = None


class EditorialTriageData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    mode: str | None = None
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    pools: dict[str, list[str]] = Field(default_factory=dict)


class EditorialTriageEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: EditorialTriageData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


StoryMappingInput.model_rebuild()


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
    semantic_candidate_pair_count: int = 0
    adjudicated_pair_count: int = 0
    unadjudicated_pair_count: int = 0
    time_eligible_pair_count: int = 0
    top_neighbor_pair_count: int = 0
    triage_key_pair_count: int = 0
    similarity_floor_pair_count: int = 0
    candidate_covered_record_count: int = 0
    truncated_candidate_pair_count: int = 0
    transitive_merge_rejection_count: int = 0
    pair_relationship_counts: dict[str, int] = Field(default_factory=dict)
    effective_max_pair_hours: float
    ranking_authority: str
    priority_bucket_counts: dict[str, int]
    source_group_mix: dict[str, int]
    llm_runtime: dict[str, Any]
    top_story_quality_flags: dict[str, int]
    top_stories: list[dict[str, Any]]
    triage: dict[str, Any] = Field(default_factory=dict)


class StoryMappingHandoff(BaseModel):
    story_count: int
    ready_for_editorial_selection: bool


class StoryMappingResponse(BaseModel):
    status: StoryMappingStatus
    data: StoryMappingData
    summary: StoryMappingSummary
    handoff: StoryMappingHandoff
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
    DEFAULT_CANDIDATE_NEIGHBORS_PER_RECORD,
