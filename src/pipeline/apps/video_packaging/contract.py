from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import KNOWN_FUTURE_FORMATS, SUPPORTED_FORMATS


VideoPackagingStatus = Literal["ok", "failed"]
TargetFormat = Literal["roundup", "auto", "deep_dive"]


class VideoPackagingRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class RoleWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead: float
    major: float
    brief: float

    @field_validator("lead", "major", "brief")
    @classmethod
    def weights_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("roundup.role_weights values must be positive")
        return value


class RoundupConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_limit: int
    min_stories: int
    max_stories: int
    target_duration_seconds: int
    intro_seconds: int
    closing_seconds: int
    role_weights: RoleWeights
    max_per_entity: int
    max_per_product: int
    max_per_event_family: int
    allowed_priority_buckets: list[str]
    exclude_noise: bool
    exclude_tutorials: bool

    @field_validator(
        "candidate_limit",
        "min_stories",
        "max_stories",
        "target_duration_seconds",
        "max_per_entity",
        "max_per_product",
        "max_per_event_family",
    )
    @classmethod
    def positive_ints(cls, value: int) -> int:
        if value < 1:
            raise ValueError("roundup positive integer fields must be at least 1")
        return value

    @field_validator("intro_seconds", "closing_seconds")
    @classmethod
    def non_negative_seconds(cls, value: int) -> int:
        if value < 0:
            raise ValueError("roundup intro_seconds and closing_seconds must be non-negative")
        return value

    @field_validator("allowed_priority_buckets")
    @classmethod
    def priority_buckets_must_be_non_empty_strings(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("roundup.allowed_priority_buckets must not be empty")
        cleaned = []
        for bucket in value:
            if not isinstance(bucket, str) or not bucket.strip():
                raise ValueError("roundup.allowed_priority_buckets must contain non-empty strings")
            cleaned.append(bucket.strip())
        return cleaned

    @model_validator(mode="after")
    def validate_roundup_bounds(self) -> "RoundupConfig":
        if self.min_stories > self.max_stories:
            raise ValueError("roundup.min_stories must be <= roundup.max_stories")
        if self.candidate_limit < self.max_stories:
            raise ValueError("roundup.candidate_limit must be >= roundup.max_stories")
        story_budget = self.target_duration_seconds - self.intro_seconds - self.closing_seconds
        if story_budget <= 0:
            raise ValueError("roundup target_duration_seconds must exceed intro_seconds + closing_seconds")
        return self


class VideoPackagingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    target_format: TargetFormat
    roundup: RoundupConfig

    @model_validator(mode="after")
    def known_but_unsupported_formats_are_allowed_to_route(self) -> "VideoPackagingConfig":
        if self.target_format not in SUPPORTED_FORMATS and self.target_format not in KNOWN_FUTURE_FORMATS:
            raise ValueError(f"Unsupported target_format: {self.target_format}")
        return self


class StoryMappingData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    story_count: int | None = None
    stories: list[dict[str, Any]]


class StoryMappingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: StoryMappingData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VideoPackagingInput(BaseModel):
    story_mapping: StoryMappingEnvelope


class VideoPackagingRequest(BaseModel):
    run: VideoPackagingRun
    config: VideoPackagingConfig
    input: VideoPackagingInput


class VideoPackagingData(BaseModel):
    run_id: str
    generated_at: str
    selected_format: str
    script_app: str
    video_packet: dict[str, Any]


class VideoPackagingSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_story_count: int
    candidate_story_count: int
    selected_story_count: int
    rejected_story_count: int
    selection_reason_counts: dict[str, int]
    role_counts: dict[str, int]
    target_duration_seconds: int
    failure_reason: str = ""


class VideoPackagingHandoff(BaseModel):
    ready_for_script_generation: bool
    script_app: str
    selected_format: str


class VideoPackagingResponse(BaseModel):
    status: VideoPackagingStatus
    data: VideoPackagingData
    summary: VideoPackagingSummary
    handoff: VideoPackagingHandoff
