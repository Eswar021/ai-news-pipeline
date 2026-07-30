from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator


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
BeatFunction = Literal[
    "story_hook",
    "setup",
    "reveal",
    "explanation",
    "example",
    "reaction",
    "comic_release",
    "consequence",
    "caveat",
    "payoff",
    "bridge",
]
CreativeDevice = Literal[
    "none",
    "analogy",
    "contrast",
    "rhetorical_question",
    "hypothetical",
    "observational_humor",
    "self_aware_humor",
    "callback",
]
StoryEngine = Literal[
    "contradiction",
    "surprise",
    "problem_solution",
    "practical_consequence",
    "competition",
    "human_behavior",
    "technical_mechanism",
    "strategic_shift",
    "cautionary_failure",
]
EpisodeShape = Literal["shared_tension", "curated_roundup"]
TruthType = Literal[
    "event",
    "metric",
    "result",
    "mechanism",
    "quote",
    "limitation",
    "example",
    "context",
]
ClaimFrame = Literal[
    "reported_fact",
    "measured_result",
    "source_claim",
    "opinion",
    "forecast",
    "allegation",
    "planned_or_proposed",
]
DeliveryPace = Literal["deliberate", "measured", "conversational", "brisk", "rapid"]
DeliveryEnergy = Literal["restrained", "warm", "engaged", "animated", "punchy"]
DeliveryPause = Literal["none", "micro", "short", "full_beat"]


class SourceDetailDraft(BaseModel):
    """A semantically selected note attributed to one assigned source record."""

    model_config = ConfigDict(extra="forbid")

    record_key: str
    detail_type: TruthType
    source_note: str = Field(
        description="A concise source-backed note in the researcher's own words."
    )
    value_text: str = Field(
        description="A useful metric or short quote selected by the researcher, or an empty string when not applicable."
    )
    claim_frame: ClaimFrame
    editorial_use: str

    @field_validator("record_key", "source_note", "editorial_use")
    @classmethod
    def required_source_detail_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source detail record_key, source_note, and editorial_use must not be empty")
        return value.strip()


