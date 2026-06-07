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


class PublishHandoffConfig(BaseModel):
    output_dir: Optional[str] = None
    require_approved: bool = True


class PublishHandoffInput(BaseModel):
    manifest: dict[str, Any]
    verification_package: dict[str, Any]


class PublishHandoffRequest(BaseModel):
    run: RunInfo
    config: PublishHandoffConfig = Field(default_factory=PublishHandoffConfig)
    input: PublishHandoffInput
