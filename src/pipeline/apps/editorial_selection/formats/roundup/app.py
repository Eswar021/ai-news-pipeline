from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import time
from typing import Any

from langchain_core.prompts import PromptTemplate

from .contract import (
    CandidateScreenDraft,
    EditorialSelectionRequest,
    EditorialSelectionResponse,
    RoundupSlateDraft,
    RoundupSlateReviewDraft,
)
from .config import SCREENING_PROMPT_MODULE, SLATE_REVIEW_PROMPT_MODULE
from .llm_client import make_llm
from .llm_logging import build_llm_call_log
from .prompt_loader import load_prompt_bundle
from .utils import build_story_context, clean_text, story_context_chars, text_token_count


IST = timezone(timedelta(hours=5, minutes=30))
TASK_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\n{user_preamble}\n\nSelection payload:\n{task_payload}"
)


def run(input_json: dict) -> dict:
    request = EditorialSelectionRequest.model_validate(input_json)
    run_id = request.run.run_id
    config = request.config.model_dump(mode="json")
    mapping = request.input.story_mapping
    upstream_run_id = clean_text(mapping.data.run_id)
    if upstream_run_id and upstream_run_id != run_id:
        raise ValueError(
            f"editorial_selection run_id mismatch: request={run_id}, story_mapping={upstream_run_id}"
        )
    stories = list(mapping.data.stories)
    if mapping.status != "ok" or not stories:
        return _failed_response(
            run_id=run_id,
            input_count=len(stories),
            llm_calls=[],
            reason="story_mapping is not ready or contains no stories",
        )
    prompt_bundle = load_prompt_bundle(config["prompt_version"])
    llm = make_llm(
        provider=config["provider"],
        model=config["model"],
        temperature=float(config["temperature"]),
        base_url=config.get("base_url"),
    )
    llm_calls: list[dict[str, Any]] = []
    try:
        candidate_pool, screened_out, screening = _screen_candidate_pool(
            stories=stories,
            config=config,
            llm=llm,
            llm_calls=llm_calls,
        )
    except Exception as exc:
        return _failed_response(
            run_id=run_id,
            input_count=len(stories),
            llm_calls=llm_calls,
            reason=f"editorial candidate screening unresolved: {clean_text(exc)}",
        )

    last_error = ""
    slate: dict[str, Any] | None = None
    slate_review_changed = False
    slate_review_reason = ""
    duplicate_story_groups: list[dict[str, Any]] = []
    slate_review_config = dict(config.get("slate_review") or {})
    slate_review_prompt_bundle = None
    if bool(slate_review_config.get("enabled")):
        slate_review_prompt_bundle = load_prompt_bundle(
            slate_review_config["prompt_version"],
            module=SLATE_REVIEW_PROMPT_MODULE,
        )
    for attempt in range(1, int(config["max_attempts"]) + 1):
        try:
            draft = _invoke_selector(
                stories=candidate_pool,
                config=config,
                prompt_bundle=prompt_bundle,
                llm=llm,
                llm_calls=llm_calls,
                attempt=attempt,
                original_story_count=len(stories),
            )
            _validate_slate(draft, candidate_pool, config)
            if slate_review_prompt_bundle is not None:
                reviewed_draft = _invoke_slate_reviewer(
                    stories=candidate_pool,
                    proposed=draft,
                    config=config,
                    review_config=slate_review_config,
                    prompt_bundle=slate_review_prompt_bundle,
                    llm=llm,
                    llm_calls=llm_calls,
                    attempt=attempt,
                )
                _validate_slate(reviewed_draft, candidate_pool, config)
                draft = reviewed_draft
                slate_review_changed = bool(reviewed_draft.review_changed)
                slate_review_reason = clean_text(reviewed_draft.review_reason)
                duplicate_story_groups = [
                    group.model_dump(mode="json")
                    for group in reviewed_draft.duplicate_story_groups
                ]
            slate = _materialize_slate(
                draft,
                stories,
                candidate_pool=candidate_pool,
                screened_out=screened_out,
                screening=screening,
            )
            _validate_materialized_coverage(slate, stories)
            break
        except Exception as exc:
            last_error = clean_text(exc)

    if slate is None:
        return _failed_response(
            run_id=run_id,
            input_count=len(stories),
            llm_calls=llm_calls,
            reason=f"editorial selector unresolved after bounded retries: {last_error}",
            evaluated_count=len(stories),
            screening=screening,
        )

    generated_at = datetime.now(IST).isoformat()
    response = EditorialSelectionResponse(
        status="ok",
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": "roundup",
            "editorial_slate": slate,
        },
        summary={
            "input_story_count": len(stories),
            "evaluated_story_count": len(stories),
            "selected_story_count": len(slate["selected_stories"]),
            "reserve_story_count": len(slate["reserve"]),
            "rejected_story_count": len(slate["rejected"]),
            "llm_call_count": len(llm_calls),
            "screening_call_count": sum(
                1
                for call in llm_calls
                if call.get("module_name") == SCREENING_PROMPT_MODULE
            ),
            "slate_review_enabled": bool(slate_review_config.get("enabled")),
            "slate_review_call_count": sum(
                1
                for call in llm_calls
                if call.get("module_name") == SLATE_REVIEW_PROMPT_MODULE
            ),
            "slate_review_changed": slate_review_changed,
            "slate_review_reason": slate_review_reason,
            "duplicate_story_group_count": len(duplicate_story_groups),
            "duplicate_story_groups": duplicate_story_groups,
            "selection_strategy": screening["strategy"],
            "screening_round_count": len(screening["rounds"]),
            "final_candidate_story_count": len(candidate_pool),
            "max_candidate_stories_per_call": int(config["max_candidate_stories"]),
            "max_call_context_chars": int(config["max_call_context_chars"]),
            "max_call_context_tokens": int(config["max_call_context_tokens"]),
            "screening_shortlist_per_batch": int(config["screening_shortlist_per_batch"]),
            "failure_reason": "",
            "episode_shape": slate["episode_shape"],
            "selected_story_ids": slate["selected_story_ids"],
            "reserve_story_ids": [item["story_id"] for item in slate["reserve"]],
        },
        handoff={"ready_for_video_packaging": True, "selected_format": "roundup"},
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _invoke_slate_reviewer(
    *,
    stories: list[dict],
    proposed: RoundupSlateDraft,
    config: dict[str, Any],
    review_config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
    attempt: int,
) -> RoundupSlateReviewDraft:
    story_contexts, selection_ref_to_story_id = _selection_contexts_with_refs(
        stories,
        config,
    )
    serialized_context_chars, serialized_context_tokens = _validate_call_context(
        story_contexts,
        config,
    )
    proposed_transport = _slate_with_selection_refs(
        proposed,
        selection_ref_to_story_id,
    )
    payload = {
        "task": "Audit and finalize the proposed roundup slate.",
        "channel": config["channel"],
        "constraints": {
            "min_stories": config["min_stories"],
            "max_stories": config["max_stories"],
            "exactly_one_lead": True,
            "all_candidate_ids_must_be_accounted_for": True,
            "do_not_select_duplicate_editorial_stories": True,
        },
        "selection_identity": {
            "story_id_values_are_opaque_selection_refs": True,
            "copy_story_id_values_exactly": True,
        },
        "proposed_slate": proposed_transport,
        "candidate_stories": story_contexts,
        "required_story_ids": [item["story_id"] for item in story_contexts],
    }
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": json.dumps(payload, ensure_ascii=False, indent=2),
    }
    rendered_prompt = TASK_PROMPT.format(**prompt_inputs)
    chain = TASK_PROMPT | llm.with_structured_output(
        RoundupSlateReviewDraft,
        include_raw=True,
    )
    raw = None
    parsed_dict = None
    last_error = ""
    for review_attempt in range(1, int(review_config["max_attempts"]) + 1):
        started = time.time()
        try:
            result = chain.invoke(prompt_inputs)
            raw = result.get("raw") if isinstance(result, dict) else None
            parsed = result.get("parsed") if isinstance(result, dict) else result
            parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
            if parsing_error is not None or parsed is None:
                raise ValueError(f"structured output parsing failed: {parsing_error}")
            transport_output = (
                parsed
                if isinstance(parsed, RoundupSlateReviewDraft)
                else RoundupSlateReviewDraft.model_validate(parsed)
            )
            parsed_dict = transport_output.model_dump(mode="json")
            output = _restore_slate_review_story_ids(
                transport_output,
                selection_ref_to_story_id,
            )
            llm_calls.append(
                build_llm_call_log(
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered_prompt,
                    raw_response=raw,
                    parsed_output=parsed_dict,
                    metadata={
                        **_selection_context_metadata(
                            story_contexts,
                            attempt=attempt,
                            serialized_context_chars=serialized_context_chars,
                            serialized_context_tokens=serialized_context_tokens,
                            selection_ref_to_story_id=selection_ref_to_story_id,
                        ),
                        "review_attempt": review_attempt,
                    },
                    duration_seconds=time.time() - started,
                    module_name=SLATE_REVIEW_PROMPT_MODULE,
                )
            )
            return output
        except Exception as exc:
            last_error = clean_text(exc)
            llm_calls.append(
                build_llm_call_log(
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered_prompt,
                    raw_response=raw,
                    parsed_output=parsed_dict,
                    metadata={
                        **_selection_context_metadata(
                            story_contexts,
                            attempt=attempt,
                            serialized_context_chars=serialized_context_chars,
                            serialized_context_tokens=serialized_context_tokens,
                            selection_ref_to_story_id=selection_ref_to_story_id,
                        ),
                        "review_attempt": review_attempt,
                    },
                    duration_seconds=time.time() - started,
                    parse_error=last_error,
                    module_name=SLATE_REVIEW_PROMPT_MODULE,
                )
            )
    raise RuntimeError(f"roundup slate review unresolved after bounded retries: {last_error}")


