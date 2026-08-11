from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import time
from typing import Any

from langchain_core.prompts import PromptTemplate

from .config import PROMPT_MODULE
from .contract import (
    EditorialTriageRequest,
    EditorialTriageResponse,
    TriageBatchOutput,
)
from src.pipeline.llm import make_llm
from .llm_logging import build_llm_call_log
from .prompt_loader import load_prompt_bundle
from .utils import build_record_context, clean_text, record_context_chars, record_key


IST = timezone(timedelta(hours=5, minutes=30))
TASK_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\n{user_preamble}\n\nTask payload:\n{task_payload}"
)


def run(input_json: dict) -> dict:
    request = EditorialTriageRequest.model_validate(input_json)
    run_id = request.run.run_id
    generated_at = datetime.now(IST).isoformat()
    config = request.config.model_dump(mode="json")
    evidence = request.input.evidence_prep
    upstream_run_id = clean_text(evidence.data.run_id)
    if upstream_run_id and upstream_run_id != run_id:
        raise ValueError(
            f"editorial_triage run_id mismatch: request={run_id}, evidence_prep={upstream_run_id}"
        )

    source_records = [
        {
            **record,
            "triage_origin": "evidence_prep",
            "record_available_for_story_mapping": True,
        }
        for record in evidence.data.records
    ]
    if request.input.news_collection is not None:
        source_records.extend(
            _collector_quarantine_records(request.input.news_collection.data.candidate_ledger)
        )
    records = _unique_records(source_records)
    if not config["enabled"]:
        return _disabled_response(
            run_id,
            generated_at,
            len(records),
            mode=config["mode"],
        )
    if not records:
        return _response(
            run_id=run_id,
            generated_at=generated_at,
            decisions=[],
            llm_calls=[],
            batch_count=0,
            failed_batch_count=0,
            failure_reason="evidence_prep contains no candidate records",
            mode=config["mode"],
            story_mapping_actions=config["story_mapping_actions"],
        )

    prompt_bundle = load_prompt_bundle(config["prompt_version"])
    llm = make_llm(
        provider=config["provider"],
        model=config["model"],
        temperature=float(config["temperature"]),
        base_url=config.get("base_url"),
    )
    llm_calls: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    batches, context_telemetry = _complete_context_batches(
        records,
        batch_size=int(config["batch_size"]),
        max_record_context_chars=int(config["max_record_context_chars"]),
        max_batch_context_chars=int(config["max_batch_context_chars"]),
    )
    failed_batch_count = 0
    failed_batch_errors: list[dict[str, Any]] = []

    for batch_index, batch in enumerate(batches, start=1):
        batch_decisions: list[dict[str, Any]] | None = None
        last_error = ""
        for attempt in range(1, int(config["max_attempts"]) + 1):
            try:
                batch_decisions = _invoke_batch(
                    batch=batch,
                    batch_index=batch_index,
                    attempt=attempt,
                    config=config,
                    prompt_bundle=prompt_bundle,
                    llm=llm,
                    llm_calls=llm_calls,
                )
                break
            except Exception as exc:
                last_error = str(exc)
        if batch_decisions is None:
            failed_batch_count += 1
            failed_batch_errors.append(
                {
                    "batch_index": batch_index,
                    "record_count": len(batch),
                    "error": clean_text(last_error),
                }
            )
            batch_decisions = [
                _unresolved_decision(record, batch_index, last_error)
                for record in batch
            ]
        decisions.extend(batch_decisions)

    failure_reason = ""
    if failed_batch_count:
        first_error = clean_text(failed_batch_errors[0].get("error")) if failed_batch_errors else ""
        failure_reason = f"{failed_batch_count} of {len(batches)} triage batches were unresolved"
        if first_error:
            failure_reason = f"{failure_reason}; first_error={first_error}"
    return _response(
        run_id=run_id,
        generated_at=generated_at,
        decisions=decisions,
        llm_calls=llm_calls,
        batch_count=len(batches),
        failed_batch_count=failed_batch_count,
        failure_reason=failure_reason,
        mode=config["mode"],
        story_mapping_actions=config["story_mapping_actions"],
        context_telemetry=context_telemetry,
        failed_batch_errors=failed_batch_errors,
    )


