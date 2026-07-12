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


class ChatGPTScriptParserConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    diagnostic_words_per_minute: int = 140
    title_card_seconds: float = 2.8

    @field_validator("diagnostic_words_per_minute")
    @classmethod
    def words_per_minute_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("config.diagnostic_words_per_minute must be positive")
        return value

    @model_validator(mode="after")
    def title_card_timing_must_be_valid(self) -> "ChatGPTScriptParserConfig":
        if self.title_card_seconds < 1.5 or self.title_card_seconds > 5:
            raise ValueError("config.title_card_seconds must be between 1.5 and 5")
        return self


class VideoPackagingData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    selected_format: str
    script_app: str | None = None
    video_packet: dict[str, Any]


class VideoPackagingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    data: VideoPackagingData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class ParserInput(BaseModel):
    response_text: str
    video_packaging: VideoPackagingEnvelope
    script_source: str | None = None

    @field_validator("response_text")
    @classmethod
    def response_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("input.response_text must not be empty")
        return value


class ChatGPTScriptParserRequest(BaseModel):
    run: RunInfo
    config: ChatGPTScriptParserConfig = Field(default_factory=ChatGPTScriptParserConfig)
    input: ParserInput

    @model_validator(mode="after")
    def upstream_must_be_usable(self) -> "ChatGPTScriptParserRequest":
        if self.input.video_packaging.status != "ok":
            raise ValueError("input.video_packaging.status must be ok")
        packet = self.input.video_packaging.data.video_packet
        if not packet:
            raise ValueError("input.video_packaging.data.video_packet is missing")
        if packet.get("selected_format") != "roundup":
            raise NotImplementedError("chatgpt_script_parser currently supports only roundup packets")
        if not isinstance(packet.get("stories"), list) or not packet["stories"]:
            raise ValueError("video_packet.stories must contain selected stories")
        return self
