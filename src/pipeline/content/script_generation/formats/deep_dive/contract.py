"""Deep-dive script contract.

Reuses the shared script config/base, input envelope, output contracts, run, and
response pieces; adds deep-dive writing guidance (intro/angle/closing), the
config, request, and package.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...shared.contract import (  # noqa: F401
    BaseScriptConfig,
    FullScriptStatsContract,
    ScriptAudioPlanContract,
    ScriptChecksContract,
    ScriptGenerationHandoff,
    ScriptGenerationInput,
    ScriptGenerationRun,
    ScriptGenerationStatus,
    ScriptGenerationSummary,
    ScriptSectionContract,
    SectionWritingGuidance,
)
from .config import DEFAULT_MAX_ANGLE_SECTIONS, DEFAULT_MIN_ANGLE_SECTIONS


class DeepDiveWritingGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intro: SectionWritingGuidance = Field(
        default_factory=lambda: SectionWritingGuidance(
            suggested_words=70,
            beat_guidance="Use two or three purposeful beats.",
            editorial_goal="Hook the viewer on why this one topic is worth several minutes, and promise a clear payoff.",
        )
    )
    angle: SectionWritingGuidance = Field(
        default_factory=lambda: SectionWritingGuidance(
            suggested_words=200,
            beat_guidance="Use as many distinct beats as the angle naturally needs; open with a bridge from the previous angle.",
            editorial_goal="Advance one facet of the topic with concrete detail, a plain-language model, and a reason it matters.",
        )
    )
    closing: SectionWritingGuidance = Field(
        default_factory=lambda: SectionWritingGuidance(
            suggested_words=60,
            beat_guidance="Use one or two concise beats.",
            editorial_goal="Land the single argument, give the honest takeaway, and end naturally without re-listing every angle.",
        )
    )


class DeepDiveScriptConfig(BaseScriptConfig):
    writing_guidance: DeepDiveWritingGuidance = Field(default_factory=DeepDiveWritingGuidance)
    min_angle_sections: int = DEFAULT_MIN_ANGLE_SECTIONS
    max_angle_sections: int = DEFAULT_MAX_ANGLE_SECTIONS

    @field_validator("min_angle_sections", "max_angle_sections")
    @classmethod
    def angle_bounds_must_be_positive(cls, value: int) -> int:
        if value < 1 or value > 12:
            raise ValueError("deep_dive angle-section bounds must be between 1 and 12")
        return value

    @model_validator(mode="after")
    def angle_bounds_must_be_ordered(self) -> "DeepDiveScriptConfig":
        if self.min_angle_sections > self.max_angle_sections:
            raise ValueError("deep_dive.min_angle_sections must be <= max_angle_sections")
        return self


class ScriptGenerationRequest(BaseModel):
    run: ScriptGenerationRun
    config: DeepDiveScriptConfig
    input: ScriptGenerationInput


class DeepDiveScriptPackage(BaseModel):
    model_config = ConfigDict(extra="allow")

    package_type: Literal["deep_dive_script"]
    selected_format: Literal["deep_dive"]
    generation_source: Literal["native_app"]
    provenance: dict[str, Any]
    generation_strategy: str
    duration_policy: dict[str, Any] = Field(default_factory=dict)
    topic_story_id: str = ""
    angle_count: int = 0
    selected_story_ids: list[str] = Field(default_factory=list)
    section_plan: list[dict[str, Any]] = Field(default_factory=list)
    story_truth_indexes: list[dict[str, Any]] = Field(default_factory=list)
    story_context_packets: list[dict[str, Any]] = Field(default_factory=list)
    sections: list[ScriptSectionContract]
    full_script: str
    full_script_stats: FullScriptStatsContract
    audio_plan: ScriptAudioPlanContract
    checks: ScriptChecksContract


class ScriptGenerationData(BaseModel):
    run_id: str
    generated_at: str
    selected_format: str
    script_package: DeepDiveScriptPackage


class ScriptGenerationResponse(BaseModel):
    status: ScriptGenerationStatus
    data: ScriptGenerationData
    summary: ScriptGenerationSummary
    handoff: ScriptGenerationHandoff
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
