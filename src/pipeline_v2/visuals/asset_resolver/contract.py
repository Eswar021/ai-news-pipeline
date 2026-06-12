from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_BROWSER_TIMEOUT_MS,
    DEFAULT_DEVICE_SCALE_FACTOR,
    DEFAULT_POST_LOAD_WAIT_MS,
    DEFAULT_TARGET_HEIGHT,
    DEFAULT_TARGET_WIDTH,
    DEFAULT_USER_AGENT,
)


AssetResolverStatus = Literal["ok", "partial", "failed"]
CaptureMode = Literal["article_viewport", "headline_then_body", "target_text_focus"]


class VisualsRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class BrowserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headless: bool = True
    timeout_ms: int = DEFAULT_BROWSER_TIMEOUT_MS
    post_load_wait_ms: int = DEFAULT_POST_LOAD_WAIT_MS
    device_scale_factor: float = DEFAULT_DEVICE_SCALE_FACTOR
    user_agent: str = DEFAULT_USER_AGENT

    @field_validator("timeout_ms", "post_load_wait_ms")
    @classmethod
    def millis_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("browser timeout/wait values must be non-negative")
        return value

    @field_validator("device_scale_factor")
    @classmethod
    def device_scale_factor_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("browser.device_scale_factor must be positive")
        return value


class SourceScreenshotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    capture_mode: CaptureMode = "target_text_focus"
    save_full_page_debug: bool = False
    save_raw_capture_debug: bool = True


class LogoConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    local_logo_dir: str | None = None
    simple_icons_enabled: bool = True
    favicon_fallback_enabled: bool = True
    text_fallback_enabled: bool = True


class AssetResolverConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    output_dir: str
    force: bool = False
    target_width: int = DEFAULT_TARGET_WIDTH
    target_height: int = DEFAULT_TARGET_HEIGHT
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    source_screenshots: SourceScreenshotConfig = Field(default_factory=SourceScreenshotConfig)
    logos: LogoConfig = Field(default_factory=LogoConfig)

    @field_validator("output_dir")
    @classmethod
    def output_dir_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.output_dir must not be empty")
        return value

    @field_validator("target_width", "target_height")
    @classmethod
    def dimensions_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("target dimensions must be positive")
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


class AssetResolverInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    visual_scene_planning: VisualScenePlanEnvelope


class AssetResolverRequest(BaseModel):
    run: VisualsRun
    config: AssetResolverConfig
    input: AssetResolverInput

    @model_validator(mode="after")
    def visual_scene_plan_must_be_ready(self) -> "AssetResolverRequest":
        if self.input.visual_scene_planning.status != "ok":
            raise ValueError("input.visual_scene_planning.status must be ok")
        plan = self.input.visual_scene_planning.data.visual_scene_plan
        if not isinstance(plan.get("scene_timeline"), list) or not plan.get("scene_timeline"):
            raise ValueError("visual_scene_plan.scene_timeline is missing or empty")
        return self


class AssetResolverData(BaseModel):
    run_id: str
    generated_at: str
    visual_asset_manifest: dict[str, Any]


class AssetResolverSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    requested_scene_count: int
    resolved_asset_count: int
    source_screenshot_count: int
    logo_asset_count: int
    failed_asset_count: int
    output_dir: str
    failure_reason: str = ""


class AssetResolverHandoff(BaseModel):
    ready_for_visual_render: bool
    next_module: str


class AssetResolverResponse(BaseModel):
    status: AssetResolverStatus
    data: AssetResolverData
    summary: AssetResolverSummary
    handoff: AssetResolverHandoff