def _invoke_selector(
    *,
    stories: list[dict],
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
    attempt: int,
    original_story_count: int,
) -> RoundupSlateDraft:
    story_contexts, selection_ref_to_story_id = _selection_contexts_with_refs(
        stories,
        config,
    )
    serialized_context_chars, serialized_context_tokens = _validate_call_context(
        story_contexts,
        config,
    )
    payload = {
        "task": "Select and order an engaging roundup slate.",
        "channel": config["channel"],
        "constraints": {
            "min_stories": config["min_stories"],
            "max_stories": config["max_stories"],
            "exactly_one_lead": True,
            "all_candidate_ids_must_be_accounted_for": True,
        },
        "candidate_pool": {
            "original_story_count": original_story_count,
            "final_candidate_story_count": len(story_contexts),
            "was_semantically_screened": original_story_count > len(story_contexts),
        },
        "selection_identity": {
            "story_id_values_are_opaque_selection_refs": True,
            "copy_story_id_values_exactly": True,
            "never_reconstruct_story_id_from_titles_dates_or_source_content": True,
        },
        "candidate_stories": story_contexts,
        "required_story_ids": [item["story_id"] for item in story_contexts],
    }
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": json.dumps(payload, ensure_ascii=False, indent=2),
    }
    rendered_prompt = TASK_PROMPT.format(**prompt_inputs)
    chain = TASK_PROMPT | llm.with_structured_output(RoundupSlateDraft, include_raw=True)
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
        transport_output = (
            parsed
            if isinstance(parsed, RoundupSlateDraft)
            else RoundupSlateDraft.model_validate(parsed)
        )
        parsed_dict = transport_output.model_dump(mode="json")
        output = _restore_slate_story_ids(
            transport_output,
            selection_ref_to_story_id,
        )
    except Exception as exc:
        llm_calls.append(
            build_llm_call_log(
                provider=config["provider"],
                model=config["model"],
                rendered_prompt=rendered_prompt,
                raw_response=raw,
                parsed_output=parsed_dict,
                metadata=_selection_context_metadata(
                    story_contexts,
                    attempt=attempt,
                    serialized_context_chars=serialized_context_chars,
                    serialized_context_tokens=serialized_context_tokens,
                    selection_ref_to_story_id=selection_ref_to_story_id,
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
            metadata=_selection_context_metadata(
                story_contexts,
                attempt=attempt,
                serialized_context_chars=serialized_context_chars,
                serialized_context_tokens=serialized_context_tokens,
                selection_ref_to_story_id=selection_ref_to_story_id,
            ),
            duration_seconds=time.time() - started,
        )
    )
    return output


def _screen_candidate_pool(
    *,
    stories: list[dict],
    config: dict[str, Any],
    llm,
    llm_calls: list[dict[str, Any]],
) -> tuple[list[dict], list[dict[str, Any]], dict[str, Any]]:
    per_call_limit = int(config["max_candidate_stories"])
    if _candidate_pool_fits_one_call(stories, config):
        return list(stories), [], {
            "strategy": "direct_final_selection",
            "input_story_count": len(stories),
            "final_candidate_story_count": len(stories),
            "rounds": [],
        }

    prompt_bundle = load_prompt_bundle(
        config["prompt_version"],
        module=SCREENING_PROMPT_MODULE,
    )
    active = list(stories)
    screened_out: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    max_rounds = int(config["max_screening_rounds"])
    shortlist_per_batch = int(config["screening_shortlist_per_batch"])

    for round_number in range(1, max_rounds + 1):
        if _candidate_pool_fits_one_call(active, config):
            break
        batches = _balanced_context_batches(active, config)
        quotas = _screening_quotas(
            [len(batch) for batch in batches],
            shortlist_per_batch=shortlist_per_batch,
            target_total=max(
                len(batches),
                min(
                    per_call_limit,
                    shortlist_per_batch * len(batches),
                    math.ceil(len(active) / 2),
                ),
            ),
        )
        next_active: list[dict] = []
        round_batch_summaries: list[dict[str, Any]] = []
        for batch_number, (batch, shortlist_quota) in enumerate(
            zip(batches, quotas, strict=True),
            start=1,
        ):
            draft: CandidateScreenDraft | None = None
            last_error = ""
            for attempt in range(1, int(config["max_attempts"]) + 1):
                try:
                    candidate = _invoke_candidate_screen(
                        stories=batch,
                        shortlist_quota=shortlist_quota,
                        config=config,
                        prompt_bundle=prompt_bundle,
                        llm=llm,
                        llm_calls=llm_calls,
                        round_number=round_number,
                        batch_number=batch_number,
                        attempt=attempt,
                    )
                    _validate_candidate_screen(
                        candidate,
                        batch,
                        shortlist_quota=shortlist_quota,
                    )
                    draft = candidate
                    break
                except Exception as exc:
                    last_error = clean_text(exc)
            if draft is None:
                raise ValueError(
                    f"round {round_number} batch {batch_number} failed after bounded retries: {last_error}"
                )

            by_id = {clean_text(story.get("story_id")): story for story in batch}
            decision_dicts = [item.model_dump(mode="json") for item in draft.decisions]
            shortlisted_ids = [clean_text(item["story_id"]) for item in decision_dicts]
            next_active.extend(by_id[story_id] for story_id in shortlisted_ids)
            shortlisted_id_set = set(shortlisted_ids)
            for story in batch:
                story_id = clean_text(story.get("story_id"))
                if story_id in shortlisted_id_set:
                    continue
                screened_out.append(
                    {
                        "story_id": story_id,
                        "action": "reserve",
                        "reason": (
                            "Not advanced from this semantic screening batch; retained as a "
                            "recoverable reserve."
                        ),
                        "selection_stage": "candidate_screen",
                        "decision_source": "llm_shortlist_complement",
                        "screening_round": round_number,
                        "screening_batch": batch_number,
                    }
                )
            round_batch_summaries.append(
                {
                    "batch_number": batch_number,
                    "input_story_count": len(batch),
                    "shortlisted_story_count": len(shortlisted_ids),
                    "reserve_story_count": len(batch) - len(shortlisted_ids),
                    "rejected_story_count": 0,
                    "shortlisted_story_ids": shortlisted_ids,
                }
            )

        if len(next_active) >= len(active):
            raise ValueError(
                f"screening round {round_number} did not reduce the candidate pool"
            )
        rounds.append(
            {
                "round_number": round_number,
                "input_story_count": len(active),
                "output_story_count": len(next_active),
                "batch_count": len(batches),
                "batches": round_batch_summaries,
            }
        )
        active = next_active

    if not _candidate_pool_fits_one_call(active, config):
        raise ValueError(
            f"candidate pool remains too large for one complete-context call after the configured "
            f"{max_rounds} screening rounds; story_count={len(active)}, "
            f"count_limit={per_call_limit}, context_limit={config['max_call_context_chars']}"
            f", token_limit={config['max_call_context_tokens']}"
        )
    return active, screened_out, {
        "strategy": "iterative_llm_screening_then_final_selection",
        "input_story_count": len(stories),
        "final_candidate_story_count": len(active),
        "rounds": rounds,
    }


def _invoke_candidate_screen(
    *,
    stories: list[dict],
    shortlist_quota: int,
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
    round_number: int,
    batch_number: int,
    attempt: int,
) -> CandidateScreenDraft:
    story_contexts, selection_ref_to_story_id = _selection_contexts_with_refs(
        stories,
        config,
    )
    serialized_context_chars, serialized_context_tokens = _validate_call_context(
        story_contexts,
        config,
    )
    payload = {
        "task": "Semantically screen one balanced batch for a later roundup selector.",
        "channel": config["channel"],
        "constraints": {
            "shortlist_exactly": shortlist_quota,
            "return_shortlist_decisions_only": True,
            "shortlist_must_be_ordered_by_editorial_preference": True,
            "shortlist_is_not_final_episode_selection": True,
        },
        "screening_context": {
            "round_number": round_number,
            "batch_number": batch_number,
            "candidate_story_count": len(story_contexts),
        },
        "selection_identity": {
            "story_id_values_are_opaque_selection_refs": True,
            "copy_story_id_values_exactly": True,
            "never_reconstruct_story_id_from_titles_dates_or_source_content": True,
        },
        "candidate_stories": story_contexts,
        "required_story_ids": [item["story_id"] for item in story_contexts],
    }
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": json.dumps(payload, ensure_ascii=False, indent=2),
    }
    rendered_prompt = TASK_PROMPT.format(**prompt_inputs)
    chain = TASK_PROMPT | llm.with_structured_output(CandidateScreenDraft, include_raw=True)
    started = time.time()
    raw = None
    parsed_dict = None
    metadata = {
        "attempt": attempt,
        "screening_round": round_number,
        "screening_batch": batch_number,
        "candidate_story_count": len(stories),
        "shortlist_quota": shortlist_quota,
        "source_context_mode": "complete_normalized_story_records",
        "stories_truncated": False,
        "serialized_context_chars": serialized_context_chars,
        "serialized_context_tokens": serialized_context_tokens,
        "selection_identity_transport": "opaque_per_call_reference",
        "selection_refs": list(selection_ref_to_story_id),
        "story_ids": list(selection_ref_to_story_id.values()),
        "story_context_chars": {
            selection_ref_to_story_id[item["story_id"]]: story_context_chars(item)
            for item in story_contexts
        },
    }
    try:
        result = chain.invoke(prompt_inputs)
        raw = result.get("raw") if isinstance(result, dict) else None
        parsed = result.get("parsed") if isinstance(result, dict) else result
        parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
        if parsing_error is not None or parsed is None:
            raise ValueError(f"structured output parsing failed: {parsing_error}")
        transport_output = (
            parsed
            if isinstance(parsed, CandidateScreenDraft)
            else CandidateScreenDraft.model_validate(parsed)
        )
        parsed_dict = transport_output.model_dump(mode="json")
        output = _restore_candidate_screen_story_ids(
            transport_output,
            selection_ref_to_story_id,
        )
    except Exception as exc:
        llm_calls.append(
            build_llm_call_log(
                provider=config["provider"],
                model=config["model"],
                rendered_prompt=rendered_prompt,
                raw_response=raw,
                parsed_output=parsed_dict,
                metadata=metadata,
                duration_seconds=time.time() - started,
                parse_error=str(exc),
                module_name=SCREENING_PROMPT_MODULE,
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
            metadata=metadata,
            duration_seconds=time.time() - started,
            module_name=SCREENING_PROMPT_MODULE,
        )
    )
    return output


