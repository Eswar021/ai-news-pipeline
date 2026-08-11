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


def build_record_context(
    record: dict[str, Any], *, max_chars: int | None = None
) -> dict[str, Any]:
    """Build a complete semantic packet without repeating equivalent content aliases.

    When ``max_chars`` is given and the packet would exceed it (a rare, anomalously
    huge scrape — e.g. a release page with its full changelog + comment thread), the
    packet's content is truncated to fit and the provenance flags it, rather than
    letting one giant record hard-fail the whole run. This bounds only the LLM's
    triage context; the untouched record still flows downstream at full length.
    """

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
    if max_chars is not None:
        _fit_context_to_budget(context, max_chars=max_chars)
    return context


TRUNCATION_MARKER = " …[truncated for triage context budget]"


def _fit_context_to_budget(context: dict[str, Any], *, max_chars: int) -> None:
    """Shrink an over-budget context in place: drop the supplementary raw copy first,
    then keep the largest head of ``semantic_content`` that still fits. Honestly
    recorded in ``semantic_content_provenance`` so the truncation is never silent."""
    if record_context_chars(context) <= max_chars:
        return
    provenance = context.get("semantic_content_provenance", {})

    dropped_distinct = False
    if context.get("distinct_raw_content"):
        del context["distinct_raw_content"]
        dropped_distinct = True
        provenance["distinct_raw_content_included"] = False

    content = context.get("semantic_content", "")
    # Set the truncation-provenance keys BEFORE measuring, so the budget search sees
    # the final structure (adding them afterwards would push the result back over).
    # The count starts at its max width (len(content)); the real value can only be
    # smaller, so the final context never exceeds what the search measured.
    provenance["complete"] = False
    provenance["truncated"] = True
    provenance["distinct_raw_content_dropped"] = dropped_distinct
    provenance["truncated_semantic_content_chars"] = len(content)
    context["semantic_content_provenance"] = provenance

    if record_context_chars(context) > max_chars:
        # Largest prefix of semantic_content whose full serialized context fits.
        low, high, best = 0, len(content), 0
        while low <= high:
            mid = (low + high) // 2
            context["semantic_content"] = content[:mid] + (
                TRUNCATION_MARKER if mid < len(content) else ""
            )
            if record_context_chars(context) <= max_chars:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        context["semantic_content"] = content[:best] + (
            TRUNCATION_MARKER if best < len(content) else ""
        )
        provenance["truncated_semantic_content_chars"] = best


def record_context_chars(context: dict[str, Any]) -> int:
    return len(json.dumps(context, ensure_ascii=False, separators=(",", ":")))


def _complete_text(value: Any) -> str:
    if value is None:
        return ""
    return unescape(str(value)).strip()