def _invoke_batch(
    *,
    batch: list[dict[str, Any]],
    batch_index: int,
    attempt: int,
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    context_records = [
        build_record_context(record, max_chars=int(config["max_record_context_chars"]))
        for record in batch
    ]
    payload = {
        "task": "Semantically triage each candidate for a future AI-news roundup.",
        "mode": config["mode"],
        "channel": config["channel"],
        "action_contract": {
            "advance": "Strong enough to enter story grouping now.",
            "reserve": "Potentially useful or uncertain; preserve for comparison/follow-up.",
            "quarantine": "Clearly unusable, malformed, duplicate-like, promotional, or outside the channel scope.",
        },
        "records": context_records,
        "required_record_keys": [item["record_key"] for item in context_records],
    }
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": json.dumps(payload, ensure_ascii=False, indent=2),
    }
    rendered_prompt = TASK_PROMPT.format(**prompt_inputs)
    chain = TASK_PROMPT | llm.with_structured_output(TriageBatchOutput, include_raw=True)
    started = time.time()
    raw = None
    parsed_dict: dict[str, Any] | None = None
    try:
        result = chain.invoke(prompt_inputs)
        raw = result.get("raw") if isinstance(result, dict) else None
        parsed = result.get("parsed") if isinstance(result, dict) else result
        parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
        if parsing_error is not None or parsed is None:
            raise ValueError(f"structured output parsing failed: {parsing_error}")
        output = TriageBatchOutput.model_validate(parsed)
        parsed_dict = output.model_dump(mode="json")
        decisions = parsed_dict["decisions"]
        _validate_batch_coverage(decisions, context_records)
    except Exception as exc:
        llm_calls.append(
            build_llm_call_log(
                provider=config["provider"],
                model=config["model"],
                rendered_prompt=rendered_prompt,
                raw_response=raw,
                parsed_output=parsed_dict,
                metadata=_context_metadata(
                    context_records,
                    batch_index=batch_index,
                    attempt=attempt,
                ),
                duration_seconds=time.time() - started,
                parse_error=str(exc),
            )
        )
        raise

    llm_calls.append(
        build_llm_call_log(
            provider=config["provider"],
            model=config["model"],
            rendered_prompt=rendered_prompt,
            raw_response=raw,
            parsed_output=parsed_dict,
            metadata=_context_metadata(
                context_records,
                batch_index=batch_index,
                attempt=attempt,
            ),
            duration_seconds=time.time() - started,
        )
    )
    records_by_key = {record_key(record): record for record in batch}
    return [
        {
            **decision,
            "decision_source": "llm",
            "batch_index": batch_index,
            "triage_origin": clean_text(
                records_by_key[decision["record_key"]].get("triage_origin")
            ) or "evidence_prep",
            "record_available_for_story_mapping": bool(
                records_by_key[decision["record_key"]].get(
                    "record_available_for_story_mapping", True
                )
            ),
        }
        for decision in decisions
    ]


def _validate_batch_coverage(decisions: list[dict], context_records: list[dict]) -> None:
    expected = [item["record_key"] for item in context_records]
    returned = [clean_text(item.get("record_key")) for item in decisions]
    if len(returned) != len(set(returned)):
        raise ValueError("editorial triage returned duplicate record keys")
    if set(returned) != set(expected):
        missing = sorted(set(expected) - set(returned))
        unknown = sorted(set(returned) - set(expected))
        raise ValueError(f"editorial triage record coverage mismatch; missing={missing}, unknown={unknown}")


