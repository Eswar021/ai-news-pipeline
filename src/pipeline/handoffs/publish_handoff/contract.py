from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RunInfo(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def require_run_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id is required")
        return value.strip()


class PublishHandoffConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: str | None = None
    require_ready_inputs: bool = True


class PublishHandoffInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_context: dict[str, Any]
    video_packaging: dict[str, Any]
    script_generation: dict[str, Any]
    metadata_finalizer: dict[str, Any]
    voiceover: dict[str, Any]
    video_assembly: dict[str, Any]
    visual_review: dict[str, Any] | None = None


class PublishHandoffRequest(BaseModel):
    run: RunInfo
    config: PublishHandoffConfig = Field(default_factory=PublishHandoffConfig)
    input: PublishHandoffInput

    @model_validator(mode="after")
    def required_inputs_must_be_ready(self) -> "PublishHandoffRequest":
        if not self.config.require_ready_inputs:
            return self
        for name in ("video_packaging", "script_generation", "metadata_finalizer", "video_assembly"):
            envelope = getattr(self.input, name)
            if envelope.get("status") != "ok":
                raise ValueError(f"input.{name}.status must be ok")
        if self.input.visual_review is not None and self.input.visual_review.get("status") != "ok":
            raise ValueError("input.visual_review.status must be ok when supplied")
        voiceover = self.input.voiceover
        if voiceover.get("status") == "ok":
            return self
        package = voiceover.get("voiceover_package") or (voiceover.get("data") or {}).get("voiceover_package") or voiceover
        if package.get("status") != "ready":
            raise ValueError("input.voiceover must be an ok envelope or ready voiceover package")
        return self
