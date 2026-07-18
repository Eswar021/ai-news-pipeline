from __future__ import annotations

from typing import Any, Literal

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .utils import parse_datetime


EvidencePrepStatus = Literal["ok", "failed"]


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


class ContentCleaningRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    domain_suffixes: list[str]
    leading_markers: list[str] = Field(default_factory=list)
    trailing_markers: list[str] = Field(default_factory=list)
    remove_phrases: list[str] = Field(default_factory=list)
    remove_patterns: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content cleaning rule name must not be empty")
        return value.strip()

    @field_validator(
        "domain_suffixes",
        "leading_markers",
        "trailing_markers",
        "remove_phrases",
        "remove_patterns",
    )
    @classmethod
    def rule_lists_must_contain_strings(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @field_validator("domain_suffixes")
    @classmethod
    def domains_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("content cleaning rule domain_suffixes must not be empty")
        return value

    @field_validator("remove_patterns")
    @classmethod
    def remove_patterns_must_compile(cls, value: list[str]) -> list[str]:
        for pattern in value:
            try:
                re.compile(pattern, flags=re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"invalid content cleaning regex {pattern!r}: {exc}") from exc
        return value


class ContentCleaningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    strip_html_markup: bool = True
    rules: list[ContentCleaningRule] = Field(default_factory=list)


class EvidencePrepConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    collection_window: CollectionWindow
    query_themes: list[str] = Field(default_factory=list)
    content_cleaning: ContentCleaningConfig = Field(default_factory=ContentCleaningConfig)

    @field_validator("query_themes")
    @classmethod
    def query_themes_must_be_strings(cls, value: list[str]) -> list[str]:
        for theme in value:
            if not isinstance(theme, str):
                raise ValueError("config.query_themes must contain strings")
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
    decision_count: int
    decision_ledger: list[dict[str, Any]]


class EvidencePrepSummary(BaseModel):
    run_id: str
    generated_at: str
    status: EvidencePrepStatus
    input_record_count: int
    prepared_record_count: int
    excluded_count: int
    duplicate_count: int
    decision_counts: dict[str, int]
    quality_flag_counts: dict[str, int]
    preparation_warning_counts: dict[str, int]
    content_status_counts: dict[str, int]
    exclude_reason_counts: dict[str, int]
    source_groups: dict[str, dict[str, int]]
    source_relationship_counts: dict[str, int]
    content_cleaning: dict[str, Any]
    excluded_records: list[dict[str, Any]]


class EvidencePrepHandoff(BaseModel):
    record_count: int
    ready_for_editorial_triage: bool


class EvidencePrepResponse(BaseModel):
    status: EvidencePrepStatus
    data: EvidencePrepData
    summary: EvidencePrepSummary
    handoff: EvidencePrepHandoff
