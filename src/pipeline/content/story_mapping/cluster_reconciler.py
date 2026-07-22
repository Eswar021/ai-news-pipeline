from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
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
CLUSTER_CONFLICT_RESOLUTION_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\nConflicting record assignments:\n{conflict_payload}"
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


class ConflictingRecordDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_key: str
    selected_candidate_id: str
    rationale: str


class ConflictResolutionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str
    decisions: list[ConflictingRecordDecision] = Field(min_length=1)


class PartitionCoverageError(ValueError):
    def __init__(
        self,
        *,
        missing: list[str],
        unknown: list[str],
        conflicting_assignments: dict[str, list[str]],
    ) -> None:
        self.missing = missing
        self.unknown = unknown
        self.conflicting_assignments = conflicting_assignments
        super().__init__(
            "cluster reconciliation record coverage mismatch; "
            f"missing={missing}, unknown={unknown}, "
            f"conflicting_assignments={conflicting_assignments}"
        )

    @property
    def has_only_conflicts(self) -> bool:
        return bool(self.conflicting_assignments) and not self.missing and not self.unknown


def reconcile_components(
    components: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    llm,
    system_prompt: str,
    conflict_system_prompt: str = "",
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
            conflict_system_prompt=conflict_system_prompt,
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
    conflict_system_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> list[list[str]]:
    payload = {
        "task": (
            "Partition these records into the real news events/editorial stories they describe. "
            "Every record must appear exactly once."
        ),
        **component,
    }
    base_serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(base_serialized) > int(config["max_component_chars"]):
        raise ValueError(
            "A proposed story component exceeds cluster_reconciliation.max_component_chars; "
            "source context was not truncated. "
            f"component_id={clean_text(component.get('component_id'))}, "
            f"serialized_chars={len(base_serialized)}"
        )
    base_serialized_tokens = text_token_count(
        base_serialized,
        model=config["model"],
        fallback_encoding=config["tokenizer_encoding"],
    )
    if base_serialized_tokens > int(config["max_component_tokens"]):
        raise ValueError(
            "A proposed story component exceeds cluster_reconciliation.max_component_tokens; "
            "the semantic capsule context was not truncated and no provider call was made. "
            f"component_id={clean_text(component.get('component_id'))}, "
            f"serialized_tokens={base_serialized_tokens}, "
            f"configured_limit={config['max_component_tokens']}"
        )

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
    previous_invalid_output: dict[str, Any] | None = None
    for attempt in range(1, int(config["max_attempts"]) + 1):
        attempt_payload = deepcopy(payload)
        if last_error:
            attempt_payload["structural_correction"] = {
                "validation_error": last_error,
                "previous_output": previous_invalid_output,
                "instruction": (
                    "Return the complete partition again. Keep the semantic grouping unless "
                    "needed to resolve the stated structural error, and assign every provided "
                    "record_key to exactly one group."
                ),
            }
        attempt_serialized = json.dumps(attempt_payload, ensure_ascii=False, indent=2)
        prompt_inputs = {
            "system_prompt": system_prompt,
            "component_payload": attempt_serialized,
        }
        rendered = CLUSTER_RECONCILIATION_PROMPT.format(**prompt_inputs)
        started = time.time()
        raw = None
        parsed_dict = None
        normalized_output = None
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
            normalized_output, duplicate_keys_removed = _normalize_same_group_duplicates(
                parsed_dict
            )
            _validate_partition(normalized_output, component, expected_keys)
            groups = [
                list(group["record_keys"])
                for group in normalized_output["groups"]
            ]
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
                        "serialized_context_chars": len(base_serialized),
                        "serialized_context_tokens": base_serialized_tokens,
                        "attempt_prompt_chars": len(attempt_serialized),
                        "structural_repair_feedback_included": bool(last_error),
                        "same_group_duplicate_record_keys_removed": (
                            duplicate_keys_removed
                        ),
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
            previous_invalid_output = parsed_dict
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
                        "serialized_context_chars": len(base_serialized),
                        "serialized_context_tokens": base_serialized_tokens,
                        "attempt_prompt_chars": len(attempt_serialized),
                        "structural_repair_feedback_included": attempt > 1,
                        "source_context_mode": (
                            "event_identity_capsules_extracted_from_complete_records"
                        ),
                        "records_truncated": False,
                    },
                    duration_seconds=time.time() - started,
                    parse_error=last_error,
                )
            )
            if (
                isinstance(exc, PartitionCoverageError)
                and exc.has_only_conflicts
                and normalized_output is not None
            ):
                if not clean_text(conflict_system_prompt):
                    raise ValueError(
                        "cluster conflict-resolution prompt is required for "
                        "cross-group record assignments"
                    ) from exc
                resolved_output = _resolve_conflicting_assignments(
                    component=component,
                    partition=normalized_output,
                    conflicts=exc.conflicting_assignments,
                    expected_keys=expected_keys,
                    config=config,
                    llm=llm,
                    system_prompt=conflict_system_prompt,
                    llm_calls=llm_calls,
                )
                return [
                    list(group["record_keys"])
                    for group in resolved_output["groups"]
                ]

    raise RuntimeError(
        "Cluster reconciliation failed after bounded retries for "
        f"{clean_text(component.get('component_id'))}: {last_error}"
    )


