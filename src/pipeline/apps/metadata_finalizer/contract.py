from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MetadataFinalizerRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class MetadataFinalizerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_all_script_sections: bool = True
    first_chapter_tolerance_seconds: float = 0.25

    @field_validator("first_chapter_tolerance_seconds")
    @classmethod
    def tolerance_must_be_non_negative(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("config.first_chapter_tolerance_seconds must be between 0 and 2")
        return value


class MetadataFinalizerInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata_creator: dict[str, Any]
    script_generation: dict[str, Any]
    voiceover: dict[str, Any]


class MetadataFinalizerRequest(BaseModel):
    run: MetadataFinalizerRun
    config: MetadataFinalizerConfig = Field(default_factory=MetadataFinalizerConfig)
    input: MetadataFinalizerInput


class MetadataFinalizerData(BaseModel):
    run_id: str
    generated_at: str
    selected_format: str
    metadata_package: dict[str, Any]


class MetadataFinalizerSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    chapter_count: int
    audio_unit_count: int
    chapters_finalized: bool
    timing_source: str
    failure_reason: str = ""


class MetadataFinalizerHandoff(BaseModel):
    ready_for_media_production: bool
    ready_for_publish_review: bool
    chapters_finalized: bool


class MetadataFinalizerResponse(BaseModel):
    status: Literal["ok", "failed"]
    data: MetadataFinalizerData
    summary: MetadataFinalizerSummary
    handoff: MetadataFinalizerHandoff