class SourceMeaningBoundaryDraft(BaseModel):
    """A source-derived relationship that later creative stages must not strengthen."""

    model_config = ConfigDict(extra="forbid")

    record_keys: list[str] = Field(
        description="Assigned record keys that establish this boundary."
    )
    subject: str = Field(
        description="The entity, artifact, result, claim, or event whose state needs to remain distinct."
    )
    established_state: str = Field(
        description="What the supplied records establish now, including meaningful attribution."
    )
    must_not_be_upgraded_to: str = Field(
        description="A stronger state or relationship the records do not establish."
    )
    attribution: str = Field(
        description="Who supplies the claim or status, or how the relationship is known."
    )

    @field_validator("record_keys")
    @classmethod
    def boundary_record_keys_must_not_be_empty(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if not cleaned:
            raise ValueError("source meaning boundary record_keys must not be empty")
        return list(dict.fromkeys(cleaned))

    @field_validator("subject", "established_state", "must_not_be_upgraded_to", "attribution")
    @classmethod
    def boundary_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source meaning boundary text fields must not be empty")
        return value.strip()


class StorySourceBriefOutput(BaseModel):
    """Semantic reading notes built from the complete records for one story."""

    model_config = ConfigDict(extra="forbid")

    story_id: str
    source_synopsis: str
    central_event: str
    source_relationship_summary: str
    distinctive_details: list[SourceDetailDraft] = Field(min_length=1)
    meaning_boundaries: list[SourceMeaningBoundaryDraft] = Field(
        description=(
            "Material current-versus-planned, claim-versus-result, terminology, attribution, or causality "
            "boundaries; return an empty list only when the records establish no such distinction."
        )
    )
    tensions_and_caveats: list[str]
    creator_opportunities: list[str]

    @field_validator("story_id", "source_synopsis", "central_event", "source_relationship_summary")
    @classmethod
    def source_brief_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("story source brief text fields must not be empty")
        return value.strip()


def story_source_brief_output_model(
    *,
    required_story_id: str,
    allowed_record_keys: list[str],
) -> type[StorySourceBriefOutput]:
    """Bind source-research identity fields to the records assigned to one call."""

    story_id = required_story_id.strip()
    record_keys = list(
        dict.fromkeys(key.strip() for key in allowed_record_keys if isinstance(key, str) and key.strip())
    )
    if not story_id:
        raise ValueError("required_story_id must not be empty")
    if not record_keys:
        raise ValueError(f"{story_id} has no source record keys")

    story_id_literal = Literal.__getitem__((story_id,))
    record_key_literal = Literal.__getitem__(tuple(record_keys))
    assigned_detail_model = create_model(
        "AssignedSourceDetailDraft",
        __base__=SourceDetailDraft,
        record_key=(
            record_key_literal,
            Field(description="One exact record_key from allowed_source_record_keys."),
        ),
    )
    assigned_boundary_model = create_model(
        "AssignedSourceMeaningBoundaryDraft",
        __base__=SourceMeaningBoundaryDraft,
        record_keys=(
            list[record_key_literal],
            Field(description="Exact record keys from allowed_source_record_keys."),
        ),
    )
    return create_model(
        "AssignedStorySourceBriefOutput",
        __base__=StorySourceBriefOutput,
        story_id=(
            story_id_literal,
            Field(description="The exact required_story_id supplied in the task payload."),
        ),
        distinctive_details=(list[assigned_detail_model], Field(min_length=1)),
        meaning_boundaries=(
            list[assigned_boundary_model],
            Field(
                description=(
                    "Material source meaning boundaries using only assigned record keys; return an empty "
                    "list when no such boundary exists."
                )
            ),
        ),
    )


class DeliveryDirectionDraft(BaseModel):
    """Provider-neutral performance intent kept outside spoken narration."""

    model_config = ConfigDict(extra="forbid")

    performance_intent: str = Field(
        description="How this spoken beat should land for the viewer, expressed as a concise director note."
    )
    emotional_color: str = Field(
        description="The natural emotional color of the beat, such as curious, amused, skeptical, urgent, or reflective."
    )
    pace: DeliveryPace
    energy: DeliveryEnergy
    emphasis_phrases: list[str] = Field(
        description="Exact phrases from narration_text that deserve audible emphasis; return an empty list when none do."
    )
    pause_after: DeliveryPause

    @field_validator("performance_intent", "emotional_color")
    @classmethod
    def delivery_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("delivery direction text must not be empty")
        return value.strip()


class StoryBeatDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_type: BeatType
    beat_function: BeatFunction
    narration_text: str
    support_truth_ids: list[str] = Field(
        description="Truth IDs supporting externally verifiable claims; empty is valid for pure opinion or creative language."
    )
    creative_device: CreativeDevice
    source_record_keys: list[str] = Field(
        description="Assigned source record keys grounding the beat; use an empty list only for non-factual transitions."
    )
    delivery_direction: DeliveryDirectionDraft

    @field_validator("narration_text")
    @classmethod
    def narration_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("beat narration_text must not be empty")
        return value.strip()


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


class StorySegmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    display_title: str
    story_thesis: str
    viewer_takeaway: str
    beats: list[StoryBeatDraft]


ReviewIssueCode = Literal[
    "weak_hook",
    "flat_story_arc",
    "article_readout",
    "generic_language",
    "unclear_explanation",
    "missing_viewer_payoff",
    "weak_or_forced_personality",
    "poor_spoken_rhythm",
    "repetition",
    "unsupported_claim",
    "source_meaning_distortion",
    "fabricated_or_inexact_quote",
    "missing_attribution",
    "connector_target_mismatch",
    "intro_body_repetition",
]


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ReviewIssueCode
    explanation: str
    affected_beat_ids: list[str] = Field(
        description="One or more review-local beat/component IDs supplied in the task payload."
    )

    @field_validator("explanation")
    @classmethod
    def explanation_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("review issue explanation must not be empty")
        return value.strip()

    @field_validator("affected_beat_ids")
    @classmethod
    def affected_beat_ids_must_not_be_empty(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if not cleaned:
            raise ValueError("review issue affected_beat_ids must contain at least one ID")
        return list(dict.fromkeys(cleaned))


class StoryReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rewrite_required: bool
    issues: list[ReviewIssue]
    revised_segment: StorySegmentOutput | None

    @model_validator(mode="after")
    def keep_or_rewrite_must_be_consistent(self) -> "StoryReviewOutput":
        if not self.rewrite_required and (self.issues or self.revised_segment is not None):
            raise ValueError("rewrite_required=false requires issues=[] and revised_segment=null")
        if self.rewrite_required and (not self.issues or self.revised_segment is None):
            raise ValueError("rewrite_required=true requires material issues and a revised_segment")
        return self


class BookendBeatDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_type: Literal["hook", "intro", "conclusion", "takeaway"]
    narration_text: str
    delivery_direction: DeliveryDirectionDraft


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
