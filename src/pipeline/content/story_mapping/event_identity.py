from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from .clusterer import build_record_context
from .llm_logging import build_llm_call_log
from .utils import clean_text


EVENT_IDENTITY_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\nComplete normalized record:\n{record_payload}"
)


class EventIdentityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_entity: str
    owning_org: str
    product_or_project: str
    named_identity_supported: bool = Field(
        description=(
            "True only when the record supports an exact proper-noun organization/entity and "
            "product identity. Generic labels such as 'a Chinese startup' are false."
        )
    )
    canonical_named_entity: str = Field(
        description="Exact supported entity/organization name, or an empty string when unresolved."
    )
    canonical_named_product: str = Field(
        description="Exact supported product/model/project name, or an empty string when unresolved."
    )
    identity_resolution: Literal[
        "explicit",
        "resolved_from_record_context",
        "descriptive_only",
        "unknown",
    ]
    identity_evidence: list[str]
    entity_aliases: list[str]
    product_aliases: list[str]
    event_action: str
    event_type: Literal[
        "announcement",
        "release",
        "update",
        "report",
        "research",
        "funding",
        "policy_position",
        "incident",
        "benchmark",
        "tutorial",
        "opinion",
        "evergreen",
        "other",
        "unknown",
    ]
    event_status: Literal[
        "planned",
        "announced",
        "available",
        "released",
        "reported",
        "measured",
        "claimed",
        "alleged",
        "proposed",
        "opinion",
        "evergreen",
        "unknown",
    ]
    event_date: str
    canonical_event: str
    story_family: str
    distinguishing_details: list[str]
    event_fingerprint: list[str]


def attach_event_identities(
    records: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not records:
        return []

    worker_count = min(max(1, int(config.get("worker_count", 1))), len(records))
    ordered: list[tuple[dict[str, Any], list[dict[str, Any]]] | None] = [None] * len(records)

    def process(index: int, record: dict[str, Any]):
        local_calls: list[dict[str, Any]] = []
        identity = _extract_event_identity(
            record,
            config=config,
            llm=llm,
            system_prompt=system_prompt,
            llm_calls=local_calls,
        )
        enriched = {
            **record,
            "story_mapping_event_identity": {
                "record_key": clean_text(record.get("record_key")),
                **identity,
            },
        }
        return index, enriched, local_calls

    if worker_count == 1:
        for index, record in enumerate(records):
            _, enriched, local_calls = process(index, record)
            ordered[index] = (enriched, local_calls)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(process, index, record): index
                for index, record in enumerate(records)
            }
            for future in as_completed(futures):
                index, enriched, local_calls = future.result()
                ordered[index] = (enriched, local_calls)

    output: list[dict[str, Any]] = []
    for item in ordered:
        if item is None:
            raise RuntimeError("Event identity extraction completed with a missing record result")
        record, local_calls = item
        output.append(record)
        llm_calls.extend(local_calls)
    return output


def _extract_event_identity(
    record: dict[str, Any],
    *,
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    context = build_record_context(record)
    payload = {
        "task": "Extract the concrete event identity represented by this complete record.",
        "record": context,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(serialized) > int(config["max_record_chars"]):
        raise ValueError(
            "A complete record exceeds event_identity.max_record_chars; source context was not "
            f"truncated. record_key={clean_text(record.get('record_key'))}, "
            f"serialized_chars={len(serialized)}"
        )

    prompt_inputs = {"system_prompt": system_prompt, "record_payload": serialized}
    rendered = EVENT_IDENTITY_PROMPT.format(**prompt_inputs)
    structured_options: dict[str, Any] = {"include_raw": True}
    if clean_text(config.get("provider")).casefold() == "openai":
        structured_options["strict"] = True
    chain = EVENT_IDENTITY_PROMPT | llm.with_structured_output(
        EventIdentityOutput,
        **structured_options,
    )

    last_error = ""
    for attempt in range(1, int(config["max_attempts"]) + 1):
        started = time.time()
        raw = None
        parsed_dict = None
        try:
            result = chain.invoke(prompt_inputs)
            raw = result.get("raw") if isinstance(result, dict) else None
            parsed = result.get("parsed") if isinstance(result, dict) else result
            parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
            if parsing_error is not None or parsed is None:
                raise ValueError(f"structured output parsing failed: {parsing_error}")
            output = (
                parsed
                if isinstance(parsed, EventIdentityOutput)
                else EventIdentityOutput.model_validate(parsed)
            )
            parsed_dict = output.model_dump(mode="json")
            llm_calls.append(
                build_llm_call_log(
                    module_name="event_identity",
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered,
                    raw_response=raw,
                    parsed_output=parsed_dict,
                    metadata={
                        "record_key": clean_text(record.get("record_key")),
                        "attempt": attempt,
                        "serialized_context_chars": len(serialized),
                        "source_context_mode": "complete_normalized_record",
                        "record_truncated": False,
                    },
                    duration_seconds=time.time() - started,
                )
            )
            return parsed_dict
        except Exception as exc:
            last_error = clean_text(exc)
            llm_calls.append(
                build_llm_call_log(
                    module_name="event_identity",
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered,
                    raw_response=raw,
                    parsed_output=parsed_dict,
                    metadata={
                        "record_key": clean_text(record.get("record_key")),
                        "attempt": attempt,
                        "serialized_context_chars": len(serialized),
                        "source_context_mode": "complete_normalized_record",
                        "record_truncated": False,
                    },
                    duration_seconds=time.time() - started,
                    parse_error=last_error,
                )
            )
    raise RuntimeError(
        "Event identity extraction failed after bounded retries for "
        f"{clean_text(record.get('record_key'))}: {last_error}"
    )
