"""Roundup script-generation contract.

Format-agnostic config/envelope/output contracts live in
script_generation.shared.contract and are re-exported here so existing roundup
imports keep working. Only roundup-specific config/package/request/response
wrappers are defined locally.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Re-exported shared contract pieces (kept importable as `from .contract import X`).
from ...shared.contract import (  # noqa: F401
    BaseScriptConfig,
    ChannelVoiceConfig,
    ContentFilterFallbackConfig,
    DeliveryDirectionContract,
    FullScriptStatsContract,
    HumorPolicy,
    LanguagePolicy,
    LLMProvider,
    LLMRetryConfig,
    OpinionPolicy,
    ProviderOptions,
    ReviewConfig,
    RoleLLMConfig,
    ScriptAudioPlanContract,
    ScriptAudioUnitContract,
    ScriptBeatContract,
    ScriptChecksContract,
    ScriptGenerationHandoff,
    ScriptGenerationInput,
    ScriptGenerationRun,
    ScriptGenerationStatus,
    ScriptGenerationSummary,
    ScriptLLMRole,
    ScriptSectionContract,
    ScriptStyle,
    SectionWritingGuidance,
    SourceContextConfig,
    SourcePolicy,
    StorytellingConfig,
    StoryTitleCardContract,
    StructuredOutputConfig,
    VideoPacket,
    VideoPackagingData,
    VideoPackagingEnvelope,
)


class WritingGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intro: SectionWritingGuidance = Field(
        default_factory=lambda: SectionWritingGuidance(
            suggested_words=70,
            beat_guidance="Use two or three purposeful beats.",
            editorial_goal="Hook the viewer and preview the episode without listing every headline.",
        )
    )
    lead: SectionWritingGuidance = Field(
        default_factory=lambda: SectionWritingGuidance(
            suggested_words=240,
            beat_guidance="Use as many distinct beats as the explanation naturally needs.",
            editorial_goal="Explain the strongest story fully, clearly, and without padding.",
        )
    )
    major: SectionWritingGuidance = Field(
        default_factory=lambda: SectionWritingGuidance(
            suggested_words=180,
            beat_guidance="Use a compact sequence of distinct explanatory beats.",
            editorial_goal="Cover what changed, why it matters, and the useful caveat.",
        )
    )
    brief: SectionWritingGuidance = Field(
        default_factory=lambda: SectionWritingGuidance(
            suggested_words=120,
            beat_guidance="Use a few focused beats and finish once the takeaway is clear.",
            editorial_goal="Deliver the essential update without stretching limited source material.",
        )
    )
    closing: SectionWritingGuidance = Field(
        default_factory=lambda: SectionWritingGuidance(
            suggested_words=45,
            beat_guidance="Use one or two concise beats.",
            editorial_goal="Synthesize the episode and end naturally without repeating every story.",
        )
    )
    connector: SectionWritingGuidance = Field(
        default_factory=lambda: SectionWritingGuidance(
            suggested_words=8,
            beat_guidance="Use one natural spoken line.",
            editorial_goal="Introduce the next story while its title motion appears.",
        )
    )


class RoundupScriptConfig(BaseScriptConfig):
    writing_guidance: WritingGuidance = Field(default_factory=WritingGuidance)


class ScriptGenerationRequest(BaseModel):
    run: ScriptGenerationRun
    config: RoundupScriptConfig
    input: ScriptGenerationInput


class RoundupScriptPackage(BaseModel):
    model_config = ConfigDict(extra="allow")

    package_type: Literal["roundup_script"]
    selected_format: Literal["roundup"]
    generation_source: Literal["native_app", "chatgpt_handoff"]
    provenance: dict[str, Any]
    generation_strategy: str
    duration_policy: dict[str, Any] = Field(default_factory=dict)
    target_duration_seconds: int | None = None
    intro_seconds: int | None = None
    closing_seconds: int | None = None
    story_count: int = 0
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
    script_package: RoundupScriptPackage


class ScriptGenerationResponse(BaseModel):
    status: ScriptGenerationStatus
    data: ScriptGenerationData
    summary: ScriptGenerationSummary
    handoff: ScriptGenerationHandoff
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
