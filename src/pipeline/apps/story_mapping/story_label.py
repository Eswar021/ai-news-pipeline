from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from .config import (
    VALID_ACTIONS,
    VALID_EDITORIAL_VALUES,
    VALID_STORY_TYPES,
    VALID_TEMPORAL_RELATIONSHIPS,
)
from .fingerprint import build_fingerprint_text
from .llm_logging import build_llm_call_log
from .utils import clean_text


STORY_LABEL_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\n"
    "Story payload:\n"
    "{story_payload}"
)


class StoryLabelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_entity: str = Field(description="Short canonical entity name.")
    owning_org: str = Field(description="Canonical organization name, or unknown.")
    product_or_project: str = Field(description="Specific product, project, model, repo, paper, or unknown.")
    story_action: Literal[
        "adopted",
        "disproved",
        "expanded",
        "launched",
        "updated",
        "partnered",
        "reported",
        "benchmarked",
        "researched",
        "funded",
        "criticized",
        "explained",
        "tutorial",
        "event_update",
        "unknown",
    ]
    story_type: Literal[
        "official_update",
        "industry_news",
        "research_result",
        "community_product_launch",
        "community_repository",
        "tutorial_or_demo",
        "event_update",
        "reaction_or_opinion",
        "unknown",
    ]
    temporal_relationship: Literal[
        "same_event",
        "follow_up",
        "broader_story_arc",
        "timeless_topic",
        "unknown",
    ]
    canonical_story_key: str = Field(description="Stable lowercase identity string.")
    one_sentence_story: str = Field(description="One complete concise sentence describing the exact story.")
    editorial_value: Literal["high", "medium", "low"]
    is_tutorial: bool
    is_event_update: bool
    is_noise: bool
    why_it_matters: str = Field(
        description="One complete concise sentence explaining why this may or may not matter."
    )


def attach_story_labels(
    stories: list[dict],
    *,
    story_label_cfg: dict,
    run_context: dict,
    llm,
    llm_calls: list[dict[str, Any]],
    system_prompt: str,
) -> list[dict]:
    worker_count = int(story_label_cfg["worker_count"])
    if worker_count < 1:
        raise ValueError("story_label.worker_count must be at least 1")

    structured_llm = llm.with_structured_output(StoryLabelOutput, include_raw=True)
    chain = STORY_LABEL_PROMPT | structured_llm
    total = len(stories)
    if worker_count == 1:
        return [
            _label_one_story(
                index=index,
                total=total,
                story=story,
                story_label_cfg=story_label_cfg,
                run_context=run_context,
                chain=chain,
                llm_calls=llm_calls,
                system_prompt=system_prompt,
            )
            for index, story in enumerate(stories, start=1)
        ]

    ordered: list[dict | None] = [None] * total
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _label_one_story,
                index=index,
                total=total,
                story=story,
                story_label_cfg=story_label_cfg,
                run_context=run_context,
                chain=chain,
                llm_calls=llm_calls,
                system_prompt=system_prompt,
            ): index - 1
            for index, story in enumerate(stories, start=1)
        }
        for future in as_completed(future_to_index):
            result_index = future_to_index[future]
            ordered[result_index] = future.result()

    if any(story is None for story in ordered):
        raise RuntimeError("Story labeling finished with missing story outputs")
    return [story for story in ordered if story is not None]


def _label_one_story(
    *,
    index: int,
    total: int,
    story: dict,
    story_label_cfg: dict,
    run_context: dict,
    chain,
    llm_calls: list[dict[str, Any]],
    system_prompt: str,
) -> dict:
    story_payload = _build_user_prompt(
        story=story,
        run_context=run_context,
        max_records_per_story=int(story_label_cfg["max_records_per_story"]),
    )
    prompt_inputs = {
        "system_prompt": system_prompt,
        "story_payload": story_payload,
    }
    metadata = {
        "story_id": story.get("story_id", ""),
        "story_title": story.get("story_title", ""),
        "record_count": story.get("record_count", 0),
        "story_index": index,
        "story_total": total,
    }
    response_model = _invoke_story_label_chain(
        module_name="story_label",
        chain=chain,
        prompt_inputs=prompt_inputs,
        metadata=metadata,
        story_label_cfg=story_label_cfg,
        llm_calls=llm_calls,
    )
    label = validate_story_label(response_model, story)
    next_story = dict(story)
    next_story["story_identity"] = label
    if label["story_type"] != "unknown":
        next_story["story_type_hint"] = label["story_type"]
    return next_story


