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


class SemanticVerificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    provider: Literal["openai"] = "openai"
    model: str = "gpt-4o-mini"
    prompt_version: str = "v1"
    temperature: float = 0.0
    max_candidates_per_scene: int = 4
    max_attempts: int = 2
    verify_video_clip_frames: bool = True
    max_video_sample_frames: int = 5
    video_clip_failure_policy: Literal["reject", "start_at_zero"] = "reject"

    @field_validator("model", "prompt_version")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("semantic verification model and prompt_version must not be empty")
        return value

    @field_validator("max_candidates_per_scene")
    @classmethod
    def candidate_limit_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 8:
            raise ValueError("semantic verification max_candidates_per_scene must be between 1 and 8")
        return value

    @field_validator("max_video_sample_frames")
    @classmethod
    def video_sample_limit_must_be_bounded(cls, value: int) -> int:
        if value < 2 or value > 8:
            raise ValueError("semantic verification max_video_sample_frames must be between 2 and 8")
        return value

    @field_validator("max_attempts")
    @classmethod
    def attempts_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 4:
            raise ValueError("semantic verification max_attempts must be between 1 and 4")
        return value

    @field_validator("temperature")
    @classmethod
    def fractional_values_must_be_bounded(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("semantic verification temperature must be between 0 and 1")
        return value


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
    trusted_catalog_only: bool = False
    allow_query_fallback: bool = False
    reuse_equivalent_image_requests: bool = True
    max_fallback_requests: int | None = None
    max_fallback_scenes: int = 3
    unresolved_fallback_render_kind: Literal["kinetic_type_scene"] | None = "kinetic_type_scene"
    semantic_verification: SemanticVerificationConfig = Field(
        default_factory=SemanticVerificationConfig
    )
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

    @field_validator("preferred_aspect_ratio")
    @classmethod
    def positive_floats_required(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("media discovery ratio/score settings must be positive")
        return value

    @field_validator("max_fallback_requests", "max_fallback_scenes")
    @classmethod
    def fallback_budget_must_be_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("media fallback request budget must be non-negative")
        return value

    @property
    def fallback_request_budget(self) -> int:
        if self.max_fallback_requests is not None:
            return self.max_fallback_requests
        return self.max_fallback_scenes

    @model_validator(mode="after")
    def external_media_requires_semantic_review(self) -> "VisualMediaConfig":
        if not self.trusted_catalog_only and not self.semantic_verification.enabled:
            raise ValueError(
                "External media discovery requires semantic_verification.enabled=true; "
                "lexical or numeric ranking cannot approve contextual media"
            )
        return self

    @field_validator("video_clip_padding_seconds")
    @classmethod
    def clip_padding_must_be_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("config.video_clip_padding_seconds must be non-negative")
        return value


class VisualScenePlanData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
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
    unique_media_request_count: int = 0
    reused_media_scene_count: int = 0
    selected_media_count: int
    selected_asset_count: int = 0
    selected_image_count: int
    selected_video_count: int
    fallback_scene_count: int
    fallback_request_count: int = 0
    fallback_request_budget: int = 0
    unresolved_scene_count: int
    provider_error_count: int
    download_error_count: int = 0
    semantic_verified_candidate_count: int = 0
    semantic_accepted_candidate_count: int = 0
    semantic_rejected_candidate_count: int = 0
    semantic_clip_selection_count: int = 0
    llm_call_count: int = 0
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
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
