from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


BeatType = Literal[
    "hook",
    "transition",
    "what_changed",
    "explanation",
    "example",
    "why_it_matters",
    "caveat",
    "takeaway",
    "intro",
    "conclusion",
]
VisualIntent = Literal[
    "story_title",
    "source_proof",
    "entity_intro",
    "product_demo",
    "metric_explainer",
    "process_explainer",
    "comparison",
    "context_media",
    "transition",
    "takeaway",
]
AssetType = Literal[
    "source_page",
    "product_ui",
    "logo",
    "photo",
    "video",
    "chart",
    "diagram",
    "kinetic_text",
]


class VisualBriefDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(description="What the viewer should understand from the visual while this beat is spoken.")
    visual_intent: VisualIntent
    preferred_asset_types: list[AssetType] = Field(
        description="Ordered asset families that can communicate this beat; return an empty list when none apply."
    )
    must_show: list[str] = Field(description="Concrete visual requirements; return an empty list when none apply.")
    on_screen_text: str = Field(description="A short optional phrase, never a narration paragraph.")
    avoid: list[str] = Field(description="Visual mistakes to avoid; return an empty list when none apply.")

    @field_validator("purpose")
    @classmethod
    def purpose_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("visual brief purpose must not be empty")
        return value.strip()


class StoryBeatDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_type: BeatType
    narration_text: str
    source_record_keys: list[str] = Field(
        description="Assigned source record keys grounding the beat; use an empty list only for non-factual transitions."
    )
    visual_brief: VisualBriefDraft

    @field_validator("narration_text")
    @classmethod
    def narration_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("beat narration_text must not be empty")
        return value.strip()


class StoryDirectionBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    story_promise: str
    angle: str
    must_cover: list[str] = Field(description="Required story points; return an empty list only when none are required.")
    avoid: list[str] = Field(description="Story-specific pitfalls; return an empty list only when none apply.")
    transition_in: str
    transition_out: str


class EpisodeDirectorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_thesis: str
    viewer_promise: str
    hook_strategy: str
    pacing_strategy: str
    ordered_story_ids: list[str]
    story_briefs: list[StoryDirectionBrief]


class StorySegmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    display_title: str
    story_thesis: str
    viewer_takeaway: str
    beats: list[StoryBeatDraft]


class StoryReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_apply_revision: bool
    diagnosis: list[str] = Field(description="Concise gate diagnoses; return an empty list when no issue remains.")
    revised_segment: StorySegmentOutput


class BookendBeatDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_type: Literal["hook", "intro", "conclusion", "takeaway"]
    narration_text: str
    visual_brief: VisualBriefDraft


class StoryConnectorDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    display_title: str
    transition_line: str
    title_card_subtitle: str


class BookendOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intro_beats: list[BookendBeatDraft]
    story_connectors: list[StoryConnectorDraft]
    closing_beats: list[BookendBeatDraft]
    continuity_notes: list[str] = Field(description="Episode continuity notes; return an empty list when none are needed.")


class BookendReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_apply_revision: bool
    diagnosis: list[str] = Field(description="Concise gate diagnoses; return an empty list when no issue remains.")
    revised_bookends: BookendOutput
