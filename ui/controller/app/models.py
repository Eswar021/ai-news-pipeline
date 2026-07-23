from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
STAGE_NAMES = ("collect", "content", "voiceover", "visuals")
Operation = Literal["new", "resume", "retry"]
StageName = Literal["collect", "content", "voiceover", "visuals"]


def _slug(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or not SLUG_RE.fullmatch(normalized) or normalized in {".", ".."}:
        raise ValueError(f"{label} must contain only letters, numbers, dot, dash, or underscore")
    return normalized


class RunPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Operation = "new"
    run_id: str | None = None
    profile: str | None = None
    environment: str | None = None
    target_stage: StageName = "content"
    config_mode: Literal["live", "frozen"] = "live"
    script_source: Literal["auto", "app", "native", "chatgpt"] = "app"
    synthesis_mode: Literal["preview", "final"] = "preview"
    voiceover_variant: str | None = None
    plan_source: Literal["generate", "chatgpt"] = "generate"
    render_mode: Literal["preview", "final"] = "preview"
    render_backend: Literal["remotion", "hyperframes"] | None = None
    from_module: str | None = None
    stop_after: str | None = None
    selected_scene_ids: list[str] = Field(default_factory=list, max_length=100)
    selected_story_ids: list[str] = Field(default_factory=list, max_length=100)
    skip_metadata_finalization: bool = False
    skip_publish_handoff: bool = False
    confirm_provider_costs: bool = False
    confirm_final_media: bool = False

    @field_validator(
        "run_id",
        "profile",
        "environment",
        "voiceover_variant",
        "from_module",
        "stop_after",
    )
    @classmethod
    def slugs_must_be_safe(cls, value: str | None, info) -> str | None:
        return _slug(value, info.field_name)

    @field_validator("selected_scene_ids", "selected_story_ids")
    @classmethod
    def identifiers_must_be_safe(cls, values: list[str], info) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = _slug(value, info.field_name)
            if item and item not in normalized:
                normalized.append(item)
        return normalized


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    plan: RunPlan

    @field_validator("request_id")
    @classmethod
    def request_id_must_be_safe(cls, value: str) -> str:
        normalized = _slug(value, "request_id")
        assert normalized is not None
        if len(normalized) > 100:
            raise ValueError("request_id is too long")
        return normalized


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    expected_sha256: str
    text: str = Field(max_length=1_000_000)
    change_summary: str = Field(min_length=3, max_length=300)
    confirm_write: bool = False

    @field_validator("path")
    @classmethod
    def path_must_be_relative_yaml(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        if (
            not normalized
            or normalized.startswith("/")
            or "\x00" in normalized
            or ".." in normalized.split("/")
            or not normalized.lower().endswith((".yaml", ".yml"))
        ):
            raise ValueError("path must name an existing YAML file beneath src/pipeline/config")
        return normalized

    @field_validator("expected_sha256")
    @classmethod
    def hash_must_be_hex(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", normalized):
            raise ValueError("expected_sha256 must be a SHA-256 digest")
        return normalized


class ReviewNoteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "needs_changes", "approved"] = "open"
    body: str = Field(default="", max_length=30_000)
