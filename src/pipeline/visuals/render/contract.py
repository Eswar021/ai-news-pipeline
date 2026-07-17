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
    render_mode: Literal["preview", "final"] = "final"
    quality_preset: Literal["custom", "1080p", "2k", "4k"] = "custom"
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    codec: str = DEFAULT_CODEC
    crf: int | None = None
    video_bitrate: str | None = None
    x264_preset: str | None = None
    pixel_format: str | None = None
    hardware_acceleration: Literal["disable", "if-possible", "required"] = "if-possible"
    bundle_timeout_seconds: int = 240
    render_timeout_seconds: int = 240
    worker_count: int = 1
    frame_concurrency: int = 2
    max_render_attempts: int = 2
    keep_render_logs: bool = True
    max_scene_duration_seconds: float | None = None
    scene_limit: int | None = None
    selected_scene_ids: list[str] = Field(default_factory=list)
    selected_story_ids: list[str] = Field(default_factory=list)
    cache_dir: str | None = None
    reuse_cached_scenes: bool = False
    batch_renderer_enabled: bool = True

    @field_validator("output_dir")
    @classmethod
    def output_dir_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.output_dir must not be empty")
        return value

    @field_validator(
        "width",
        "height",
        "fps",
        "bundle_timeout_seconds",
        "render_timeout_seconds",
        "worker_count",
        "frame_concurrency",
        "max_render_attempts",
    )
    @classmethod
    def positive_numbers_required(cls, value: int) -> int:
        if value < 1:
            raise ValueError("render dimensions, fps, timeouts, concurrency, and attempts must be positive")
        return value

    @field_validator("max_render_attempts")
    @classmethod
    def render_attempts_must_be_bounded(cls, value: int) -> int:
        if value > 5:
            raise ValueError("config.max_render_attempts must not exceed 5")
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

    @field_validator("selected_scene_ids", "selected_story_ids")
    @classmethod
    def selection_values_must_be_clean(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @model_validator(mode="after")
    def concurrency_must_be_safe(self) -> "VisualRenderConfig":
        if self.worker_count > 8:
            raise ValueError("config.worker_count must not exceed 8; use cache and preview mode before adding workers")
        if self.frame_concurrency > 4:
            raise ValueError("config.frame_concurrency must not exceed 4")
        if self.reuse_cached_scenes and not (self.cache_dir or "").strip():
            raise ValueError("config.cache_dir is required when reuse_cached_scenes=true")
        return self


class AssetResolverData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
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
