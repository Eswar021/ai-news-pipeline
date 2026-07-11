from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import DEFAULT_MAX_RESEARCH_PAPERS
from .utils import parse_datetime


EvidencePrepStatus = Literal["ok", "partial", "failed"]


class EvidencePrepRun(BaseModel):
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
    lookback_hours: int | float | None = None

    @field_validator("start", "end")
    @classmethod
    def window_endpoint_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("collection_window start/end must not be empty")
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


class EvidencePrepConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    collection_window: CollectionWindow
    query_themes: list[str] = Field(default_factory=list)
    max_research_papers: int = DEFAULT_MAX_RESEARCH_PAPERS
    filter_policy: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query_themes")
    @classmethod
    def query_themes_must_be_strings(cls, value: list[str]) -> list[str]:
        for theme in value:
            if not isinstance(theme, str):
                raise ValueError("config.query_themes must contain strings")
        return value

    @field_validator("max_research_papers")
    @classmethod
    def max_research_papers_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("config.max_research_papers must be non-negative")
        return value


class NewsCollectionData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    record_count: int | None = None
    records: list[dict[str, Any]]


class NewsCollectionEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: NewsCollectionData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class EvidencePrepInput(BaseModel):
    news_collection: NewsCollectionEnvelope


class EvidencePrepRequest(BaseModel):
    run: EvidencePrepRun
    config: EvidencePrepConfig
    input: EvidencePrepInput


class EvidencePrepData(BaseModel):
    run_id: str
    generated_at: str
    record_count: int
    records: list[dict[str, Any]]


class EvidencePrepSummary(BaseModel):
    run_id: str
    generated_at: str
    status: EvidencePrepStatus
    input_record_count: int
    prepared_record_count: int
    excluded_count: int
    duplicate_count: int
    content_status_counts: dict[str, int]
    exclude_reason_counts: dict[str, int]
    source_groups: dict[str, dict[str, int]]
    excluded_records: list[dict[str, Any]]


class EvidencePrepHandoff(BaseModel):
    record_count: int
    ready_for_story_mapping: bool


class EvidencePrepResponse(BaseModel):
    status: EvidencePrepStatus
    data: EvidencePrepData
    summary: EvidencePrepSummary
    handoff: EvidencePrepHandoff
