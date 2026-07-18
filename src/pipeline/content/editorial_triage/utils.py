from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from html import unescape
from typing import Any


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


def record_key(record: dict[str, Any]) -> str:
    existing = clean_text(record.get("record_key"))
    if existing:
        return existing
    basis = "|".join(
        clean_text(record.get(name)).casefold()
        for name in ("source", "url", "title", "published_at")
    )
    return f"record_{hashlib.sha1(basis.encode('utf-8')).hexdigest()[:12]}"


CONTENT_FIELDS = (
    "cleaned_content",
    "content",
    "transcript",
    "semantic_content",
    "raw_content",
)


def build_record_context(record: dict[str, Any]) -> dict[str, Any]:
    """Build a complete semantic packet without repeating equivalent content aliases."""

    context = deepcopy(record)
    field_values = {
        field: _complete_text(record.get(field))
        for field in CONTENT_FIELDS
        if record.get(field) is not None
    }
    source_field = next((field for field in CONTENT_FIELDS if field_values.get(field)), "")
    semantic_content = field_values.get(source_field, "")
    raw_content = field_values.get("raw_content", "")
    for field in CONTENT_FIELDS:
        context.pop(field, None)

    # Legacy code hints remain available in the output ledger, but they must not
    # bias the semantic editor before it reads the source itself.
    context.pop("legacy_filter_hints", None)
    context["record_key"] = record_key(record)
    context["semantic_content"] = semantic_content
    if raw_content and raw_content != semantic_content:
        context["distinct_raw_content"] = raw_content
    context["semantic_content_provenance"] = {
        "source_field": source_field,
        "complete": True,
        "truncated": False,
        "distinct_raw_content_included": bool(
            raw_content and raw_content != semantic_content
        ),
        "original_field_char_counts": {
            field: len(value) for field, value in field_values.items()
        },
    }
    return context


def record_context_chars(context: dict[str, Any]) -> int:
    return len(json.dumps(context, ensure_ascii=False, separators=(",", ":")))


def _complete_text(value: Any) -> str:
    if value is None:
        return ""
    return unescape(str(value)).strip()
