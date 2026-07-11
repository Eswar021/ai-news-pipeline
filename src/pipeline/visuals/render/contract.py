from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import DEFAULT_CODEC, DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH


VisualRenderStatus = Literal["ok", "partial", "failed"]


class VisualsRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class VisualRenderConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    output_dir: str
    force: bool = False
    remotion_engine_dir: str | None = None
    quality_preset: Literal["custom", "1080p", "2k", "4k"] = "custom"
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    codec: str = DEFAULT_CODEC
    crf: int | None = None
    video_bitrate: str | None = None
    x264_preset: str | None = None
    pixel_format: str | None = None
    render_timeout_seconds: int = 240
    worker_count: int = 1
    max_scene_duration_seconds: float | None = None
    scene_limit: int | None = None

    @field_validator("output_dir")
    @classmethod
    def output_dir_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.output_dir must not be empty")
        return value

    @field_validator("width", "height", "fps", "render_timeout_seconds", "worker_count")
    @classmethod
    def positive_numbers_required(cls, value: int) -> int:
        if value < 1:
            raise ValueError("render dimensions, fps, timeout, and worker_count must be positive")
        return value

    @field_validator("max_scene_duration_seconds")
    @classmethod
    def max_scene_duration_must_be_positive(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("config.max_scene_duration_seconds must be positive when provided")
        return value

    @field_validator("crf")
    @classmethod
    def crf_must_be_valid(cls, value: int | None) -> int | None:
        if value is not None and (value < 0 or value > 51):
            raise ValueError("config.crf must be between 0 and 51 when provided")
        return value


class AssetResolverData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    visual_asset_manifest: dict[str, Any]


class AssetResolverEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: AssetResolverData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VisualRenderInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    visual_asset_resolution: AssetResolverEnvelope


class VisualRenderRequest(BaseModel):
    run: VisualsRun
    config: VisualRenderConfig
    input: VisualRenderInput

    @model_validator(mode="after")
    def asset_resolution_must_be_usable(self) -> "VisualRenderRequest":
        if self.input.visual_asset_resolution.status not in {"ok", "partial"}:
            raise ValueError("input.visual_asset_resolution.status must be ok or partial")
        manifest = self.input.visual_asset_resolution.data.visual_asset_manifest
        if not isinstance(manifest.get("render_scenes"), list) or not manifest.get("render_scenes"):
            raise ValueError("visual_asset_manifest.render_scenes is missing or empty")
        return self


class VisualRenderData(BaseModel):
    run_id: str
    generated_at: str
    visual_render_package: dict[str, Any]


class VisualRenderSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    requested_scene_count: int
    rendered_scene_count: int
    failed_scene_count: int
    output_dir: str
    failure_reason: str = ""


class VisualRenderHandoff(BaseModel):
    ready_for_video_assembly: bool
    next_module: str


class VisualRenderResponse(BaseModel):
    status: VisualRenderStatus
    data: VisualRenderData
    summary: VisualRenderSummary
    handoff: VisualRenderHandoff
