from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from .llm_logging import build_llm_call_log
from .utils import clean_text


PAIR_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\nCandidate pairs:\n{pair_payload}"
)


class PairDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str
    relationship: Literal[
        "same_event",
        "follow_up",
        "broader_story_arc",
        "unrelated",
        "uncertain",
    ]
    confidence: float = Field(ge=0, le=1)
    reason: str
    requires_full_record_review: bool


class PairDecisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[PairDecision]


def adjudicate_candidate_pairs(
    candidates: list[dict],
    *,
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
    full_record_llm=None,
) -> list[dict]:
    decisions: list[dict] = []
    batches = _candidate_batches(
        candidates,
        batch_size=int(config["batch_size"]),
        max_batch_chars=int(config["max_batch_chars"]),
        max_single_pair_chars=int(config.get("max_single_pair_chars", 300_000)),
    )
    worker_count = min(max(1, int(config.get("worker_count", 2))), len(batches))

    def process_batch(batch_index: int, batch: list[dict]) -> tuple[int, list[dict], list[dict[str, Any]]]:
        local_calls: list[dict[str, Any]] = []
        batch_output = None
        last_error = ""
        for attempt in range(1, int(config["max_attempts"]) + 1):
            try:
                batch_output = _invoke_batch(
                    batch=batch,
                    batch_index=batch_index,
                    attempt=attempt,
                    config=config,
                    llm=llm,
                    system_prompt=system_prompt,
                    llm_calls=local_calls,
                    full_record_llm=full_record_llm,
                )
                break
            except Exception as exc:
                last_error = clean_text(exc)
        if batch_output is None:
            batch_output = [
                {
                    "pair_id": item["pair_id"],
                    "relationship": "uncertain",
                    "confidence": 0.0,
                    "reason": f"Pair adjudication unresolved after bounded retries: {last_error}",
                    "requires_full_record_review": False,
                    "decision_source": "unresolved",
                }
                for item in batch
            ]
        return batch_index, batch_output, local_calls

    ordered: list[tuple[list[dict], list[dict[str, Any]]] | None] = [None] * len(batches)
    if worker_count == 1:
        for batch_index, batch in enumerate(batches, start=1):
            _, batch_output, local_calls = process_batch(batch_index, batch)
            ordered[batch_index - 1] = (batch_output, local_calls)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(process_batch, batch_index, batch): batch_index
                for batch_index, batch in enumerate(batches, start=1)
            }
            for future in as_completed(futures):
                batch_index, batch_output, local_calls = future.result()
                ordered[batch_index - 1] = (batch_output, local_calls)

    for item in ordered:
        if item is None:
            raise RuntimeError("Pair adjudication completed with a missing batch result")
        batch_output, local_calls = item
        decisions.extend(batch_output)
        llm_calls.extend(local_calls)
    return decisions


def _invoke_batch(
    *,
    batch: list[dict],
    batch_index: int,
    attempt: int,
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
    full_record_llm=None,
) -> list[dict]:
    if len(batch) != 1:
        raise ValueError("Pair adjudication requires exactly one candidate per LLM call")

    capsule_output = _invoke_context(
        batch=batch,
        batch_index=batch_index,
        attempt=attempt,
        config=config,
        llm=llm,
        system_prompt=system_prompt,
        llm_calls=llm_calls,
        include_full_records=False,
        module_name="pair_adjudication",
    )
    decision = capsule_output[0]
    if not bool(config.get("confirm_same_event_with_full_records", True)):
        return capsule_output
    needs_confirmation = decision.get("relationship") == "same_event"
    needs_ambiguity_review = bool(
        config.get("review_ambiguous_pairs_with_full_records", True)
        and (
            decision.get("requires_full_record_review")
            or _pair_has_unresolved_named_identity(batch)
            or decision.get("relationship")
            in set(
                config.get(
                    "full_record_review_relationships",
                    ["follow_up", "broader_story_arc", "uncertain"],
                )
            )
        )
    )
    if not needs_confirmation and not needs_ambiguity_review:
        return capsule_output

    confirmation_prompt = (
        system_prompt
        + "\n\nThis is the authoritative full-record review. Read both complete records "
        "independently and resolve generic or unnamed entities from the supplied record context "
        "when the evidence supports it. Return same_event only when both records describe the "
        "same concrete event; otherwise return the correct relationship. Set "
        "requires_full_record_review=false because complete records are already present."
    )
    full_record_config = {
        **config,
        **dict(config.get("full_record_review") or {}),
    }
    return _invoke_context(
        batch=batch,
        batch_index=batch_index,
        attempt=attempt,
        config=full_record_config,
        llm=full_record_llm or llm,
        system_prompt=confirmation_prompt,
        llm_calls=llm_calls,
        include_full_records=True,
        module_name="pair_adjudication_full_confirmation",
    )


