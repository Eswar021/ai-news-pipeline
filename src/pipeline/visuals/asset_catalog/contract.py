from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AssetCatalogRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class PageMetadataConfig(BaseModel):
    enabled: bool = True
    request_timeout_seconds: int = 15
    max_html_bytes: int = 2_000_000
    max_image_bytes: int = 20_000_000
    max_video_bytes: int = 120_000_000
    worker_count: int = 4
    min_image_short_edge: int = 360
    min_image_pixel_area: int = 450_000
    min_image_aspect_ratio: float = 0.2
    max_image_aspect_ratio: float = 5.0
    near_duplicate_hash_distance: int = 5
    max_images_per_record: int = 12
    max_image_candidates: int = 48
    min_video_width: int = 720
    min_video_height: int = 404
    max_videos_per_record: int = 1
    max_video_candidates: int = 8
    ffprobe_path: str = "ffprobe"
    user_agent: str = "AIContentCreation/2.0 (visual-asset-catalog)"
    source_page_fetch_failure_policy: Literal["keep_unverified", "mark_unavailable"] = (
        "mark_unavailable"
    )

    @field_validator(
        "request_timeout_seconds",
        "max_html_bytes",
        "max_image_bytes",
        "max_video_bytes",
        "worker_count",
        "min_image_short_edge",
        "min_image_pixel_area",
        "max_images_per_record",
        "max_image_candidates",
        "min_video_width",
        "min_video_height",
        "max_videos_per_record",
        "max_video_candidates",
    )
    @classmethod
    def positive_values_required(cls, value: int) -> int:
        if value < 1:
            raise ValueError("page metadata limits and worker_count must be positive")
        return value

    @model_validator(mode="after")
    def image_candidate_limit_must_cover_output_limit(self) -> "PageMetadataConfig":
        if self.max_image_candidates < self.max_images_per_record:
            raise ValueError("page_metadata.max_image_candidates must be >= max_images_per_record")
        if self.max_video_candidates < self.max_videos_per_record:
            raise ValueError("page_metadata.max_video_candidates must be >= max_videos_per_record")
        if self.min_image_aspect_ratio <= 0:
            raise ValueError("page_metadata.min_image_aspect_ratio must be positive")
        if self.max_image_aspect_ratio <= self.min_image_aspect_ratio:
            raise ValueError(
                "page_metadata.max_image_aspect_ratio must be greater than min_image_aspect_ratio"
            )
        if self.near_duplicate_hash_distance < 0 or self.near_duplicate_hash_distance > 64:
            raise ValueError(
                "page_metadata.near_duplicate_hash_distance must be between 0 and 64"
            )
        if not self.ffprobe_path.strip():
            raise ValueError("page_metadata.ffprobe_path must not be empty")
        return self


class ContactSheetConfig(BaseModel):
    enabled: bool = True
    columns: int = 3
    tile_width: int = 480
    tile_height: int = 270

    @field_validator("columns", "tile_width", "tile_height")
    @classmethod
    def positive_values_required(cls, value: int) -> int:
        if value < 1:
            raise ValueError("contact sheet dimensions must be positive")
        return value


class SourcePagePreflightConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    timeout_ms: int = 20_000
    post_load_wait_ms: int = 1_000
    viewport_width: int = 1_440
    viewport_height: int = 900
    device_scale_factor: float = 1.0
    save_preview_debug: bool = True
    failure_policy: Literal["keep_unverified", "mark_unavailable"] = "mark_unavailable"
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )

    @field_validator("timeout_ms", "post_load_wait_ms")
    @classmethod
    def non_negative_timings_required(cls, value: int) -> int:
        if value < 0:
            raise ValueError("source_page_preflight timing values must be non-negative")
        return value

    @field_validator("viewport_width", "viewport_height")
    @classmethod
    def positive_viewport_required(cls, value: int) -> int:
        if value < 1:
            raise ValueError("source_page_preflight viewport values must be positive")
        return value

    @field_validator("device_scale_factor")
    @classmethod
    def device_scale_factor_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("source_page_preflight.device_scale_factor must be positive")
        return value

    @field_validator("user_agent")
    @classmethod
    def user_agent_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_page_preflight.user_agent must not be empty")
        return value


class SourceLinkedVideoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    providers: list[Literal["youtube", "vimeo", "x"]] = Field(
        default_factory=lambda: ["youtube", "vimeo", "x"]
    )
    yt_dlp_path: str = "yt-dlp"
    download_timeout_seconds: int = 180
    max_links_per_record: int = 3
    max_duration_seconds: int = 1_800
    max_height: int = 1_080
    max_chapter_moments: int = 24

    @field_validator(
        "download_timeout_seconds",
        "max_links_per_record",
        "max_duration_seconds",
        "max_height",
        "max_chapter_moments",
    )
    @classmethod
    def positive_values_required(cls, value: int) -> int:
        if value < 1:
            raise ValueError("source_linked_video limits must be positive")
        return value

    @field_validator("providers")
    @classmethod
    def providers_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("source_linked_video.providers must not be empty")
        return value

    @field_validator("yt_dlp_path")
    @classmethod
    def yt_dlp_path_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_linked_video.yt_dlp_path must not be empty")
        return value


class AssetCatalogConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    output_dir: str
    force: bool = False
    research_mode: Literal["trusted_only"] = "trusted_only"
    require_visual_research: bool = False
    require_real_anchor_per_story: bool = True
    collect_source_pages: bool = True
    collect_source_images: bool = True
    collect_source_videos: bool = False
    collect_resolvable_logos: bool = True
    local_logo_dir: str | None = None
    page_metadata: PageMetadataConfig = Field(default_factory=PageMetadataConfig)
    source_page_preflight: SourcePagePreflightConfig = Field(
        default_factory=SourcePagePreflightConfig
    )
    source_linked_video: SourceLinkedVideoConfig = Field(
        default_factory=SourceLinkedVideoConfig
    )
    contact_sheet: ContactSheetConfig = Field(default_factory=ContactSheetConfig)

    @field_validator("output_dir")
    @classmethod
    def output_dir_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.output_dir must not be empty")
        return value


class ScriptGenerationData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    script_package: dict[str, Any]


class ScriptGenerationEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    data: ScriptGenerationData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VideoPackagingData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    selected_format: str
    video_packet: dict[str, Any]


class VideoPackagingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    data: VideoPackagingData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VisualResearchData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    visual_research_package: dict[str, Any]


class VisualResearchEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    data: VisualResearchData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class AssetCatalogInput(BaseModel):
    script_generation: ScriptGenerationEnvelope
    video_packaging: VideoPackagingEnvelope
    visual_research: VisualResearchEnvelope | None = None

    @model_validator(mode="after")
    def upstream_results_must_be_ready(self) -> "AssetCatalogInput":
        if self.script_generation.status != "ok":
            raise ValueError("input.script_generation.status must be ok")
        if self.video_packaging.status != "ok":
            raise ValueError("input.video_packaging.status must be ok")
        return self


class AssetCatalogRequest(BaseModel):
    run: AssetCatalogRun
    config: AssetCatalogConfig
    input: AssetCatalogInput

    @model_validator(mode="after")
    def visual_research_must_be_ready_when_required(self) -> "AssetCatalogRequest":
        if self.config.require_visual_research and self.input.visual_research is None:
            raise ValueError("input.visual_research is required by config.require_visual_research")
        if self.input.visual_research is not None and self.input.visual_research.status != "ok":
            raise ValueError("input.visual_research.status must be ok")
        return self


class AssetCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["ok", "failed"]
    data: dict[str, Any]
    summary: dict[str, Any]
    handoff: dict[str, Any]
