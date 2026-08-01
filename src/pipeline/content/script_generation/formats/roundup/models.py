"""Roundup LLM output models.

Format-agnostic models (beats, segments, source briefs, reviews) live in
script_generation.shared.models and are re-exported here so existing roundup
imports keep working. Only roundup-specific director/bookend shapes are defined
locally.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Re-exported shared models (kept importable as `from .models import X`).
from ...shared.models import (  # noqa: F401
    BeatFunction,
    BeatType,
    BookendBeatDraft,
    ClaimFrame,
    CreativeDevice,
    DeliveryDirectionDraft,
    DeliveryEnergy,
    DeliveryPace,
    DeliveryPause,
    EpisodeShape,
    ReviewIssue,
    ReviewIssueCode,
    SourceDetailDraft,
    SourceMeaningBoundaryDraft,
    StoryBeatDraft,
    StoryEngine,
    StoryReviewOutput,
    StorySegmentOutput,
    StorySourceBriefOutput,
    TruthType,
    story_source_brief_output_model,
)


class StoryDirectionBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    story_engine: StoryEngine
    story_promise: str
    hook_idea: str
    tension: str
    reveal_or_payoff: str
    viewer_stakes: str
    specific_detail_anchor: str = Field(
        description="The concrete supplied detail, mechanism, contrast, or consequence that makes this story distinctive."
    )
    source_meaning_boundary: str = Field(
        description=(
            "A concise semantic boundary the writer must preserve, especially attribution, causality, "
            "single-versus-combined evidence, measured-versus-claimed results, and current-versus-planned state."
        )
    )
    source_meaning_boundaries: list[str] = Field(
        description=(
            "All material source-state and attribution boundaries the writer must preserve; "
            "return an empty list only when no additional boundary exists beyond source_meaning_boundary."
        )
    )
    must_communicate_truth_ids: list[str] = Field(
        description=(
            "Small set of priority truth IDs the writer should preserve when they improve the story; "
            "an empty list is valid when no individual truth item is indispensable."
        )
    )
    optional_truth_ids: list[str] = Field(
        description="Useful truth IDs the storyteller may select when they improve the mini-story."
    )
    narrator_take: str
    explanation_goal: str
    analogy_opportunities: list[str] = Field(description="Original analogy directions; return an empty list when none fit.")
    humor_opportunities: list[str] = Field(description="Tasteful humor directions; return an empty list when humor would hurt.")
    humor_restraint_reason: str | None = Field(
        description="Why humor should be restrained for this story, or null when normal channel restraint is sufficient."
    )
    transition_relationship: str
    avoid: list[str] = Field(description="Story-specific pitfalls; return an empty list only when none apply.")

    @field_validator(
        "story_id",
        "story_promise",
        "hook_idea",
        "tension",
        "reveal_or_payoff",
        "viewer_stakes",
        "specific_detail_anchor",
        "source_meaning_boundary",
        "narrator_take",
        "explanation_goal",
        "transition_relationship",
    )
    @classmethod
    def direction_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("story direction text fields must not be empty")
        return value.strip()


class EpisodeDirectorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_shape: EpisodeShape
    episode_connection_reason: str
    episode_thesis: str
    viewer_promise: str
    hook_strategy: str
    pacing_strategy: str
    ordered_story_ids: list[str]
    story_briefs: list[StoryDirectionBrief]


class StoryConnectorDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_story_id: str = Field(
        description="The exact story ID introduced by both this transition line and its title card."
    )
    display_title: str
    transition_line: str
    title_card_subtitle: str
    delivery_direction: DeliveryDirectionDraft


class BookendOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intro_beats: list[BookendBeatDraft]
    story_connectors: list[StoryConnectorDraft]
    closing_beats: list[BookendBeatDraft]
    continuity_notes: list[str] = Field(description="Episode continuity notes; return an empty list when none are needed.")


class BookendReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rewrite_required: bool
    issues: list[ReviewIssue]
    revised_bookends: BookendOutput | None

    @model_validator(mode="after")
    def keep_or_rewrite_must_be_consistent(self) -> "BookendReviewOutput":
        if not self.rewrite_required and (self.issues or self.revised_bookends is not None):
            raise ValueError("rewrite_required=false requires issues=[] and revised_bookends=null")
        if self.rewrite_required and (not self.issues or self.revised_bookends is None):
            raise ValueError("rewrite_required=true requires material issues and revised_bookends")
        return self
