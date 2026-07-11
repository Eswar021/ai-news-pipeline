from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_AUDIO_BITRATE,
    DEFAULT_AUDIO_CHANNELS,
    DEFAULT_AUDIO_CODEC,
    DEFAULT_AUDIO_SAMPLE_RATE_HZ,
    DEFAULT_DURATION_TOLERANCE_SECONDS,
    DEFAULT_FFMPEG_PATH,
    DEFAULT_FFPROBE_PATH,
    DEFAULT_PIXEL_FORMAT,
    DEFAULT_REENCODE_CODEC,
    DEFAULT_REENCODE_CRF,
    DEFAULT_REENCODE_PRESET,
    DEFAULT_VIDEO_CODEC,
    DEFAULT_VIDEO_FILENAME,
)


VideoAssemblyStatus = Literal["ok", "failed"]


class VisualsRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class VideoAssemblyConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    output_dir: str
    force: bool = False
    ffmpeg_path: str = DEFAULT_FFMPEG_PATH
    ffprobe_path: str = DEFAULT_FFPROBE_PATH
    final_video_filename: str = DEFAULT_VIDEO_FILENAME
    video_codec: str = DEFAULT_VIDEO_CODEC
    audio_codec: str = DEFAULT_AUDIO_CODEC
    audio_bitrate: str = DEFAULT_AUDIO_BITRATE
    audio_sample_rate_hz: int = DEFAULT_AUDIO_SAMPLE_RATE_HZ
    audio_channels: int = DEFAULT_AUDIO_CHANNELS
    shortest: bool = True
    movflags_faststart: bool = True
    allow_reencode_fallback: bool = True
    reencode_video_codec: str = DEFAULT_REENCODE_CODEC
    reencode_preset: str = DEFAULT_REENCODE_PRESET
    reencode_crf: int = DEFAULT_REENCODE_CRF
    pixel_format: str = DEFAULT_PIXEL_FORMAT
    duration_tolerance_seconds: float = DEFAULT_DURATION_TOLERANCE_SECONDS

    @field_validator("output_dir", "ffmpeg_path", "ffprobe_path", "final_video_filename")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("assembly config text fields must not be empty")
        return value

    @field_validator("duration_tolerance_seconds")
    @classmethod
    def duration_tolerance_must_be_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("config.duration_tolerance_seconds must be non-negative")
        return value

    @field_validator("audio_sample_rate_hz")
    @classmethod
    def audio_sample_rate_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("config.audio_sample_rate_hz must be positive")
        return value

    @field_validator("audio_channels")
    @classmethod
    def audio_channels_must_be_valid(cls, value: int) -> int:
        if value not in {1, 2}:
            raise ValueError("config.audio_channels must be 1 or 2")
        return value

    @field_validator("reencode_crf")
    @classmethod
    def reencode_crf_must_be_valid(cls, value: int) -> int:
        if value < 0 or value > 51:
            raise ValueError("config.reencode_crf must be between 0 and 51")
        return value


class VisualRenderData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    visual_render_package: dict[str, Any]


class VisualRenderEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: VisualRenderData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VideoAssemblyInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    visual_render: VisualRenderEnvelope
    voiceover: dict[str, Any]


class VideoAssemblyRequest(BaseModel):
    run: VisualsRun
    config: VideoAssemblyConfig
    input: VideoAssemblyInput

    @model_validator(mode="after")
    def upstream_artifacts_must_be_ready(self) -> "VideoAssemblyRequest":
        if self.input.visual_render.status != "ok":
            raise ValueError("input.visual_render.status must be ok")
        package = self.input.visual_render.data.visual_render_package
        rendered_scenes = package.get("rendered_scenes")
        if not isinstance(rendered_scenes, list) or not rendered_scenes:
            raise ValueError("visual_render_package.rendered_scenes is missing or empty")
        if not isinstance(self.input.voiceover, dict) or not self.input.voiceover:
            raise ValueError("input.voiceover is missing or empty")
        return self


class VideoAssemblyData(BaseModel):
    run_id: str
    generated_at: str
    final_video_package: dict[str, Any]


class VideoAssemblySummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    assembled_scene_count: int
    audio_duration_seconds: float
    visual_duration_seconds: float
    final_duration_seconds: float
    duration_delta_seconds: float
    output_dir: str
    final_video_path: str
    failure_reason: str = ""


class VideoAssemblyHandoff(BaseModel):
    ready_for_manual_review: bool
    final_video_path: str


class VideoAssemblyResponse(BaseModel):
    status: VideoAssemblyStatus
    data: VideoAssemblyData
    summary: VideoAssemblySummary
    handoff: VideoAssemblyHandoff
