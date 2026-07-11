from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class RunInfo(BaseModel):
    run_id: str
    generated_at: Optional[str] = None

    @field_validator("run_id")
    @classmethod
    def require_run_id(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("run.run_id is required")
        return value.strip()


class ChatGPTExporterConfig(BaseModel):
    profile: str = "auto"
    prompt_version: str = "v1"
    output_dir: Optional[str] = None


class ChatGPTExporterInput(BaseModel):
    manifest: dict[str, Any]
    artifacts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    summaries: dict[str, Any] = Field(default_factory=dict)


class ChatGPTExporterRequest(BaseModel):
    run: RunInfo
    config: ChatGPTExporterConfig = Field(default_factory=ChatGPTExporterConfig)
    input: ChatGPTExporterInput
