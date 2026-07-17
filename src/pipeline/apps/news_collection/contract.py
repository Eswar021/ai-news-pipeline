from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    COLLECTION_WINDOW_REQUIRED_GROUPS,
    SUPPORTED_SOURCE_GROUPS,
)


NewsCollectionStatus = Literal["ok", "partial", "failed"]
CandidateDecision = Literal[
    "collected",
    "quarantined",
    "hard_rejected",
    "fetch_failed",
    "not_processed",
]


class NewsCollectionRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class CollectorConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_group: str
    collection_window: dict[str, Any] | None = None
    query_themes: list[str] = Field(default_factory=list)
    runtime: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_group")
    @classmethod
    def source_group_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("collector config source_group must not be empty")
        return value


class NewsCollectionConfig(BaseModel):
    enabled_source_groups: list[str]
    query_themes: list[str]
    collectors: dict[str, CollectorConfig]

    @field_validator("enabled_source_groups")
    @classmethod
    def enabled_groups_must_be_strings(cls, value: list[str]) -> list[str]:
        for group_name in value:
            if not isinstance(group_name, str) or not group_name.strip():
                raise ValueError("config.enabled_source_groups must contain non-empty strings")
        return value

    @model_validator(mode="after")
    def validate_enabled_collectors(self) -> "NewsCollectionConfig":
        for group_name in self.enabled_source_groups:
            if group_name not in SUPPORTED_SOURCE_GROUPS:
                raise ValueError(f"Unsupported news collection source group: {group_name}")
            collector_cfg = self.collectors.get(group_name)
            if collector_cfg is None:
                raise ValueError(f"Missing collector config for enabled source group: {group_name}")
            if collector_cfg.source_group != group_name:
                raise ValueError(
                    f"Collector config source_group mismatch for {group_name}: "
                    f"{collector_cfg.source_group}"
                )
            if group_name in COLLECTION_WINDOW_REQUIRED_GROUPS and not collector_cfg.collection_window:
                raise ValueError(f"Collector config missing collection_window for: {group_name}")
        return self


class NewsCollectionRequest(BaseModel):
    run: NewsCollectionRun
    config: NewsCollectionConfig
    input: dict[str, Any] = Field(default_factory=dict)


class NewsCandidateDecision(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_key: str
    source_group: str
    source: str
    title: str = ""
    url: str = ""
    published_at: str = ""
    decision: CandidateDecision
    reason_code: str = ""
    reason: str = ""
    decision_owner: Literal["code"] = "code"
    record_id: str | None = None
    quality_flags: dict[str, Any] = Field(default_factory=dict)
    retrieval_hints: dict[str, Any] = Field(default_factory=dict)


class NewsCollectionData(BaseModel):
    run_id: str
    generated_at: str
    record_count: int
    records: list[dict[str, Any]]
    candidate_count: int
    candidate_ledger: list[NewsCandidateDecision]


class NewsCollectionSummary(BaseModel):
    run_id: str
    generated_at: str
    status: NewsCollectionStatus
    enabled_source_groups: list[str]
    enabled_source_group_count: int
    successful_source_groups: list[str]
    successful_source_group_count: int
    total_records: int
    candidate_count: int
    candidate_decision_counts: dict[str, int]
    elapsed_seconds: float
    groups: dict[str, dict[str, Any]]


class NewsCollectionHandoff(BaseModel):
    record_count: int
    candidate_count: int
    ready_for_evidence_prep: bool


class NewsCollectionResponse(BaseModel):
    status: NewsCollectionStatus
    data: NewsCollectionData
    summary: NewsCollectionSummary
    handoff: NewsCollectionHandoff
