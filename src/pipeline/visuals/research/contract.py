from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


LLMProvider = Literal["openai", "gemini", "lmstudio", "moonshot"]
AssetType = Literal[
    "source_page",
    "source_image",
    "source_video",
    "logo",
    "official_product_interface",
    "source_figure",
    "context_photo",
    "broll_video",
    "code_graphic",
    "kinetic_text",
]


class VisualResearchRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class ProviderOptions(BaseModel):
    model_config = ConfigDict(extra="allow")

    thinking: Literal["enabled", "disabled"] | None = None
    omit_temperature: bool = False
    request_timeout_seconds: float = Field(default=300.0, ge=10.0, le=1800.0)


class StructuredOutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["json_schema", "function_calling", "json_mode"] = "json_schema"
    strict: bool = True


class VisualResearchConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: LLMProvider
    model: str
    prompt_version: str = "v1"
    temperature: float = 0.2
    base_url: str | None = None
    provider_options: ProviderOptions = Field(default_factory=ProviderOptions)
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)
    max_attempts: int = 2
    worker_count: int = 2
    include_full_records: bool = True
    external_search_enabled: bool = False
    collectable_asset_types: list[AssetType] = Field(
        default_factory=lambda: [
            "source_page",
            "source_image",
            "source_video",
            "logo",
            "official_product_interface",
            "source_figure",
            "context_photo",
            "broll_video",
            "code_graphic",
            "kinetic_text",
        ]
    )
    active_render_kinds: list[str] = Field(default_factory=list)

    @field_validator("model", "prompt_version")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.model and config.prompt_version must not be empty")
        return value.strip()

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_valid(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("config.temperature must be between 0 and 2")
        return value

    @field_validator("max_attempts")
    @classmethod
    def max_attempts_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 4:
            raise ValueError("config.max_attempts must be between 1 and 4")
        return value

    @field_validator("worker_count")
    @classmethod
    def worker_count_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 8:
            raise ValueError("config.worker_count must be between 1 and 8")
        return value

    @model_validator(mode="after")
    def full_records_are_required(self) -> "VisualResearchConfig":
        if not self.include_full_records:
            raise ValueError("config.include_full_records must be true")
        if not self.collectable_asset_types:
            raise ValueError("config.collectable_asset_types must not be empty")
        if not self.active_render_kinds:
            raise ValueError("config.active_render_kinds must not be empty")
        return self


class ScriptGenerationData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    script_package: dict[str, Any]


class ScriptGenerationEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    data: ScriptGenerationData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VideoPackagingData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    selected_format: str
    video_packet: dict[str, Any]


class VideoPackagingEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    data: VideoPackagingData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VisualResearchInput(BaseModel):
    script_generation: ScriptGenerationEnvelope
    video_packaging: VideoPackagingEnvelope

    @model_validator(mode="after")
    def upstream_results_must_be_ready(self) -> "VisualResearchInput":
        if self.script_generation.status != "ok":
            raise ValueError("input.script_generation.status must be ok")
        if self.video_packaging.status != "ok":
            raise ValueError("input.video_packaging.status must be ok")
        return self


class VisualResearchRequest(BaseModel):
    run: VisualResearchRun
    config: VisualResearchConfig
    input: VisualResearchInput


class SequenceResearchNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence_label: str = Field(description="A concise internal label for this visual sequence.")
    beat_ids: list[str] = Field(description="Canonical adjacent beat IDs covered by this sequence.")
    visual_arc: str = Field(description="How the adjacent shots establish, develop, and pay off the idea.")
    preferred_shot_progression: list[str] = Field(
        description="Two to four short shot ideas in viewing order, not timestamps."
    )
    continuity_motif: str = Field(description="A visual element that keeps the shots feeling connected.")


class AssetNeedDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_ids: list[str] = Field(description="Canonical beat IDs this need can serve.")
    sequence_role: Literal["establish", "develop", "payoff", "bridge"]
    subject: str = Field(description="The concrete person, product, interface, document, place, or concept to show.")
    action_or_detail: str = Field(description="The exact action, state, or detail the visual should depict.")
    editorial_purpose: str = Field(description="Why this visual helps the viewer understand the narration.")
    preferred_asset_types: list[AssetType]
    preferred_source_record_keys: list[str]
    must_show: list[str]
    must_avoid: list[str]
    suggested_search_queries: list[str]
    availability_strategy: Literal[
        "selected_source",
        "verified_identity",
        "external_if_enabled",
        "code_generated",
    ]


class StoryVisualResearchDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    visual_thesis: str = Field(description="One sentence describing the visual way to tell this story.")
    sequence_notes: list[SequenceResearchNote]
    asset_needs: list[AssetNeedDraft]
    unresolved_gaps: list[str]
    warnings: list[str]


class VisualResearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["ok", "failed"]
    data: dict[str, Any]
    summary: dict[str, Any]
    handoff: dict[str, Any]
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)


def visual_research_identity_payload(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "research_version": package.get("research_version"),
        "story_research": package.get("story_research", []),
    }
