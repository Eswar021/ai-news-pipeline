from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_PEXELS_PHOTO_ENDPOINT,
    DEFAULT_PEXELS_VIDEO_ENDPOINT,
    DEFAULT_PIXABAY_PHOTO_ENDPOINT,
    DEFAULT_PIXABAY_VIDEO_ENDPOINT,
    DEFAULT_USER_AGENT,
    DEFAULT_WIKIMEDIA_ENDPOINT,
)


VisualMediaStatus = Literal["ok", "partial", "failed"]


class VisualsRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class WikimediaProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    endpoint: str = DEFAULT_WIKIMEDIA_ENDPOINT
    include_images: bool = True
    include_videos: bool = False


class PexelsProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    api_key_env: str = "PEXELS_API_KEY"
    photo_endpoint: str = DEFAULT_PEXELS_PHOTO_ENDPOINT
    video_endpoint: str = DEFAULT_PEXELS_VIDEO_ENDPOINT


class PixabayProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    api_key_env: str = "PIXABAY_API_KEY"
    photo_endpoint: str = DEFAULT_PIXABAY_PHOTO_ENDPOINT
    video_endpoint: str = DEFAULT_PIXABAY_VIDEO_ENDPOINT


class MediaProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wikimedia: WikimediaProviderConfig = Field(default_factory=WikimediaProviderConfig)
    pexels: PexelsProviderConfig = Field(default_factory=PexelsProviderConfig)
    pixabay: PixabayProviderConfig = Field(default_factory=PixabayProviderConfig)


class VisualMediaConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    output_dir: str
    force: bool = False
    user_agent: str = DEFAULT_USER_AGENT
    request_timeout_seconds: int = 25
    download_timeout_seconds: int = 90
    max_download_bytes: int = 250_000_000
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    video_output_width: int = 1280
    video_clip_padding_seconds: float = 0.75
    max_queries_per_scene: int = 3
    max_candidates_per_query: int = 8
    candidate_catalog_limit_per_scene: int = 12
    min_image_width: int = 1280
    min_image_height: int = 720
    preferred_aspect_ratio: float = 16 / 9
    minimum_selection_score: float = 0.15
    unresolved_fallback_render_kind: Literal["kinetic_type_scene"] | None = "kinetic_type_scene"
    providers: MediaProvidersConfig = Field(default_factory=MediaProvidersConfig)

    @field_validator("output_dir", "user_agent")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.output_dir and config.user_agent must not be empty")
        return value

    @field_validator(
        "request_timeout_seconds",
        "download_timeout_seconds",
        "max_download_bytes",
        "video_output_width",
        "max_queries_per_scene",
        "max_candidates_per_query",
        "candidate_catalog_limit_per_scene",
        "min_image_width",
        "min_image_height",
    )
    @classmethod
    def positive_integers_required(cls, value: int) -> int:
        if value < 1:
            raise ValueError("media discovery integer settings must be positive")
        return value

    @field_validator("preferred_aspect_ratio", "minimum_selection_score")
    @classmethod
    def positive_floats_required(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("media discovery ratio/score settings must be positive")
        return value

    @field_validator("video_clip_padding_seconds")
    @classmethod
    def clip_padding_must_be_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("config.video_clip_padding_seconds must be non-negative")
        return value


class VisualScenePlanData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    generated_at: str | None = None
    selected_format: str | None = None
    visual_scene_plan: dict[str, Any]


class VisualScenePlanEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: VisualScenePlanData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VisualMediaInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    visual_scene_planning: VisualScenePlanEnvelope


class VisualMediaRequest(BaseModel):
    run: VisualsRun
    config: VisualMediaConfig
    input: VisualMediaInput

    @model_validator(mode="after")
    def visual_scene_plan_must_be_ready(self) -> "VisualMediaRequest":
        if self.input.visual_scene_planning.status != "ok":
            raise ValueError("input.visual_scene_planning.status must be ok")
        plan = self.input.visual_scene_planning.data.visual_scene_plan
        if not isinstance(plan.get("scene_timeline"), list) or not plan.get("scene_timeline"):
            raise ValueError("visual_scene_plan.scene_timeline is missing or empty")
        return self


class VisualMediaData(BaseModel):
    run_id: str
    generated_at: str
    visual_media_package: dict[str, Any]


class VisualMediaSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    requested_media_scene_count: int
    selected_media_count: int
    selected_image_count: int
    selected_video_count: int
    fallback_scene_count: int
    unresolved_scene_count: int
    provider_error_count: int
    download_error_count: int = 0
    output_dir: str
    failure_reason: str = ""


class VisualMediaHandoff(BaseModel):
    ready_for_visual_asset_resolution: bool
    next_module: str


class VisualMediaResponse(BaseModel):
    status: VisualMediaStatus
    data: VisualMediaData
    summary: VisualMediaSummary
    handoff: VisualMediaHandoff
