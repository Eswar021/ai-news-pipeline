from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from .llm_logging import build_llm_call_log
from .utils import clean_text, text_token_count


CLUSTER_RECONCILIATION_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\nProposed semantic component:\n{component_payload}"
)


class ReconciledRecordGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_ref: str
    record_keys: list[str] = Field(min_length=1)
    relationship: Literal[
        "same_event_coverage",
        "coherent_event_update",
        "standalone_record",
    ]
    canonical_event: str
    rationale: str


class ComponentReconciliationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str
    groups: list[ReconciledRecordGroup] = Field(min_length=1)


def reconcile_components(
    components: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> dict[str, list[list[str]]]:
    """Partition each proposed component into coherent story-record groups."""
    if not components:
        return {}

    worker_count = min(max(1, int(config.get("worker_count", 1))), len(components))
    ordered: list[tuple[str, list[list[str]], list[dict[str, Any]]] | None] = [
        None
    ] * len(components)

    def process(index: int, component: dict[str, Any]):
        local_calls: list[dict[str, Any]] = []
        groups = _reconcile_component(
            component,
            config=config,
            llm=llm,
            system_prompt=system_prompt,
            llm_calls=local_calls,
        )
        return index, clean_text(component.get("component_id")), groups, local_calls

    if worker_count == 1:
        for index, component in enumerate(components):
            _, component_id, groups, local_calls = process(index, component)
            ordered[index] = (component_id, groups, local_calls)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(process, index, component): index
                for index, component in enumerate(components)
            }
            for future in as_completed(futures):
                index, component_id, groups, local_calls = future.result()
                ordered[index] = (component_id, groups, local_calls)

    output: dict[str, list[list[str]]] = {}
    for item in ordered:
        if item is None:
            raise RuntimeError("Cluster reconciliation completed with a missing component result")
        component_id, groups, local_calls = item
        output[component_id] = groups
        llm_calls.extend(local_calls)
    return output


def _reconcile_component(
    component: dict[str, Any],
    *,
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> list[list[str]]:
    payload = {
        "task": (
            "Partition these records into the real news events/editorial stories they describe. "
            "Every record must appear exactly once."
        ),
        **component,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(serialized) > int(config["max_component_chars"]):
        raise ValueError(
            "A proposed story component exceeds cluster_reconciliation.max_component_chars; "
            "source context was not truncated. "
            f"component_id={clean_text(component.get('component_id'))}, "
            f"serialized_chars={len(serialized)}"
        )
    serialized_tokens = text_token_count(
        serialized,
        model=config["model"],
        fallback_encoding=config["tokenizer_encoding"],
    )
    if serialized_tokens > int(config["max_component_tokens"]):
        raise ValueError(
            "A proposed story component exceeds cluster_reconciliation.max_component_tokens; "
            "the semantic capsule context was not truncated and no provider call was made. "
            f"component_id={clean_text(component.get('component_id'))}, "
            f"serialized_tokens={serialized_tokens}, "
            f"configured_limit={config['max_component_tokens']}"
        )

    prompt_inputs = {
        "system_prompt": system_prompt,
        "component_payload": serialized,
    }
    rendered = CLUSTER_RECONCILIATION_PROMPT.format(**prompt_inputs)
    structured_options: dict[str, Any] = {"include_raw": True}
    if clean_text(config.get("provider")).casefold() == "openai":
        structured_options["strict"] = True
    chain = CLUSTER_RECONCILIATION_PROMPT | llm.with_structured_output(
        ComponentReconciliationOutput,
        **structured_options,
    )

    expected_keys = [
        clean_text(record.get("record_key"))
        for record in component.get("records") or []
    ]
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
                if isinstance(parsed, ComponentReconciliationOutput)
                else ComponentReconciliationOutput.model_validate(parsed)
            )
            parsed_dict = output.model_dump(mode="json")
            _validate_partition(parsed_dict, component, expected_keys)
            groups = [list(group["record_keys"]) for group in parsed_dict["groups"]]
            llm_calls.append(
                build_llm_call_log(
                    module_name="cluster_reconciliation",
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered,
                    raw_response=raw,
                    parsed_output=parsed_dict,
                    metadata={
                        "component_id": clean_text(component.get("component_id")),
                        "attempt": attempt,
                        "record_count": len(expected_keys),
                        "record_keys": expected_keys,
                        "serialized_context_chars": len(serialized),
                        "serialized_context_tokens": serialized_tokens,
                        "source_context_mode": (
                            "event_identity_capsules_extracted_from_complete_records"
                        ),
                        "records_truncated": False,
                    },
                    duration_seconds=time.time() - started,
                )
            )
            return groups
        except Exception as exc:
            last_error = clean_text(exc)
            llm_calls.append(
                build_llm_call_log(
                    module_name="cluster_reconciliation",
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered,
                    raw_response=raw,
                    parsed_output=parsed_dict,
                    metadata={
                        "component_id": clean_text(component.get("component_id")),
                        "attempt": attempt,
                        "record_count": len(expected_keys),
                        "record_keys": expected_keys,
                        "serialized_context_chars": len(serialized),
                        "serialized_context_tokens": serialized_tokens,
                        "source_context_mode": (
                            "event_identity_capsules_extracted_from_complete_records"
                        ),
                        "records_truncated": False,
                    },
                    duration_seconds=time.time() - started,
                    parse_error=last_error,
                )
            )

    raise RuntimeError(
        "Cluster reconciliation failed after bounded retries for "
        f"{clean_text(component.get('component_id'))}: {last_error}"
    )


def _validate_partition(
    output: dict[str, Any],
    component: dict[str, Any],
    expected_keys: list[str],
) -> None:
    component_id = clean_text(component.get("component_id"))
    if clean_text(output.get("component_id")) != component_id:
        raise ValueError(
            "cluster reconciliation component_id mismatch: "
            f"expected={component_id}, returned={clean_text(output.get('component_id'))}"
        )
    returned_keys = [
        clean_text(record_key)
        for group in output.get("groups") or []
        for record_key in group.get("record_keys") or []
    ]
    expected = set(expected_keys)
    returned = set(returned_keys)
    if (
        any(not key for key in returned_keys)
        or len(returned_keys) != len(returned)
        or returned != expected
    ):
        raise ValueError(
            "cluster reconciliation record coverage mismatch; "
            f"missing={sorted(expected - returned)}, unknown={sorted(returned - expected)}, "
            f"duplicates={sorted(key for key in returned if returned_keys.count(key) > 1)}"
        )