def _resolve_conflicting_assignments(
    *,
    component: dict[str, Any],
    partition: dict[str, Any],
    conflicts: dict[str, list[str]],
    expected_keys: list[str],
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    payload, candidate_group_indices = _conflict_resolution_payload(
        component=component,
        partition=partition,
        conflicts=conflicts,
    )
    base_serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    structured_options: dict[str, Any] = {"include_raw": True}
    if clean_text(config.get("provider")).casefold() == "openai":
        structured_options["strict"] = True
    chain = CLUSTER_CONFLICT_RESOLUTION_PROMPT | llm.with_structured_output(
        ConflictResolutionOutput,
        **structured_options,
    )

    last_error = ""
    previous_invalid_output: dict[str, Any] | None = None
    for attempt in range(1, int(config["max_attempts"]) + 1):
        attempt_payload = deepcopy(payload)
        if last_error:
            attempt_payload["structural_correction"] = {
                "validation_error": last_error,
                "previous_output": previous_invalid_output,
                "instruction": "Return exactly one valid decision for each conflicting record.",
            }
        serialized = json.dumps(attempt_payload, ensure_ascii=False, indent=2)
        prompt_inputs = {
            "system_prompt": system_prompt,
            "conflict_payload": serialized,
        }
        rendered = CLUSTER_CONFLICT_RESOLUTION_PROMPT.format(**prompt_inputs)
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
                if isinstance(parsed, ConflictResolutionOutput)
                else ConflictResolutionOutput.model_validate(parsed)
            )
            parsed_dict = output.model_dump(mode="json")
            selected_indices = _validate_conflict_resolution(
                parsed_dict,
                component_id=clean_text(component.get("component_id")),
                conflicts=conflicts,
                candidate_group_indices=candidate_group_indices,
            )
            resolved = _apply_conflict_resolution(
                partition,
                selected_group_indices=selected_indices,
            )
            _validate_partition(resolved, component, expected_keys)
            llm_calls.append(
                build_llm_call_log(
                    module_name="cluster_reconciliation_conflict_resolution",
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered,
                    raw_response=raw,
                    parsed_output=parsed_dict,
                    metadata={
                        "component_id": clean_text(component.get("component_id")),
                        "attempt": attempt,
                        "conflicting_record_keys": sorted(conflicts),
                        "serialized_context_chars": len(base_serialized),
                        "structural_repair_feedback_included": bool(last_error),
                        "semantic_decision_scope": "conflicting_record_group_ownership_only",
                    },
                    duration_seconds=time.time() - started,
                )
            )
            return resolved
        except Exception as exc:
            last_error = clean_text(exc)
            previous_invalid_output = parsed_dict
            llm_calls.append(
                build_llm_call_log(
                    module_name="cluster_reconciliation_conflict_resolution",
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered,
                    raw_response=raw,
                    parsed_output=parsed_dict,
                    metadata={
                        "component_id": clean_text(component.get("component_id")),
                        "attempt": attempt,
                        "conflicting_record_keys": sorted(conflicts),
                        "serialized_context_chars": len(base_serialized),
                        "structural_repair_feedback_included": attempt > 1,
                        "semantic_decision_scope": "conflicting_record_group_ownership_only",
                    },
                    duration_seconds=time.time() - started,
                    parse_error=last_error,
                )
            )

    raise RuntimeError(
        "Cluster conflict resolution failed after bounded retries for "
        f"{clean_text(component.get('component_id'))}: {last_error}"
    )


