from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import re
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    @field_validator(
        "primary_entity",
        "owning_org",
        "product_or_project",
        "canonical_story_key",
        "one_sentence_story",
        "why_it_matters",
    )
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("story label text fields must not be empty; use 'unknown' when needed")
        return value


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
    context_records = [
        record for record in story.get("records", []) if isinstance(record, dict)
    ]
    story_context = _build_story_label_context(
        story=story,
        run_context=run_context,
        records=context_records,
    )
    serialized_context_chars = len(
        json.dumps(story_context, ensure_ascii=False, separators=(",", ":"))
    )
    configured_limit = int(story_label_cfg["max_story_context_chars"])
    if serialized_context_chars > configured_limit:
        raise ValueError(
            "Complete story-label context exceeds story_label.max_story_context_chars; "
            "no records were removed or truncated. "
            f"story_id={story.get('story_id')}, serialized_chars={serialized_context_chars}, "
            f"configured_limit={configured_limit}"
        )
    story_payload = _build_user_prompt(
        story_context=story_context,
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
        "context_record_keys": [clean_text(record.get("record_key")) for record in context_records],
        "source_context_mode": "complete_normalized_story_records",
        "records_truncated": False,
        "serialized_context_chars": serialized_context_chars,
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
    next_story["story_label_context"] = {
        "record_keys": [clean_text(record.get("record_key")) for record in context_records],
        "selection_strategy": "all_complete_story_records",
        "records_truncated": False,
        "serialized_context_chars": serialized_context_chars,
    }
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


def _build_user_prompt(
    *,
    story_context: dict[str, Any],
) -> str:
    return json.dumps(story_context, ensure_ascii=False, indent=2)


def _build_story_label_context(
    *,
    story: dict[str, Any],
    run_context: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    time_range = story.get("time_range") or {}
    collection_window = run_context.get("collection_window") or {}
    return {
        "run_window": {
            "start": clean_text(collection_window.get("start")),
            "end": clean_text(collection_window.get("end")),
            "lookback_hours": collection_window.get("lookback_hours"),
            "effective_max_pair_hours": run_context.get("effective_max_pair_hours"),
        },
        "story": {
            "story_id": clean_text(story.get("story_id")),
            "story_title": clean_text(story.get("story_title")),
            "record_count": len(records),
            "source_groups": list(story.get("source_groups") or []),
            "match_reasons": list(story.get("match_reasons") or []),
            "time_range": {
                "first_seen_at": clean_text(time_range.get("first_seen_at")),
                "last_seen_at": clean_text(time_range.get("last_seen_at")),
                "time_span_hours": time_range.get("time_span_hours", 0),
            },
        },
        "records": [_complete_record_context(record) for record in records],
        "context_contract": {
            "all_story_records_included": True,
            "records_truncated": False,
        },
    }


def _complete_record_context(record: dict[str, Any]) -> dict[str, Any]:
    content_fields = (
        "cleaned_content",
        "content",
        "transcript",
        "semantic_content",
        "raw_content",
    )
    context = deepcopy(record)
    values = {
        field: str(record.get(field) or "").strip()
        for field in content_fields
        if record.get(field) is not None
    }
    source_field = next((field for field in content_fields if values.get(field)), "")
    semantic_content = values.get(source_field, "")
    raw_content = values.get("raw_content", "")
    for field in content_fields:
        context.pop(field, None)
    context["semantic_content"] = semantic_content
    if raw_content and raw_content != semantic_content:
        context["distinct_raw_content"] = raw_content
    context["semantic_content_provenance"] = {
        "source_field": source_field,
        "complete": True,
        "truncated": False,
        "distinct_raw_content_included": bool(raw_content and raw_content != semantic_content),
        "original_field_char_counts": {
            field: len(value) for field, value in values.items()
        },
    }
    return context


def validate_story_label(raw: StoryLabelOutput | BaseModel | dict, story: dict) -> dict:
    if isinstance(raw, BaseModel):
        raw_dict = raw.model_dump(mode="json")
    elif isinstance(raw, dict):
        raw_dict = raw
    else:
        raise ValueError(f"Story label response must be a Pydantic model or dict for {story.get('story_id', '')}")

    parsed = StoryLabelOutput.model_validate(raw_dict)
    canonical_story_key = _normalize_key(parsed.canonical_story_key)
    if not canonical_story_key:
        raise ValueError(
            f"Story label canonical_story_key normalizes to empty for {story.get('story_id', '')}"
        )

    return {
        "primary_entity": _clean_label_text(parsed.primary_entity),
        "owning_org": _clean_label_text(parsed.owning_org),
        "product_or_project": _clean_label_text(parsed.product_or_project),
        "story_action": parsed.story_action,
        "story_type": parsed.story_type,
        "temporal_relationship": parsed.temporal_relationship,
        "canonical_story_key": canonical_story_key,
        "merge_identity": canonical_story_key,
        "one_sentence_story": _clean_label_text(parsed.one_sentence_story),
        "editorial_value": parsed.editorial_value,
        "is_tutorial": parsed.is_tutorial,
        "is_event_update": parsed.is_event_update,
        "is_noise": parsed.is_noise,
        "why_it_matters": _clean_label_text(parsed.why_it_matters),
    }


def _clean_label_text(value) -> str:
    return clean_text(str(value or ""))


def _normalize_key(value) -> str:
    cleaned = clean_text(str(value or "")).lower()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[^a-z0-9|_\- ]+", "", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = re.sub(r"_*\|_*", "|", cleaned)
    return cleaned[:140]