def _pair_has_unresolved_named_identity(batch: list[dict[str, Any]]) -> bool:
    for item in batch:
        for field_name in ("left_record", "right_record"):
            identity = dict(
                (item.get(field_name) or {}).get("story_mapping_event_identity") or {}
            )
            if identity.get("named_identity_supported") is False:
                return True
    return False


def _invoke_context(
    *,
    batch: list[dict],
    batch_index: int,
    attempt: int,
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
    include_full_records: bool,
    module_name: str,
) -> list[dict]:
    payload = _pair_payload(batch, include_full_records=include_full_records)
    prompt_inputs = {
        "system_prompt": system_prompt,
        "pair_payload": json.dumps(payload, ensure_ascii=False, indent=2),
    }
    rendered = PAIR_PROMPT.format(**prompt_inputs)
    structured_options: dict[str, Any] = {"include_raw": True}
    if clean_text(config.get("provider")).casefold() == "openai":
        structured_options["strict"] = True
    chain = PAIR_PROMPT | llm.with_structured_output(PairDecisionBatch, **structured_options)
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
        output = parsed if isinstance(parsed, PairDecisionBatch) else PairDecisionBatch.model_validate(parsed)
        parsed_dict = output.model_dump(mode="json")
        _validate_coverage(parsed_dict["decisions"], batch)
    except Exception as exc:
        llm_calls.append(
            build_llm_call_log(
                module_name=module_name,
                provider=config["provider"],
                model=config["model"],
                rendered_prompt=rendered,
                raw_response=raw,
                parsed_output=parsed_dict,
                metadata=_batch_metadata(
                    payload,
                    batch_index=batch_index,
                    attempt=attempt,
                    include_full_records=include_full_records,
                ),
                duration_seconds=time.time() - started,
                parse_error=str(exc),
            )
        )
        raise
    llm_calls.append(
        build_llm_call_log(
            module_name=module_name,
            provider=config["provider"],
            model=config["model"],
            rendered_prompt=rendered,
            raw_response=raw,
            parsed_output=parsed_dict,
            metadata=_batch_metadata(
                payload,
                batch_index=batch_index,
                attempt=attempt,
                include_full_records=include_full_records,
            ),
            duration_seconds=time.time() - started,
        )
    )
    return [
        {**item, "decision_source": "llm"}
        for item in parsed_dict["decisions"]
    ]


def _validate_coverage(decisions: list[dict], batch: list[dict]) -> None:
    expected = {item["pair_id"] for item in batch}
    returned = [clean_text(item.get("pair_id")) for item in decisions]
    if len(returned) != len(set(returned)) or set(returned) != expected:
        raise ValueError(
            f"pair adjudication coverage mismatch; missing={sorted(expected - set(returned))}, "
            f"unknown={sorted(set(returned) - expected)}"
        )