def _unresolved_decision(record: dict, batch_index: int, error: str) -> dict:
    return {
        "record_key": record_key(record),
        "topic_relevance": "uncertain",
        "newsworthiness": "uncertain",
        "audience_value": "uncertain",
        "content_usability": "uncertain",
        "likely_content_type": "other",
        "novelty": "uncertain",
        "confidence": 0.0,
        "reason": f"LLM triage unresolved after bounded retries: {clean_text(error)}",
        "possible_story_keys": [],
        "recommended_action": "reserve",
        "decision_source": "unresolved",
        "batch_index": batch_index,
        "triage_origin": clean_text(record.get("triage_origin")) or "evidence_prep",
        "record_available_for_story_mapping": bool(
            record.get("record_available_for_story_mapping", True)
        ),
    }


def _unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for record in records:
        key = record_key(record)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _collector_quarantine_records(candidate_ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in candidate_ledger:
        decision = clean_text(item.get("decision"))
        if decision not in {"quarantined", "fetch_failed", "not_processed"}:
            continue
        records.append(
            {
                "record_key": clean_text(item.get("candidate_key")),
                "source": clean_text(item.get("source")),
                "source_group": clean_text(item.get("source_group")),
                "source_type": "collector_candidate",
                "title": clean_text(item.get("title")),
                "url": clean_text(item.get("url")),
                "published_at": clean_text(item.get("published_at")),
                "content": clean_text(item.get("reason")),
                "quality_flags": item.get("quality_flags", {}),
                "retrieval_diagnostics": {
                    "decision": decision,
                    "reason_codes": [clean_text(item.get("reason_code"))],
                    "retrieval_hints": item.get("retrieval_hints", {}),
                },
                "triage_origin": "news_collection_candidate_ledger",
                "record_available_for_story_mapping": False,
            }
        )
    return records


def _complete_context_batches(
    records: list[dict[str, Any]],
    *,
    batch_size: int,
    max_record_context_chars: int,
    max_batch_context_chars: int,
) -> tuple[list[list[dict[str, Any]]], dict[str, Any]]:
    # An anomalously huge record (e.g. a release page with its whole changelog +
    # comment thread) is truncated to the per-record budget rather than hard-failing
    # the run; the truncation is flagged in each context's provenance. Only the LLM's
    # triage context is bounded — the full record still flows downstream.
    contexts = [
        (record, build_record_context(record, max_chars=max_record_context_chars))
        for record in records
    ]
    record_sizes = {
        context["record_key"]: record_context_chars(context)
        for _record, context in contexts
    }
    truncated_record_keys = [
        context["record_key"]
        for _record, context in contexts
        if context.get("semantic_content_provenance", {}).get("truncated")
    ]

    batches: list[list[dict[str, Any]]] = []
    current_records: list[dict[str, Any]] = []
    current_contexts: list[dict[str, Any]] = []
    for record, context in contexts:
        trial_contexts = [*current_contexts, context]
        trial_chars = len(
            json.dumps(trial_contexts, ensure_ascii=False, separators=(",", ":"))
        )
        if current_records and (
            len(trial_contexts) > batch_size
            or trial_chars > max_batch_context_chars
        ):
            batches.append(current_records)
            current_records = [record]
            current_contexts = [context]
        else:
            current_records.append(record)
            current_contexts = trial_contexts
    if current_records:
        batches.append(current_records)

    batch_sizes = [
        len(
            json.dumps(
                [
                    build_record_context(record, max_chars=max_record_context_chars)
                    for record in batch
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        for batch in batches
    ]
    if any(size > max_batch_context_chars for size in batch_sizes):
        raise ValueError(
            "A complete editorial-triage batch exceeds config.max_batch_context_chars; "
            "no source content was truncated."
        )
    return batches, {
        "context_mode": "complete_normalized_records",
        "records_truncated": bool(truncated_record_keys),
        "truncated_record_keys": truncated_record_keys,
        "record_count": len(records),
        "record_context_chars": record_sizes,
        "batch_context_chars": batch_sizes,
    }


def _context_metadata(
    context_records: list[dict[str, Any]],
    *,
    batch_index: int,
    attempt: int,
) -> dict[str, Any]:
    return {
        "batch_index": batch_index,
        "attempt": attempt,
        "record_count": len(context_records),
        "record_keys": [item["record_key"] for item in context_records],
        "record_context_chars": {
            item["record_key"]: record_context_chars(item)
            for item in context_records
        },
        "serialized_context_chars": len(
            json.dumps(context_records, ensure_ascii=False, separators=(",", ":"))
        ),
        "source_context_mode": "complete_normalized_records",
        "records_truncated": any(
            item.get("semantic_content_provenance", {}).get("truncated")
            for item in context_records
        ),
    }


def _response(
    *,
    run_id: str,
    generated_at: str,
    decisions: list[dict[str, Any]],
    llm_calls: list[dict[str, Any]],
    batch_count: int,
    failed_batch_count: int,
    failure_reason: str,
    mode: str,
    story_mapping_actions: list[str],
    context_telemetry: dict[str, Any] | None = None,
    failed_batch_errors: list[dict[str, Any]] | None = None,
) -> dict:
    unresolved_count = sum(1 for item in decisions if item.get("decision_source") == "unresolved")
    action_counts = dict(Counter(item.get("recommended_action", "unknown") for item in decisions))
    pools = {
        f"{action}_record_keys": [
            item["record_key"]
            for item in decisions
            if item.get("recommended_action") == action
        ]
        for action in ("advance", "reserve", "quarantine")
    }
    story_mapping_action_set = set(story_mapping_actions)
    pools["story_mapping_record_keys"] = [
        item["record_key"]
        for item in decisions
        if item.get("recommended_action") in story_mapping_action_set
        and bool(item.get("record_available_for_story_mapping", True))
    ]
    pools["retrieval_required_record_keys"] = [
        item["record_key"]
        for item in decisions
        if item.get("recommended_action") in story_mapping_action_set
        and not bool(item.get("record_available_for_story_mapping", True))
    ]
    if not decisions:
        status = "failed"
    elif unresolved_count:
        status = "partial"
    else:
        status = "ok"
    response = EditorialTriageResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "mode": mode,
            "input_record_count": len(decisions),
            "decision_count": len(decisions),
            "decisions": decisions,
            "pools": pools,
        },
        summary={
            "input_record_count": len(decisions),
            "decision_count": len(decisions),
            "resolved_count": len(decisions) - unresolved_count,
            "unresolved_count": unresolved_count,
            "action_counts": action_counts,
            "batch_count": batch_count,
            "failed_batch_count": failed_batch_count,
            "llm_call_count": len(llm_calls),
            "failure_reason": failure_reason,
            "failed_batch_errors": failed_batch_errors or [],
            "source_context": context_telemetry or {},
        },
        handoff={
            "authoritative": mode == "authoritative",
            "ready_for_editorial_review": bool(decisions),
            "ready_for_story_mapping": (
                status == "ok"
                and mode == "authoritative"
                and bool(pools["story_mapping_record_keys"])
            ),
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _disabled_response(
    run_id: str,
    generated_at: str,
    input_record_count: int,
    *,
    mode: str,
) -> dict:
    response = EditorialTriageResponse(
        status="ok",
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "mode": mode,
            "input_record_count": input_record_count,
            "decision_count": 0,
            "decisions": [],
            "pools": {
                "advance_record_keys": [],
                "reserve_record_keys": [],
                "quarantine_record_keys": [],
                "story_mapping_record_keys": [],
                "retrieval_required_record_keys": [],
            },
        },
        summary={
            "input_record_count": input_record_count,
            "decision_count": 0,
            "resolved_count": 0,
            "unresolved_count": 0,
            "action_counts": {},
            "batch_count": 0,
            "failed_batch_count": 0,
            "llm_call_count": 0,
            "failure_reason": "",
            "disabled": True,
        },
        handoff={
            "authoritative": False,
            "ready_for_editorial_review": False,
            "ready_for_story_mapping": False,
        },
        llm_calls=[],
    )
    return response.model_dump(mode="json")
