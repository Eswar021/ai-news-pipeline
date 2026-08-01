"""Format-agnostic source research + written-segment validation.

Reading the complete records for a story into a semantic source brief + truth
index, and validating a written segment's beats against that story's truth and
record keys, are shared by every script format.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .invocation import invoke_runtime_chain
from .models import StorySegmentOutput, story_source_brief_output_model
from .source_context import (
    build_source_research_context,
    build_story_context_packet,
    story_context_telemetry,
    validate_context_resource_limits,
)
from .source_truth import build_story_truth_index, compact_truth_index, truth_item_map
from .utils import clean_text, dedupe, json_dumps, source_record_keys, story_id, story_title


def research_story_sources(
    *,
    stories: list[dict[str, Any]],
    script_cfg: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    module_name: str = "source_researcher",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    source_config = dict(script_cfg.get("source_context") or {})
    worker_count = min(max(1, int(script_cfg.get("worker_count", 1))), len(stories))

    call_logs_by_index: list[list[dict[str, Any]]] = [[] for _ in stories]

    def research(index: int, story: dict[str, Any]):
        local_calls = call_logs_by_index[index]
        source_context = build_source_research_context(story)
        allowed_record_keys = source_record_keys(story)
        output_model = story_source_brief_output_model(
            required_story_id=story_id(story),
            allowed_record_keys=allowed_record_keys,
        )
        payload = {
            "task": "Read the complete assigned records and build one semantic source brief without writing narration.",
            "required_story_id": story_id(story),
            "allowed_source_record_keys": allowed_record_keys,
            "complete_story_context": source_context,
            "identity_rule": (
                "Copy required_story_id and record_key values exactly from this payload; never shorten, "
                "rewrite, or invent an identifier."
            ),
        }
        response = invoke_runtime_chain(
            module_name=module_name,
            output_model=output_model,
            llm_runtime=llm_runtime,
            prompt_bundle=prompt_bundle,
            task_payload=json_dumps(payload),
            metadata={
                "story_id": story_id(story),
                "source_context_mode": "complete_records_plus_semantic_brief",
                **story_context_telemetry(source_context),
            },
            llm_calls=local_calls,
        )
        brief = response.model_dump(mode="json")
        truth_index_model = build_story_truth_index(story, response)
        truth_index = compact_truth_index(truth_index_model)
        packet = build_story_context_packet(story, truth_index_model)
        return index, brief, truth_index, packet

    ordered: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None] = [None] * len(stories)
    try:
        if worker_count == 1:
            for index, story in enumerate(stories):
                _, brief, truth_index, packet = research(index, story)
                ordered[index] = (brief, truth_index, packet)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {executor.submit(research, index, story): index for index, story in enumerate(stories)}
                for future in as_completed(futures):
                    index, brief, truth_index, packet = future.result()
                    ordered[index] = (brief, truth_index, packet)
    finally:
        for calls in call_logs_by_index:
            llm_calls.extend(calls)

    if any(item is None for item in ordered):
        raise RuntimeError("Source research completed with missing story packets")
    briefs: list[dict[str, Any]] = []
    truth_indexes: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = []
    for item in ordered:
        if item is None:
            continue
        brief, truth_index, packet = item
        briefs.append(brief)
        truth_indexes.append(truth_index)
        packets.append(packet)
    validate_context_resource_limits(
        packets,
        max_story_context_chars=int(source_config.get("max_story_context_chars", 500_000)),
        max_episode_context_chars=int(source_config.get("max_episode_context_chars", 1_500_000)),
    )
    return briefs, truth_indexes, packets


def validate_story_segment(
    segment: dict[str, Any],
    *,
    story: dict[str, Any],
    truth_index: dict[str, Any],
) -> dict[str, Any]:
    raw = StorySegmentOutput.model_validate(segment).model_dump(mode="json")
    sid = story_id(story)
    if clean_text(raw.get("story_id")) != sid:
        raise ValueError(f"Story writer returned story_id {raw.get('story_id')!r}; expected {sid!r}")
    allowed_keys = set(source_record_keys(story))
    available_truth = truth_item_map(truth_index)
    used_keys: list[str] = []
    for beat in raw["beats"]:
        beat["narration_text"] = clean_text(beat["narration_text"])
        beat["support_truth_ids"] = dedupe(list(beat.get("support_truth_ids") or []))
        unknown_truth = sorted(set(beat["support_truth_ids"]) - set(available_truth))
        if unknown_truth:
            raise ValueError(f"Story writer used truth IDs outside {sid}: {unknown_truth}")
        supported_record_keys = [
            clean_text(available_truth[truth_id].get("record_key"))
            for truth_id in beat["support_truth_ids"]
            if truth_id in available_truth
        ]
        beat["source_record_keys"] = dedupe(list(beat.get("source_record_keys") or []))
        beat["source_record_keys"] = dedupe([*beat["source_record_keys"], *supported_record_keys])
        unknown = sorted(set(beat["source_record_keys"]) - allowed_keys)
        if unknown:
            raise ValueError(f"Story writer used source keys outside {sid}: {unknown}")
        used_keys.extend(beat["source_record_keys"])
    if allowed_keys and not used_keys:
        raise ValueError(f"Story writer did not ground {sid} in any assigned source record")
    raw["display_title"] = clean_text(raw.get("display_title")) or story_title(story)
    return raw


def beat_support_context(segment: dict[str, Any], truth_index: dict[str, Any]) -> list[dict[str, Any]]:
    available = truth_item_map(truth_index)
    context: list[dict[str, Any]] = []
    for beat_order, beat in enumerate(segment.get("beats", []), start=1):
        support_items = [
            available[truth_id]
            for truth_id in beat.get("support_truth_ids", [])
            if truth_id in available
        ]
        context.append(
            {
                "beat_id": f"beat_{beat_order:02d}",
                "narration_text": clean_text(beat.get("narration_text")),
                "support_items": support_items,
            }
        )
    return context
