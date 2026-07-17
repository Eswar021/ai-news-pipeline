from __future__ import annotations

import re
import json
from copy import deepcopy
from functools import lru_cache
from html import unescape
from typing import Any

import tiktoken


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


CONTENT_FIELDS = (
    "cleaned_content",
    "content",
    "transcript",
    "semantic_content",
    "raw_content",
)


def build_story_context(story: dict[str, Any]) -> dict[str, Any]:
    records = [
        _complete_record_context(record)
        for record in story.get("records", [])
        if isinstance(record, dict)
    ]
    context = {
        "story_id": clean_text(story.get("story_id")),
        "story_title": clean_text(story.get("story_title")),
        "story_identity": deepcopy(story.get("story_identity") or {}),
        "story_type_hint": clean_text(story.get("story_type_hint")),
        "time_range": deepcopy(story.get("time_range") or {}),
        "source_groups": list(story.get("source_groups") or []),
        "related_stories": deepcopy(story.get("related_stories") or []),
        "ranking_features": deepcopy(story.get("ranking_features") or {}),
        "ranking_note": "Objective telemetry only; do not treat candidate order as editorial rank.",
        "records": records,
        "context_contract": {
            "record_count": len(records),
            "all_story_records_included": True,
            "records_truncated": False,
        },
    }
    context["context_contract"]["serialized_context_chars"] = story_context_chars(context)
    return context


def story_context_chars(context: dict[str, Any]) -> int:
    return len(json.dumps(context, ensure_ascii=False, separators=(",", ":")))


def text_token_count(text: str, *, model: str, fallback_encoding: str) -> int:
    encoding = _token_encoding(model, fallback_encoding)
    return len(encoding.encode(text))


@lru_cache(maxsize=32)
def _token_encoding(model: str, fallback_encoding: str):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding(fallback_encoding)


def _complete_record_context(record: dict[str, Any]) -> dict[str, Any]:
    context = deepcopy(record)
    values = {
        field: str(record.get(field) or "").strip()
        for field in CONTENT_FIELDS
        if record.get(field) is not None
    }
    source_field = next((field for field in CONTENT_FIELDS if values.get(field)), "")
    semantic_content = values.get(source_field, "")
    raw_content = values.get("raw_content", "")
    for field in CONTENT_FIELDS:
        context.pop(field, None)
    context.pop("legacy_filter_hints", None)
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
