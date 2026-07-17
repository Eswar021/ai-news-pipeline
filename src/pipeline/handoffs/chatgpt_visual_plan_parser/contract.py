from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RunInfo(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class ChatGPTVisualPlanParserConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    scene_policy: dict[str, Any] = Field(default_factory=dict)
    visual_capabilities: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)
    require_complete_timeline: bool = True
    gap_tolerance_seconds: float = 0.5
    max_automatic_timing_repair_seconds: float = 0.5
    require_real_anchor_per_story: bool = False
    output_dir: str | None = None

    @field_validator("gap_tolerance_seconds")
    @classmethod
    def gap_tolerance_must_be_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("config.gap_tolerance_seconds must be non-negative")
        return value

    @field_validator("max_automatic_timing_repair_seconds")
    @classmethod
    def automatic_repair_limit_must_be_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("config.max_automatic_timing_repair_seconds must be non-negative")
        return value


class VideoPackagingData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    selected_format: str | None = None
    video_packet: dict[str, Any]


class VideoPackagingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: VideoPackagingData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class ParserInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    response_text: str
    video_packaging: VideoPackagingEnvelope
    script_generation: dict[str, Any]
    script_source: str | None = None
    voiceover: dict[str, Any] | None = None
    asset_catalog: dict[str, Any] | None = None

    @field_validator("response_text")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("input.response_text must not be empty")
        return value


class ChatGPTVisualPlanParserRequest(BaseModel):
    run: RunInfo
    config: ChatGPTVisualPlanParserConfig = Field(default_factory=ChatGPTVisualPlanParserConfig)
    input: ParserInput

    @model_validator(mode="after")
    def upstream_must_be_usable(self) -> "ChatGPTVisualPlanParserRequest":
        if self.input.video_packaging.status and self.input.video_packaging.status != "ok":
            raise ValueError("input.video_packaging.status must be ok")
        packet = self.input.video_packaging.data.video_packet
        if not isinstance(packet, dict) or not packet:
            raise ValueError("input.video_packaging.data.video_packet is missing")
        if self.input.script_generation.get("status") != "ok":
            raise ValueError("input.script_generation.status must be ok")
        script_package = (self.input.script_generation.get("data") or {}).get("script_package") or {}
        if not str(script_package.get("full_script", "")).strip():
            raise ValueError("input.script_generation.data.script_package.full_script is missing or empty")
        return self

    @model_validator(mode="after")
    def catalog_must_be_ready_when_required(self) -> "ChatGPTVisualPlanParserRequest":
        if not self.config.require_real_anchor_per_story:
            return self
        if not isinstance(self.input.asset_catalog, dict) or self.input.asset_catalog.get("status") != "ok":
            raise ValueError("input.asset_catalog.status must be ok when real anchors are required")
        catalog = (self.input.asset_catalog.get("data") or {}).get("visual_asset_catalog")
        if not isinstance(catalog, dict) or not catalog:
            raise ValueError("input.asset_catalog.data.visual_asset_catalog is missing")
        return self
