from __future__ import annotations

from hashlib import sha1
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import StorySourceBriefOutput
from .utils import clean_text, story_id


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

class TruthItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    truth_id: str
    record_key: str
    truth_type: TruthType
    source_text: str
    source_title: str
    source_url: str
    source_name: str
    source_relationship: str
    source_field: str
    source_order: int
    value_text: str = ""
    claim_frame: ClaimFrame
    editorial_use: str
    classification_basis: Literal["llm_semantic_brief"] = "llm_semantic_brief"


class StoryTruthIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    items: list[TruthItem]
    semantic_source_brief: dict[str, Any]
    full_records: list[dict[str, Any]] = Field(default_factory=list)


def build_story_truth_index(
    story: dict[str, Any],
    source_brief: StorySourceBriefOutput | dict[str, Any],
) -> StoryTruthIndex:
    """Build provenance IDs from an LLM brief without interpreting source meaning in code."""

    sid = story_id(story)
    brief = (
        source_brief
        if isinstance(source_brief, StorySourceBriefOutput)
        else StorySourceBriefOutput.model_validate(source_brief)
    )
    if clean_text(brief.story_id) != sid:
        raise ValueError(f"source brief story_id {brief.story_id!r} does not match {sid!r}")

    records = [dict(record) for record in story.get("records", []) if isinstance(record, dict)]
    records_by_key = {
        clean_text(record.get("record_key")): record
        for record in records
        if clean_text(record.get("record_key"))
    }
    for boundary in brief.meaning_boundaries:
        unknown_record_keys = sorted(
            clean_text(record_key)
            for record_key in boundary.record_keys
            if clean_text(record_key) not in records_by_key
        )
        if unknown_record_keys:
            raise ValueError(
                f"source brief meaning boundary used record_key outside {sid}: {unknown_record_keys}"
            )
    items: list[TruthItem] = []
    for source_order, detail in enumerate(brief.distinctive_details, start=1):
        record_key = clean_text(detail.record_key)
        record = records_by_key.get(record_key)
        if record is None:
            raise ValueError(f"source brief used record_key outside {sid}: {record_key!r}")
        source_note = clean_text(detail.source_note)
        value_text = clean_text(detail.value_text)

        signature = (
            record_key,
            str(source_order),
            detail.detail_type,
            source_note.casefold(),
            value_text.casefold(),
        )
        digest = sha1("|".join((sid, *signature)).encode("utf-8")).hexdigest()[:12]
        items.append(
            TruthItem(
                truth_id=f"truth_{digest}",
                record_key=record_key,
                truth_type=detail.detail_type,
                source_text=source_note,
                source_title=clean_text(record.get("title")),
                source_url=_first_url(record),
                source_name=clean_text(record.get("source_name") or record.get("source")),
                source_relationship=clean_text(record.get("source_relationship")) or "unknown",
                source_field="semantic_source_brief",
                source_order=source_order,
                value_text=value_text,
                claim_frame=detail.claim_frame,
                editorial_use=clean_text(detail.editorial_use),
            )
        )

    return StoryTruthIndex(
        story_id=sid,
        items=items,
        semantic_source_brief=brief.model_dump(mode="json"),
        full_records=records,
    )


def build_story_truth_indexes(
    stories: list[dict[str, Any]],
    source_briefs: list[StorySourceBriefOutput | dict[str, Any]],
) -> list[StoryTruthIndex]:
    briefs_by_story = {
        clean_text(
            brief.story_id if isinstance(brief, StorySourceBriefOutput) else brief.get("story_id")
        ): brief
        for brief in source_briefs
    }
    return [build_story_truth_index(story, briefs_by_story[story_id(story)]) for story in stories]


def compact_truth_index(
    index: StoryTruthIndex | dict[str, Any],
    *,
    max_items: int | None = None,
    priority_truth_ids: list[str] | set[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return every semantic detail; legacy limits are rejected rather than silently truncating context."""

    raw = index.model_dump(mode="json") if isinstance(index, StoryTruthIndex) else dict(index)
    items = [dict(item) for item in raw.get("items") or [] if isinstance(item, dict)]
    if max_items is not None and len(items) > max_items:
        raise ValueError(
            "Semantic source details cannot be truncated. Increase the explicit context resource limit "
            "or use a model with a larger context window."
        )
    priorities = {clean_text(value) for value in priority_truth_ids if clean_text(value)}
    items.sort(key=lambda item: (0 if clean_text(item.get("truth_id")) in priorities else 1))
    return {
        "story_id": clean_text(raw.get("story_id")),
        "items": items,
        "semantic_source_brief": dict(raw.get("semantic_source_brief") or {}),
    }


def truth_item_map(index: StoryTruthIndex | dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = compact_truth_index(index)
    return {
        clean_text(item.get("truth_id")): item
        for item in raw["items"]
        if clean_text(item.get("truth_id"))
    }


def _first_url(record: dict[str, Any]) -> str:
    for key in ("url", "source_url", "canonical_url", "resolved_url"):
        value = clean_text(record.get(key))
        if value.startswith(("http://", "https://")):
            return value
    return ""