def _invoke_story_label_chain(
    *,
    module_name: str,
    chain,
    prompt_inputs: dict[str, Any],
    metadata: dict,
    story_label_cfg: dict,
    llm_calls: list[dict[str, Any]],
) -> StoryLabelOutput:
    rendered_prompt = STORY_LABEL_PROMPT.format(**prompt_inputs)
    started = time.time()
    result = chain.invoke(prompt_inputs)
    duration = time.time() - started

    raw = result.get("raw") if isinstance(result, dict) else None
    parsed = result.get("parsed") if isinstance(result, dict) else result
    parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
    provider = str(story_label_cfg.get("provider", "openai"))
    model = str(story_label_cfg.get("model", ""))

    if parsing_error is not None or parsed is None:
        llm_calls.append(
            build_llm_call_log(
                module_name=module_name,
                provider=provider,
                model=model,
                rendered_prompt=rendered_prompt,
                raw_response=raw,
                parsed_output=None,
                metadata=metadata,
                duration_seconds=duration,
                parse_error=str(parsing_error),
            )
        )
        error = ValueError(f"LLM structured output failed for module {module_name}")
        if isinstance(parsing_error, BaseException):
            raise error from parsing_error
        raise error

    parsed_model = parsed if isinstance(parsed, StoryLabelOutput) else StoryLabelOutput.model_validate(parsed)
    parsed_output = parsed_model.model_dump(mode="json")
    llm_calls.append(
        build_llm_call_log(
            module_name=module_name,
            provider=provider,
            model=model,
            rendered_prompt=rendered_prompt,
            raw_response=raw,
            parsed_output=parsed_output,
            metadata=metadata,
            duration_seconds=duration,
        )
    )
    return parsed_model


def _build_user_prompt(*, story: dict, run_context: dict, max_records_per_story: int) -> str:
    time_range = story.get("time_range") or {}
    collection_window = run_context.get("collection_window") or {}
    story_lines = [
        f"run_window_start: {clean_text(collection_window.get('start', ''))}",
        f"run_window_end: {clean_text(collection_window.get('end', ''))}",
        f"run_window_lookback_hours: {collection_window.get('lookback_hours', '')}",
        f"effective_max_pair_hours: {run_context.get('effective_max_pair_hours', '')}",
        f"story_id: {clean_text(story.get('story_id', ''))}",
        f"story_title: {clean_text(story.get('story_title', ''))}",
        f"record_count: {story.get('record_count', 0)}",
        f"source_groups: {', '.join(story.get('source_groups', []))}",
        f"match_reasons: {', '.join(story.get('match_reasons', []))}",
        f"story_first_seen_at: {clean_text(time_range.get('first_seen_at', ''))}",
        f"story_last_seen_at: {clean_text(time_range.get('last_seen_at', ''))}",
        f"story_time_span_hours: {time_range.get('time_span_hours', 0)}",
    ]
    record_blocks = []
    for index, record in enumerate(story.get("records", [])[:max_records_per_story], start=1):
        source_name = record.get("source_name") or record.get("provider") or record.get("channel_name", "")
        header = "\n".join(
            [
                f"record_{index}_key: {clean_text(record.get('record_key', ''))}",
                f"record_{index}_source_group: {clean_text(record.get('source_group', ''))}",
                f"record_{index}_source: {clean_text(record.get('source', ''))}",
                f"record_{index}_source_name: {clean_text(source_name)}",
                f"record_{index}_title: {clean_text(record.get('title', ''))}",
                f"record_{index}_url: {clean_text(record.get('url', ''))}",
                f"record_{index}_published_at: {clean_text(record.get('published_at', ''))}",
            ]
        )
        record_text = build_fingerprint_text(record)[:1800]
        record_blocks.append(f"{header}\nrecord_{index}_text:\n{record_text}")

    return "\n".join(story_lines) + "\n\nSupporting records:\n\n" + "\n\n---\n\n".join(record_blocks)


