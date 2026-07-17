from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReviewRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class VisualReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: str
    force: bool = True
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    sample_count: int = 20
    columns: int = 5
    thumbnail_width: int = 420
    jpeg_quality: int = 90
    keep_frames: bool = False

    @field_validator("output_dir", "ffmpeg_path", "ffprobe_path")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("visual review path settings must not be empty")
        return value

    @field_validator("sample_count")
    @classmethod
    def sample_count_must_be_bounded(cls, value: int) -> int:
        if value < 4 or value > 60:
            raise ValueError("config.sample_count must be between 4 and 60")
        return value

    @field_validator("columns")
    @classmethod
    def columns_must_be_bounded(cls, value: int) -> int:
        if value < 2 or value > 10:
            raise ValueError("config.columns must be between 2 and 10")
        return value

    @field_validator("thumbnail_width")
    @classmethod
    def thumbnail_width_must_be_bounded(cls, value: int) -> int:
        if value < 240 or value > 960:
            raise ValueError("config.thumbnail_width must be between 240 and 960")
        return value

    @field_validator("jpeg_quality")
    @classmethod
    def jpeg_quality_must_be_bounded(cls, value: int) -> int:
        if value < 60 or value > 100:
            raise ValueError("config.jpeg_quality must be between 60 and 100")
        return value


class VideoAssemblyData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    final_video_package: dict[str, Any]


class VideoAssemblyEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    data: VideoAssemblyData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VisualReviewInput(BaseModel):
    video_assembly: VideoAssemblyEnvelope


class VisualReviewRequest(BaseModel):
    run: ReviewRun
    config: VisualReviewConfig
    input: VisualReviewInput

    @model_validator(mode="after")
    def assembly_must_be_ready(self) -> "VisualReviewRequest":
        assembly = self.input.video_assembly
        if assembly.status != "ok":
            raise ValueError("input.video_assembly.status must be ok")
        if assembly.data.run_id != self.run.run_id:
            raise ValueError("video assembly run_id does not match request run_id")
        video_path = str(
            assembly.data.final_video_package.get("final_video_path")
            or assembly.handoff.get("final_video_path")
            or assembly.summary.get("final_video_path")
            or ""
        ).strip()
        if not video_path:
            raise ValueError("video assembly final_video_path is missing")
        return self
