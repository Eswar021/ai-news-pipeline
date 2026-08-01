from __future__ import annotations

from copy import deepcopy
from typing import Any

from .source_truth import StoryTruthIndex
from ...shared.utils import clean_text, json_dumps, story_id, story_title


STORY_CONTEXT_PACKET_VERSION = "story_context_v1"


def build_story_context_packet(
    story: dict[str, Any],
    truth_index: StoryTruthIndex | dict[str, Any],
) -> dict[str, Any]:
    raw_truth = truth_index.model_dump(mode="json") if isinstance(truth_index, StoryTruthIndex) else dict(truth_index)
    records = [deepcopy(record) for record in story.get("records", []) if isinstance(record, dict)]
    packet = {
        "packet_version": STORY_CONTEXT_PACKET_VERSION,
        "story_id": story_id(story),
        "story_title": story_title(story),
        "story_identity": deepcopy(story.get("story_identity") or {}),
        "story_role": clean_text((story.get("video_segment") or {}).get("role")),
        "record_count": len(records),
        "record_keys": [clean_text(record.get("record_key")) for record in records],
        "records": records,
        "semantic_source_brief": deepcopy(raw_truth.get("semantic_source_brief") or {}),
        "story_truth_index": {
            "story_id": clean_text(raw_truth.get("story_id")),
            "items": deepcopy(raw_truth.get("items") or []),
            "semantic_source_brief": deepcopy(raw_truth.get("semantic_source_brief") or {}),
        },
    }
    packet["telemetry"] = story_context_telemetry(packet)
    return packet


def build_source_research_context(story: dict[str, Any]) -> dict[str, Any]:
    """Preserve complete selected records before any semantic source-brief call."""

    records = [deepcopy(record) for record in story.get("records", []) if isinstance(record, dict)]
    context = {
        "packet_version": STORY_CONTEXT_PACKET_VERSION,
        "story_id": story_id(story),
        "story_title": story_title(story),
        "story_identity": deepcopy(story.get("story_identity") or {}),
        "story_role": clean_text((story.get("video_segment") or {}).get("role")),
        "record_count": len(records),
        "record_keys": [clean_text(record.get("record_key")) for record in records],
        "records": records,
    }
    context["telemetry"] = story_context_telemetry(context)
    return context


def story_context_telemetry(packet: dict[str, Any]) -> dict[str, Any]:
    records = [record for record in packet.get("records", []) if isinstance(record, dict)]
    content_chars_by_record = {
        clean_text(record.get("record_key")): len(_semantic_record_text(record))
        for record in records
    }
    return {
        "packet_version": STORY_CONTEXT_PACKET_VERSION,
        "record_count": len(records),
        "record_keys": list(content_chars_by_record),
        "content_chars_by_record": content_chars_by_record,
        "content_char_count": sum(content_chars_by_record.values()),
        "serialized_char_count": len(json_dumps({key: value for key, value in packet.items() if key != "telemetry"})),
    }


def validate_context_resource_limits(
    packets: list[dict[str, Any]],
    *,
    max_story_context_chars: int,
    max_episode_context_chars: int,
) -> None:
    oversized = [
        (clean_text(packet.get("story_id")), int((packet.get("telemetry") or {}).get("serialized_char_count", 0)))
        for packet in packets
        if int((packet.get("telemetry") or {}).get("serialized_char_count", 0)) > max_story_context_chars
    ]
    if oversized:
        raise ValueError(
            "Complete story context exceeds source_context.max_story_context_chars; no records were truncated. "
            f"Oversized packets: {oversized}"
        )
    total_chars = sum(int((packet.get("telemetry") or {}).get("serialized_char_count", 0)) for packet in packets)
    if total_chars > max_episode_context_chars:
        raise ValueError(
            "Complete episode context exceeds source_context.max_episode_context_chars; no records were truncated. "
            f"serialized_chars={total_chars}, configured_limit={max_episode_context_chars}"
        )


def _semantic_record_text(record: dict[str, Any]) -> str:
    for field in ("cleaned_content", "content", "transcript"):
        value = str(record.get(field) or "")
        if value.strip():
            return value
    return " ".join(
        str(record.get(field) or "")
        for field in ("title", "summary", "description")
        if str(record.get(field) or "").strip()
    )
