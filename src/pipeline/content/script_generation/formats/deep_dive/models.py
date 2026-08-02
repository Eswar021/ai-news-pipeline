"""Deep-dive LLM output models.

Format-agnostic beat/segment/source/review models come from
script_generation.shared.models and are re-exported. Deep-dive adds an
angle-planning director and intro/closing bookends (no inter-story connectors —
a single topic bridges between its own angle sections).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...shared.models import (  # noqa: F401 - re-exported for deep_dive imports
    BeatFunction,
    BeatType,
    BookendBeatDraft,
    ClaimFrame,
    CreativeDevice,
    DeliveryDirectionDraft,
    DeliveryEnergy,
    DeliveryPace,
    DeliveryPause,
    ReviewIssue,
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


class DeepDiveAngleBrief(BaseModel):
    """Direction for one angle section of the single deep-dive topic."""

    model_config = ConfigDict(extra="forbid")

    angle_id: str = Field(description="Stable angle id supplied in the task payload, e.g. 'angle_01'.")
    angle_label: str = Field(description="Short on-screen section title for this angle, e.g. 'How the attack works'.")
    angle_engine: StoryEngine
    angle_promise: str = Field(description="What this specific angle makes the viewer understand or feel.")
    hook_or_bridge: str = Field(
        description="For the first angle, the opening hook idea; for later angles, how it bridges naturally from the previous angle."
    )
    tension: str
    reveal_or_payoff: str
    viewer_stakes: str
    specific_detail_anchor: str = Field(
        description="The concrete supplied detail, mechanism, contrast, number, or consequence this angle is built on."
    )
    source_meaning_boundaries: list[str] = Field(
        description="Source-state and attribution boundaries the writer must preserve for this angle; empty list only when none apply."
    )
    must_communicate_truth_ids: list[str] = Field(
        description="Priority truth IDs this angle should preserve; empty list is valid when no single item is indispensable."
    )
    optional_truth_ids: list[str] = Field(description="Useful truth IDs the writer may select for this angle.")
    narrator_take: str
    explanation_goal: str
    analogy_opportunities: list[str] = Field(description="Original analogy directions; empty list when none fit.")
    humor_opportunities: list[str] = Field(description="Tasteful humor directions; empty list when humor would hurt.")
    avoid: list[str] = Field(description="Angle-specific pitfalls; empty list only when none apply.")

    @field_validator(
        "angle_id",
        "angle_label",
        "angle_promise",
        "hook_or_bridge",
        "tension",
        "reveal_or_payoff",
        "viewer_stakes",
        "specific_detail_anchor",
        "narrator_take",
        "explanation_goal",
    )
    @classmethod
    def angle_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("deep-dive angle brief text fields must not be empty")
        return value.strip()


class DeepDiveDirectorOutput(BaseModel):
    """The single-topic episode plan: a thesis plus an ordered set of angles."""

    model_config = ConfigDict(extra="forbid")

    episode_thesis: str
    viewer_promise: str
    hook_strategy: str
    pacing_strategy: str
    topic_arc: str = Field(description="How the angles progress into one coherent argument or explanation.")
    ordered_angle_ids: list[str] = Field(min_length=1)
    angle_briefs: list[DeepDiveAngleBrief] = Field(min_length=1)

    @field_validator("episode_thesis", "viewer_promise", "hook_strategy", "pacing_strategy", "topic_arc")
    @classmethod
    def director_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("deep-dive director text fields must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def angle_ids_must_be_consistent(self) -> "DeepDiveDirectorOutput":
        brief_ids = [brief.angle_id for brief in self.angle_briefs]
        if len(brief_ids) != len(set(brief_ids)):
            raise ValueError("deep-dive angle_briefs contain duplicate angle_id values")
        if set(self.ordered_angle_ids) != set(brief_ids):
            raise ValueError("deep-dive ordered_angle_ids must match the angle_briefs exactly")
        return self


class DeepDiveBookendOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intro_beats: list[BookendBeatDraft]
    closing_beats: list[BookendBeatDraft]
    continuity_notes: list[str] = Field(description="Episode continuity notes; empty list when none are needed.")


class DeepDiveBookendReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rewrite_required: bool
    issues: list[ReviewIssue]
    revised_bookends: DeepDiveBookendOutput | None

    @model_validator(mode="after")
    def keep_or_rewrite_must_be_consistent(self) -> "DeepDiveBookendReviewOutput":
        if not self.rewrite_required and (self.issues or self.revised_bookends is not None):
            raise ValueError("rewrite_required=false requires issues=[] and revised_bookends=null")
        if self.rewrite_required and (not self.issues or self.revised_bookends is None):
            raise ValueError("rewrite_required=true requires material issues and revised_bookends")
        return self