def validate_story_label(raw: StoryLabelOutput | BaseModel | dict, story: dict) -> dict:
    if isinstance(raw, BaseModel):
        raw_dict = raw.model_dump(mode="json")
    elif isinstance(raw, dict):
        raw_dict = raw
    else:
        raise ValueError(f"Story label response must be a Pydantic model or dict for {story.get('story_id', '')}")

    primary_entity = _clean_label_text(raw_dict.get("primary_entity", "unknown")) or "unknown"
    owning_org = _clean_label_text(raw_dict.get("owning_org", "unknown")) or "unknown"
    product_or_project = _clean_label_text(raw_dict.get("product_or_project", "unknown")) or "unknown"
    story_action = _enum(raw_dict.get("story_action"), VALID_ACTIONS, "unknown")
    story_type = _enum(raw_dict.get("story_type"), VALID_STORY_TYPES, "unknown")
    temporal_relationship = _enum(
        raw_dict.get("temporal_relationship"),
        VALID_TEMPORAL_RELATIONSHIPS,
        "unknown",
    )
    editorial_value = _enum(raw_dict.get("editorial_value"), VALID_EDITORIAL_VALUES, "medium")
    is_tutorial = _bool(raw_dict.get("is_tutorial", False))
    is_event_update = _bool(raw_dict.get("is_event_update", False))

    if story_type in {"community_product_launch", "official_update", "industry_news", "research_result"}:
        is_tutorial = story_action == "tutorial"
    if story_type != "event_update":
        is_event_update = story_action == "event_update"

    canonical_story_key = _normalize_key(raw_dict.get("canonical_story_key", raw_dict.get("merge_identity", "")))
    if not canonical_story_key:
        canonical_story_key = _fallback_story_key(
            primary_entity=primary_entity,
            product_or_project=product_or_project,
            story_action=story_action,
            story_type=story_type,
            story=story,
        )

    return {
        "primary_entity": primary_entity,
        "owning_org": owning_org,
        "product_or_project": product_or_project,
        "story_action": story_action,
        "story_type": story_type,
        "temporal_relationship": temporal_relationship,
        "canonical_story_key": canonical_story_key,
        "merge_identity": canonical_story_key,
        "one_sentence_story": _clean_label_text(raw_dict.get("one_sentence_story", "")),
        "editorial_value": editorial_value,
        "is_tutorial": is_tutorial,
        "is_event_update": is_event_update,
        "is_noise": _bool(raw_dict.get("is_noise", False)),
        "why_it_matters": _clean_label_text(raw_dict.get("why_it_matters", "")),
    }


def _enum(value, allowed: set[str], default: str) -> str:
    cleaned = clean_text(str(value or "")).lower()
    return cleaned if cleaned in allowed else default


def _clean_label_text(value) -> str:
    return clean_text(str(value or ""))


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned == "true":
            return True
        if cleaned == "false":
            return False
    return bool(value)


def _normalize_key(value) -> str:
    cleaned = clean_text(str(value or "")).lower()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[^a-z0-9|_\- ]+", "", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = re.sub(r"_*\|_*", "|", cleaned)
    return cleaned[:140]


def _fallback_story_key(
    *,
    primary_entity: str,
    product_or_project: str,
    story_action: str,
    story_type: str,
    story: dict,
) -> str:
    entity = product_or_project if product_or_project != "unknown" else primary_entity
    if entity == "unknown":
        entity = clean_text(story.get("story_title", ""))[:80] or clean_text(story.get("story_id", "unknown"))
    return _normalize_key(f"{entity}|{story_action}|{story_type}")
