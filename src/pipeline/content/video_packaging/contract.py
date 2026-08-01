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


class RoundupConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    min_stories: int
    max_stories: int
    duration_mode: Literal["content_driven"] = "content_driven"
    duration_ceiling_seconds: int | None = None
    @field_validator("min_stories", "max_stories")
    @classmethod
    def positive_ints(cls, value: int) -> int:
        if value < 1:
            raise ValueError("roundup positive integer fields must be at least 1")
        return value

    @field_validator("duration_ceiling_seconds")
    @classmethod
    def optional_ceiling_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("roundup.duration_ceiling_seconds must be positive when provided")
        return value

    @model_validator(mode="after")
    def validate_roundup_bounds(self) -> "RoundupConfig":
        if self.min_stories > self.max_stories:
            raise ValueError("roundup.min_stories must be <= roundup.max_stories")
        return self


class DeepDiveConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    # deep_dive expands a single story into angle sections, so exactly one story
    # is required. story_selection chooses which story from the upstream slate.
    min_stories: int = 1
    story_selection: Literal["lead"] = "lead"
    duration_mode: Literal["content_driven"] = "content_driven"
    duration_ceiling_seconds: int | None = None

    @field_validator("duration_ceiling_seconds")
    @classmethod
    def optional_ceiling_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("deep_dive.duration_ceiling_seconds must be positive when provided")
        return value


class VideoPackagingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    target_format: TargetFormat
    # Per-format config is optional in the model; the active format's block is
    # required, enforced below. This keeps each format's config self-contained.
    roundup: RoundupConfig | None = None
    deep_dive: DeepDiveConfig | None = None

    @model_validator(mode="after")
    def active_format_config_is_present_and_known(self) -> "VideoPackagingConfig":
        if self.target_format not in SUPPORTED_FORMATS and self.target_format not in KNOWN_FUTURE_FORMATS:
            raise ValueError(f"Unsupported target_format: {self.target_format}")
        if self.target_format == "roundup" and self.roundup is None:
            raise ValueError("video_packaging.roundup config is required when target_format is 'roundup'")
        if self.target_format == "deep_dive" and self.deep_dive is None:
            raise ValueError("video_packaging.deep_dive config is required when target_format is 'deep_dive'")
        return self


class EditorialSelectionData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    selected_format: str | None = None
    editorial_slate: dict[str, Any]


class EditorialSelectionEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: EditorialSelectionData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VideoPackagingInput(BaseModel):
    editorial_selection: EditorialSelectionEnvelope


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
    duration_mode: Literal["content_driven"] = "content_driven"
    duration_ceiling_seconds: int | None = None
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
