from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GalleryRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class GalleryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: str
    force: bool = False
    backend: Literal["hyperframes", "remotion"] = "hyperframes"
    palette: str = "editorial_signal"
    width: int = 1280
    height: int = 720
    fps: int = 24
    scene_duration_seconds: float = 4.0
    worker_count: int = 4
    frame_concurrency: int = 1
    render_kinds: list[str] = Field(default_factory=list)
    recipe_ids: list[str] = Field(default_factory=list)

    @field_validator("output_dir", "palette")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("gallery paths and palette names must not be empty")
        return value

    @field_validator("width", "height", "fps", "worker_count", "frame_concurrency")
    @classmethod
    def positive_integers_required(cls, value: int) -> int:
        if value < 1:
            raise ValueError("gallery dimensions, fps, and concurrency must be positive")
        return value

    @field_validator("scene_duration_seconds")
    @classmethod
    def duration_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("config.scene_duration_seconds must be positive")
        return value


class GalleryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GalleryRequest(BaseModel):
    run: GalleryRun
    config: GalleryConfig
    input: GalleryInput = Field(default_factory=GalleryInput)
