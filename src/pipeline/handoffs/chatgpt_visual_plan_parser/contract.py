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
    require_complete_timeline: bool = True
    gap_tolerance_seconds: float = 0.5
    output_dir: str | None = None

    @field_validator("gap_tolerance_seconds")
    @classmethod
    def gap_tolerance_must_be_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("config.gap_tolerance_seconds must be non-negative")
        return value


class VideoPackagingData(BaseModel):
    model_config = ConfigDict(extra="allow")

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
    script_text: str
    script_source: str | None = None
    voiceover: dict[str, Any] | None = None

    @field_validator("response_text", "script_text")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("input.response_text and input.script_text must not be empty")
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
        return self