def _balanced_context_batches(
    stories: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[list[dict[str, Any]]]:
    contexts, _selection_ref_to_story_id = _selection_contexts_with_refs(
        stories,
        config,
    )
    count_limit = int(config["max_candidate_stories"])
    pairs = list(zip(stories, contexts, strict=True))
    minimum_batch_count = max(1, math.ceil(len(stories) / count_limit))
    for batch_count in range(minimum_batch_count, len(stories) + 1):
        batches: list[list[tuple[dict[str, Any], dict[str, Any]]]] = [
            [] for _ in range(batch_count)
        ]
        for index, pair in enumerate(pairs):
            batches[index % batch_count].append(pair)
        if all(
            len(batch) <= count_limit
            and _contexts_fit_call_budget([entry[1] for entry in batch], config)
            for batch in batches
        ):
            return [
                [story for story, _context in batch]
                for batch in batches
                if batch
            ]
    raise ValueError(
        "Could not build complete-context editorial screening batches within configured limits"
    )


def _candidate_pool_fits_one_call(
    stories: list[dict[str, Any]],
    config: dict[str, Any],
) -> bool:
    if len(stories) > int(config["max_candidate_stories"]):
        return False
    contexts, _selection_ref_to_story_id = _selection_contexts_with_refs(
        stories,
        config,
    )
    return _contexts_fit_call_budget(contexts, config)


def _complete_story_contexts(
    stories: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    contexts = [build_story_context(story) for story in stories]
    oversized = []
    for context in contexts:
        serialized_context = _serialize_story_contexts([context])
        char_count = len(serialized_context)
        token_count = text_token_count(
            serialized_context,
            model=config["model"],
            fallback_encoding=config["tokenizer_encoding"],
        )
        if (
            char_count > int(config["max_story_context_chars"])
            or token_count > int(config["max_story_context_tokens"])
        ):
            oversized.append(
                {
                    "story_id": context["story_id"],
                    "chars": char_count,
                    "tokens": token_count,
                }
            )
    if oversized:
        raise ValueError(
            "Complete editorial-selection story context exceeds "
            "the configured per-story character or token budget; no records were removed "
            "or truncated. "
            f"Oversized stories: {oversized[:8]}"
        )
    return contexts


def _selection_contexts_with_refs(
    stories: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    contexts = _complete_story_contexts(stories, config)
    selection_ref_to_story_id: dict[str, str] = {}
    seen_story_ids: set[str] = set()
    for index, context in enumerate(contexts, start=1):
        story_id = clean_text(context.get("story_id"))
        if not story_id:
            raise ValueError("editorial selection received a story without story_id")
        if story_id in seen_story_ids:
            raise ValueError(f"editorial selection received duplicate story_id: {story_id}")
        seen_story_ids.add(story_id)
        selection_ref = f"candidate_{index:03d}"
        selection_ref_to_story_id[selection_ref] = story_id
        context["story_id"] = selection_ref
        for field_name, field_value in list(context.items()):
            if field_name == "story_id":
                continue
            context[field_name] = _without_nested_story_ids(field_value)
        context_contract = context.get("context_contract")
        if isinstance(context_contract, dict):
            context_contract.pop("serialized_context_chars", None)
            context_contract["serialized_context_chars"] = story_context_chars(context)
    return contexts, selection_ref_to_story_id


def _without_nested_story_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_nested_story_ids(item)
            for key, item in value.items()
            if key != "story_id"
        }
    if isinstance(value, list):
        return [_without_nested_story_ids(item) for item in value]
    return value


def _restore_candidate_screen_story_ids(
    draft: CandidateScreenDraft,
    selection_ref_to_story_id: dict[str, str],
) -> CandidateScreenDraft:
    payload = draft.model_dump(mode="json")
    for decision in payload["decisions"]:
        selection_ref = clean_text(decision.get("story_id"))
        if selection_ref not in selection_ref_to_story_id:
            raise ValueError(
                "candidate screening returned unknown selection reference: "
                f"{selection_ref}"
            )
        decision["story_id"] = selection_ref_to_story_id[selection_ref]
    return CandidateScreenDraft.model_validate(payload)


def _restore_slate_story_ids(
    draft: RoundupSlateDraft,
    selection_ref_to_story_id: dict[str, str],
) -> RoundupSlateDraft:
    payload = draft.model_dump(mode="json")
    for collection_name in ("selected", "non_selected"):
        for decision in payload[collection_name]:
            selection_ref = clean_text(decision.get("story_id"))
            if selection_ref not in selection_ref_to_story_id:
                raise ValueError(
                    "editorial selection returned unknown selection reference: "
                    f"{selection_ref}"
                )
            decision["story_id"] = selection_ref_to_story_id[selection_ref]
    return RoundupSlateDraft.model_validate(payload)


def _slate_with_selection_refs(
    draft: RoundupSlateDraft,
    selection_ref_to_story_id: dict[str, str],
) -> dict[str, Any]:
    story_id_to_selection_ref = {
        story_id: selection_ref
        for selection_ref, story_id in selection_ref_to_story_id.items()
    }
    payload = draft.model_dump(mode="json")
    for collection_name in ("selected", "non_selected"):
        for decision in payload[collection_name]:
            story_id = clean_text(decision.get("story_id"))
            selection_ref = story_id_to_selection_ref.get(story_id)
            if selection_ref is None:
                raise ValueError(
                    "proposed editorial slate references a story outside the review pool: "
                    f"{story_id}"
                )
            decision["story_id"] = selection_ref
    return payload


def _restore_slate_review_story_ids(
    draft: RoundupSlateReviewDraft,
    selection_ref_to_story_id: dict[str, str],
) -> RoundupSlateReviewDraft:
    payload = draft.model_dump(mode="json")
    for collection_name in ("selected", "non_selected"):
        for decision in payload[collection_name]:
            selection_ref = clean_text(decision.get("story_id"))
            if selection_ref not in selection_ref_to_story_id:
                raise ValueError(
                    "roundup slate review returned unknown selection reference: "
                    f"{selection_ref}"
                )
            decision["story_id"] = selection_ref_to_story_id[selection_ref]
    for group in payload["duplicate_story_groups"]:
        restored_ids = []
        for selection_ref in group["story_ids"]:
            selection_ref = clean_text(selection_ref)
            if selection_ref not in selection_ref_to_story_id:
                raise ValueError(
                    "roundup slate review duplicate group returned unknown selection "
                    f"reference: {selection_ref}"
                )
            restored_ids.append(selection_ref_to_story_id[selection_ref])
        group["story_ids"] = restored_ids
    return RoundupSlateReviewDraft.model_validate(payload)


def _validate_call_context(
    contexts: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[int, int]:
    serialized_context = _serialize_story_contexts(contexts)
    serialized_chars = len(serialized_context)
    serialized_tokens = text_token_count(
        serialized_context,
        model=config["model"],
        fallback_encoding=config["tokenizer_encoding"],
    )
    configured_limit = int(config["max_call_context_chars"])
    configured_token_limit = int(config["max_call_context_tokens"])
    if len(contexts) > int(config["max_candidate_stories"]):
        raise ValueError(
            "Editorial-selection call exceeds config.max_candidate_stories; use semantic screening."
        )
    if serialized_chars > configured_limit:
        raise ValueError(
            "Complete editorial-selection call context exceeds config.max_call_context_chars; "
            "no records were removed or truncated. Use another semantic screening round. "
            f"serialized_chars={serialized_chars}, configured_limit={configured_limit}"
        )
    if serialized_tokens > configured_token_limit:
        raise ValueError(
            "Complete editorial-selection call context exceeds "
            "config.max_call_context_tokens; no records were removed or truncated. "
            "Use another semantic screening round. "
            f"serialized_tokens={serialized_tokens}, "
            f"configured_limit={configured_token_limit}"
        )
    return serialized_chars, serialized_tokens


def _contexts_fit_call_budget(
    contexts: list[dict[str, Any]],
    config: dict[str, Any],
) -> bool:
    serialized_context = _serialize_story_contexts(contexts)
    if len(serialized_context) > int(config["max_call_context_chars"]):
        return False
    return text_token_count(
        serialized_context,
        model=config["model"],
        fallback_encoding=config["tokenizer_encoding"],
    ) <= int(config["max_call_context_tokens"])


def _serialize_story_contexts(contexts: list[dict[str, Any]]) -> str:
    return json.dumps(contexts, ensure_ascii=False, separators=(",", ":"))


def _selection_context_metadata(
    contexts: list[dict[str, Any]],
    *,
    attempt: int,
    serialized_context_chars: int,
    serialized_context_tokens: int,
    selection_ref_to_story_id: dict[str, str],
) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "candidate_story_count": len(contexts),
        "selection_identity_transport": "opaque_per_call_reference",
        "selection_refs": list(selection_ref_to_story_id),
        "story_ids": list(selection_ref_to_story_id.values()),
        "story_context_chars": {
            selection_ref_to_story_id[item["story_id"]]: story_context_chars(item)
            for item in contexts
        },
        "serialized_context_chars": serialized_context_chars,
        "serialized_context_tokens": serialized_context_tokens,
        "source_context_mode": "complete_normalized_story_records",
        "stories_truncated": False,
    }


def _screening_quotas(
    batch_sizes: list[int],
    *,
    shortlist_per_batch: int,
    target_total: int,
) -> list[int]:
    target_total = min(target_total, sum(batch_sizes) - 1)
    quotas = [0 for _ in batch_sizes]
    assigned = 0
    while assigned < target_total:
        made_progress = False
        for index, batch_size in enumerate(batch_sizes):
            if quotas[index] >= batch_size or assigned >= target_total:
                continue
            quotas[index] += 1
            assigned += 1
            made_progress = True
        if not made_progress:
            break
    if assigned != target_total or any(quota < 1 for quota in quotas):
        raise ValueError("could not allocate a non-empty semantic shortlist to every batch")
    return quotas


def _validate_candidate_screen(
    draft: CandidateScreenDraft,
    stories: list[dict],
    *,
    shortlist_quota: int,
) -> None:
    known_ids = {clean_text(story.get("story_id")) for story in stories}
    returned_ids = [clean_text(item.story_id) for item in draft.decisions]
    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError("candidate screening returned duplicate story IDs")
    unknown_ids = set(returned_ids) - known_ids
    if unknown_ids:
        raise ValueError(
            f"candidate screening returned unknown story IDs: {sorted(unknown_ids)}"
        )
    if len(returned_ids) != shortlist_quota:
        raise ValueError(
            f"candidate screening must shortlist exactly {shortlist_quota} stories; got {len(returned_ids)}"
        )


def _validate_slate(draft: RoundupSlateDraft, stories: list[dict], config: dict[str, Any]) -> None:
    known_ids = {clean_text(story.get("story_id")) for story in stories}
    selected_ids = [clean_text(item.story_id) for item in draft.selected]
    non_selected_ids = [clean_text(item.story_id) for item in draft.non_selected]
    returned_ids = selected_ids + non_selected_ids
    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError("editorial selection returned duplicate story IDs")
    unknown_ids = set(returned_ids) - known_ids
    if unknown_ids:
        raise ValueError(
            f"editorial selection returned unknown story IDs: {sorted(unknown_ids)}"
        )
    if not int(config["min_stories"]) <= len(selected_ids) <= int(config["max_stories"]):
        raise ValueError(
            f"editorial selection must choose {config['min_stories']}..{config['max_stories']} stories"
        )
    lead_indices = [index for index, item in enumerate(draft.selected) if item.role == "lead"]
    if lead_indices != [0]:
        raise ValueError("editorial selection must place exactly one lead first")


def _materialize_slate(
    draft: RoundupSlateDraft,
    stories: list[dict],
    *,
    candidate_pool: list[dict],
    screened_out: list[dict[str, Any]],
    screening: dict[str, Any],
) -> dict[str, Any]:
    by_id = {clean_text(story.get("story_id")): story for story in stories}
    selected_stories = []
    for order, decision in enumerate(draft.selected, start=1):
        decision_dict = decision.model_dump(mode="json")
        story_id = clean_text(decision.story_id)
        selected_stories.append(
            {
                **by_id[story_id],
                "editorial_selection": {**decision_dict, "selection_order": order},
            }
        )
    non_selected = [
        {**item.model_dump(mode="json"), "selection_stage": "final_selector"}
        for item in draft.non_selected
    ]
    final_returned_ids = {
        *[clean_text(item.story_id) for item in draft.selected],
        *[clean_text(item.story_id) for item in draft.non_selected],
    }
    non_selected.extend(
        {
            "story_id": story_id,
            "action": "reserve",
            "reason": (
                "Not selected in the final semantic slate; retained as a recoverable reserve."
            ),
            "selection_stage": "final_selector",
            "decision_source": "llm_selected_list_complement",
        }
        for story_id in [clean_text(story.get("story_id")) for story in candidate_pool]
        if story_id not in final_returned_ids
    )
    all_non_selected = [*non_selected, *screened_out]
    reserve_decisions = [
        item for item in all_non_selected if item["action"] == "reserve"
    ]
    reserve_stories = [
        {
            **by_id[clean_text(item["story_id"])],
            "editorial_selection": {
                **item,
                "reserve_order": order,
            },
        }
        for order, item in enumerate(reserve_decisions, start=1)
    ]
    return {
        "package_type": "roundup_editorial_slate",
        "episode_shape": draft.episode_shape,
        "episode_thesis": clean_text(draft.episode_thesis),
        "ordering_rationale": clean_text(draft.ordering_rationale),
        "human_review_warning": clean_text(draft.human_review_warning),
        "selected_story_ids": [clean_text(item.story_id) for item in draft.selected],
        "selected_stories": selected_stories,
        "reserve": reserve_decisions,
        "reserve_stories": reserve_stories,
        "rejected": [
            item for item in all_non_selected if item["action"] == "reject"
        ],
        "candidate_screening": screening,
        "decision_ledger": [
            *[
                {**item.model_dump(mode="json"), "action": "select"}
                for item in draft.selected
            ],
            *all_non_selected,
        ],
    }


def _validate_materialized_coverage(slate: dict[str, Any], stories: list[dict]) -> None:
    known_ids = {clean_text(story.get("story_id")) for story in stories}
    ledger_ids = [clean_text(item.get("story_id")) for item in slate["decision_ledger"]]
    if len(ledger_ids) != len(set(ledger_ids)) or set(ledger_ids) != known_ids:
        raise ValueError(
            "materialized editorial ledger must account for every input story exactly once"
        )


def _failed_response(
    *,
    run_id: str,
    input_count: int,
    llm_calls: list[dict],
    reason: str,
    evaluated_count: int = 0,
    screening: dict[str, Any] | None = None,
) -> dict:
    response = EditorialSelectionResponse(
        status="failed",
        data={
            "run_id": run_id,
            "generated_at": datetime.now(IST).isoformat(),
            "selected_format": "roundup",
            "editorial_slate": {
                "package_type": "roundup_editorial_slate",
                "selected_story_ids": [],
                "selected_stories": [],
                "reserve": [],
                "reserve_stories": [],
                "rejected": [],
                "decision_ledger": [],
            },
        },
        summary={
            "input_story_count": input_count,
            "evaluated_story_count": evaluated_count,
            "selected_story_count": 0,
            "reserve_story_count": 0,
            "rejected_story_count": 0,
            "llm_call_count": len(llm_calls),
            "screening_call_count": sum(
                1
                for call in llm_calls
                if call.get("module_name") == SCREENING_PROMPT_MODULE
            ),
            "selection_strategy": (screening or {}).get("strategy", "not_completed"),
            "screening_round_count": len((screening or {}).get("rounds", [])),
            "final_candidate_story_count": int(
                (screening or {}).get("final_candidate_story_count", 0)
            ),
            "failure_reason": reason,
        },
        handoff={"ready_for_video_packaging": False, "selected_format": "roundup"},
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")