def _conflict_resolution_payload(
    *,
    component: dict[str, Any],
    partition: dict[str, Any],
    conflicts: dict[str, list[str]],
) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    records_by_key = {
        clean_text(record.get("record_key")): record
        for record in component.get("records") or []
    }
    candidate_group_indices: dict[str, dict[str, int]] = {}
    conflict_items: list[dict[str, Any]] = []
    for record_key in sorted(conflicts):
        candidates: list[dict[str, Any]] = []
        index_by_candidate: dict[str, int] = {}
        for group_index, group in enumerate(partition.get("groups") or []):
            if record_key not in group.get("record_keys", []):
                continue
            candidate_id = f"candidate_{len(candidates) + 1}"
            index_by_candidate[candidate_id] = group_index
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "group_ref": clean_text(group.get("group_ref")),
                    "relationship": clean_text(group.get("relationship")),
                    "canonical_event": clean_text(group.get("canonical_event")),
                    "rationale": clean_text(group.get("rationale")),
                    "other_record_keys": [
                        key
                        for key in group.get("record_keys") or []
                        if key != record_key
                    ],
                }
            )
        candidate_group_indices[record_key] = index_by_candidate
        relevant_pair_decisions = [
            decision
            for decision in component.get("pair_decisions") or []
            if record_key
            in {
                clean_text(decision.get("left_record_key")),
                clean_text(decision.get("right_record_key")),
            }
        ]
        conflict_items.append(
            {
                "record_key": record_key,
                "record_context": records_by_key.get(record_key, {}),
                "candidate_groups": candidates,
                "relevant_pair_decisions": relevant_pair_decisions,
            }
        )
    return (
        {
            "component_id": clean_text(component.get("component_id")),
            "task": "Choose one candidate semantic group for each conflicting record.",
            "conflicts": conflict_items,
            "required_record_keys": sorted(conflicts),
        },
        candidate_group_indices,
    )


def _validate_conflict_resolution(
    output: dict[str, Any],
    *,
    component_id: str,
    conflicts: dict[str, list[str]],
    candidate_group_indices: dict[str, dict[str, int]],
) -> dict[str, int]:
    if clean_text(output.get("component_id")) != component_id:
        raise ValueError(
            "cluster conflict-resolution component_id mismatch: "
            f"expected={component_id}, returned={clean_text(output.get('component_id'))}"
        )
    decisions = output.get("decisions") or []
    returned_keys = [clean_text(item.get("record_key")) for item in decisions]
    expected = set(conflicts)
    returned = set(returned_keys)
    if len(returned_keys) != len(returned) or returned != expected:
        raise ValueError(
            "cluster conflict-resolution coverage mismatch; "
            f"missing={sorted(expected - returned)}, unknown={sorted(returned - expected)}"
        )
    selected: dict[str, int] = {}
    for decision in decisions:
        record_key = clean_text(decision.get("record_key"))
        candidate_id = clean_text(decision.get("selected_candidate_id"))
        candidate_index = candidate_group_indices.get(record_key, {}).get(candidate_id)
        if candidate_index is None:
            raise ValueError(
                "cluster conflict-resolution selected an unknown candidate; "
                f"record_key={record_key}, candidate_id={candidate_id}"
            )
        selected[record_key] = candidate_index
    return selected


def _apply_conflict_resolution(
    partition: dict[str, Any],
    *,
    selected_group_indices: dict[str, int],
) -> dict[str, Any]:
    resolved = deepcopy(partition)
    groups: list[dict[str, Any]] = []
    for group_index, group in enumerate(resolved.get("groups") or []):
        group["record_keys"] = [
            record_key
            for record_key in group.get("record_keys") or []
            if record_key not in selected_group_indices
            or selected_group_indices[record_key] == group_index
        ]
        if group["record_keys"]:
            groups.append(group)
    resolved["groups"] = groups
    return resolved


def _normalize_same_group_duplicates(
    output: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Remove only repetitions that cannot change a record's group assignment."""
    normalized = deepcopy(output)
    removed: list[str] = []
    for group in normalized.get("groups") or []:
        seen: set[str] = set()
        record_keys: list[str] = []
        for value in group.get("record_keys") or []:
            record_key = clean_text(value)
            if record_key and record_key in seen:
                removed.append(record_key)
                continue
            record_keys.append(record_key)
            if record_key:
                seen.add(record_key)
        group["record_keys"] = record_keys
    return normalized, sorted(set(removed))


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
    assignments: dict[str, list[str]] = {}
    returned_keys: list[str] = []
    for index, group in enumerate(output.get("groups") or [], start=1):
        group_ref = clean_text(group.get("group_ref")) or f"group_{index}"
        for value in group.get("record_keys") or []:
            record_key = clean_text(value)
            returned_keys.append(record_key)
            if record_key:
                assignments.setdefault(record_key, []).append(group_ref)
    expected = set(expected_keys)
    returned = set(returned_keys)
    conflicting_assignments = {
        record_key: group_refs
        for record_key, group_refs in assignments.items()
        if len(group_refs) > 1
    }
    if (
        any(not key for key in returned_keys)
        or bool(conflicting_assignments)
        or returned != expected
    ):
        raise PartitionCoverageError(
            missing=sorted(expected - returned),
            unknown=sorted(returned - expected),
            conflicting_assignments=conflicting_assignments,
        )