def _candidate_batches(
    candidates: list[dict[str, Any]],
    *,
    batch_size: int,
    max_batch_chars: int,
    max_single_pair_chars: int | None = None,
) -> list[list[dict[str, Any]]]:
    single_pair_limit = max_single_pair_chars or max_batch_chars
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for candidate in candidates:
        trial = [*current, candidate]
        trial_chars = len(
            json.dumps(_pair_payload(trial, include_full_records=False), ensure_ascii=False)
        )
        if current and (len(trial) > batch_size or trial_chars > max_batch_chars):
            batches.append(current)
            current = [candidate]
        else:
            current = trial
        current_chars = len(
            json.dumps(_pair_payload(current, include_full_records=False), ensure_ascii=False)
        )
        full_pair_chars = len(
            json.dumps(
                _pair_payload([candidate], include_full_records=True),
                ensure_ascii=False,
            )
        )
        if full_pair_chars > single_pair_limit:
            raise ValueError(
                "A complete story-mapping pair exceeds pair_adjudication.max_single_pair_chars; "
                "the normalized semantic context was not truncated. "
                f"pair_id={candidate.get('pair_id')}, serialized_chars={full_pair_chars}, "
                f"configured_limit={single_pair_limit}"
            )
        if current_chars > max_batch_chars:
            if len(current) == 1 and current_chars <= single_pair_limit:
                batches.append(current)
                current = []
            else:
                raise ValueError(
                    "A complete story-mapping pair exceeds pair_adjudication.max_single_pair_chars; "
                    "the normalized semantic context was not truncated. "
                    f"pair_id={candidate.get('pair_id')}, serialized_chars={current_chars}, "
                    f"configured_limit={single_pair_limit}"
                )
    if current:
        batches.append(current)
    return batches


def _pair_payload(
    batch: list[dict[str, Any]],
    *,
    include_full_records: bool = True,
) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    pairs: list[dict[str, Any]] = []
    for item in batch:
        left = dict(item.get("left_record") or {})
        right = dict(item.get("right_record") or {})
        left_key = clean_text(left.get("record_key"))
        right_key = clean_text(right.get("record_key"))
        if left_key:
            records[left_key] = left if include_full_records else _event_capsule_record(left)
        if right_key:
            records[right_key] = right if include_full_records else _event_capsule_record(right)
        pairs.append(
            {
                **{
                    key: value
                    for key, value in item.items()
                    if key not in {"left_record", "right_record"}
                },
                "left_record_key": left_key,
                "right_record_key": right_key,
            }
        )
    return {
        "task": "Classify the temporal/story relationship for this candidate record pair.",
        "context_mode": "complete_records" if include_full_records else "event_identity_capsules",
        "pairs": pairs,
        "records_by_key": records,
        "required_pair_ids": [item["pair_id"] for item in batch],
    }


def _event_capsule_record(record: dict[str, Any]) -> dict[str, Any]:
    identity = dict(record.get("story_mapping_event_identity") or {})
    return {
        "record_key": clean_text(record.get("record_key")),
        "title": clean_text(record.get("title")),
        "url": clean_text(record.get("url")),
        "published_at": clean_text(record.get("published_at")),
        "source": clean_text(record.get("source")),
        "source_group": clean_text(record.get("source_group")),
        "source_relationship": clean_text(record.get("source_relationship")),
        "event_identity": identity,
        "triage_story_keys": list(record.get("triage_story_keys") or []),
    }


def _batch_metadata(
    payload: dict[str, Any],
    *,
    batch_index: int,
    attempt: int,
    include_full_records: bool,
) -> dict[str, Any]:
    records = dict(payload.get("records_by_key") or {})
    return {
        "batch_index": batch_index,
        "attempt": attempt,
        "pair_count": len(payload.get("pairs") or []),
        "record_count": len(records),
        "record_keys": list(records),
        "serialized_context_chars": len(json.dumps(payload, ensure_ascii=False)),
        "source_context_mode": (
            "complete_normalized_semantic_records"
            if include_full_records
            else "llm_event_identity_capsules"
        ),
        "records_truncated": False,
    }
