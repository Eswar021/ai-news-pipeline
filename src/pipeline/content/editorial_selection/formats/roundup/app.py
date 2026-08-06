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
    RoundupDuplicateAudit,
    RoundupSlateDraft,
    RoundupSlateReviewDraft,
)
from .config import (
    DEFAULT_PREFERRED_FINALIST_STORY_COUNT,
    DUPLICATE_AUDIT_PROMPT_MODULE,
    SCREENING_PROMPT_MODULE,
    SLATE_REVIEW_PROMPT_MODULE,
)
from src.pipeline.llm import make_llm
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
    slate_diversity_assessment = ""
    slate_diversity_reason = ""
    duplicate_story_groups: list[dict[str, Any]] = []
    focused_duplicate_repaired = False
    focused_duplicate_repair_notes: list[str] = []
    focused_duplicate_audit: RoundupDuplicateAudit | None = None
    slate_review_config = dict(config.get("slate_review") or {})
    slate_review_prompt_bundle = None
    duplicate_audit_prompt_bundle = None
    slate_review_llm = llm
    review_pool = list(candidate_pool)
    review_recovery = {
        "requested_count": 0,
        "available_story_count": len(screened_out),
        "included_story_ids": [],
        "omitted_story_ids": [],
    }
    if bool(slate_review_config.get("enabled")):
        slate_review_prompt_bundle = load_prompt_bundle(
            slate_review_config["prompt_version"],
            module=SLATE_REVIEW_PROMPT_MODULE,
        )
        review_provider = slate_review_config.get("provider") or config["provider"]
        review_model = slate_review_config.get("model") or config["model"]
        review_temperature = slate_review_config.get("temperature")
        if review_temperature is None:
            review_temperature = config["temperature"]
        slate_review_config["effective_provider"] = review_provider
        slate_review_config["effective_model"] = review_model
        slate_review_config["effective_temperature"] = float(review_temperature)
        slate_review_llm = make_llm(
            provider=review_provider,
            model=review_model,
            temperature=float(review_temperature),
            base_url=slate_review_config.get("base_url") or config.get("base_url"),
        )
        if bool(slate_review_config.get("duplicate_audit_enabled")):
            duplicate_audit_prompt_bundle = load_prompt_bundle(
                slate_review_config["duplicate_audit_prompt_version"],
                module=DUPLICATE_AUDIT_PROMPT_MODULE,
            )
        review_pool, review_recovery = _build_slate_review_pool(
            candidate_pool=candidate_pool,
            screened_out=screened_out,
            stories=stories,
            config=config,
            review_config=slate_review_config,
        )
    screening["slate_review_recovery"] = review_recovery
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
            focused_duplicate_audit = None
            if duplicate_audit_prompt_bundle is not None:
                story_by_id = {
                    clean_text(story.get("story_id")): story
                    for story in candidate_pool
                }
                selected_story_contexts = [
                    story_by_id[decision.story_id]
                    for decision in draft.selected
                ]
                focused_duplicate_audit = _invoke_duplicate_auditor(
                    stories=selected_story_contexts,
                    config=config,
                    review_config=slate_review_config,
                    prompt_bundle=duplicate_audit_prompt_bundle,
                    llm=slate_review_llm,
                    llm_calls=llm_calls,
                    attempt=attempt,
                )
            materialization_pool = candidate_pool
            if slate_review_prompt_bundle is not None:
                proposed_for_review = _complete_proposed_slate_for_review(
                    draft,
                    review_pool=review_pool,
                    recovery_story_ids=set(review_recovery["included_story_ids"]),
                )
                reviewed_draft = _invoke_slate_reviewer(
                    stories=review_pool,
                    proposed=proposed_for_review,
                    config=config,
                    review_config=slate_review_config,
                    prompt_bundle=slate_review_prompt_bundle,
                    llm=slate_review_llm,
                    llm_calls=llm_calls,
                    attempt=attempt,
                    primary_candidate_count=len(candidate_pool),
                    recovery_story_ids=set(review_recovery["included_story_ids"]),
                    focused_duplicate_audit=focused_duplicate_audit,
                )
                _validate_slate(reviewed_draft, review_pool, config)
                (
                    reviewed_draft,
                    repaired_duplicate_audit,
                    duplicate_repair_notes,
                ) = _repair_slate_duplicate_audit(
                    reviewed_draft,
                    focused_duplicate_audit,
                    config,
                )
                if repaired_duplicate_audit:
                    _validate_slate(reviewed_draft, review_pool, config)
                _validate_slate_resolves_duplicate_audit(
                    reviewed_draft,
                    focused_duplicate_audit,
                )
                focused_duplicate_repaired = repaired_duplicate_audit
                focused_duplicate_repair_notes = list(duplicate_repair_notes)
                draft = reviewed_draft
                materialization_pool = review_pool
                slate_review_changed = bool(reviewed_draft.review_changed)
                slate_review_reason = clean_text(reviewed_draft.review_reason)
                slate_diversity_assessment = reviewed_draft.diversity_assessment
                slate_diversity_reason = clean_text(reviewed_draft.diversity_reason)
                duplicate_story_groups = [
                    group.model_dump(mode="json")
                    for group in reviewed_draft.duplicate_story_groups
                ]
            slate = _materialize_slate(
                draft,
                stories,
                candidate_pool=materialization_pool,
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
            "focused_duplicate_audit_enabled": bool(
                slate_review_config.get("duplicate_audit_enabled")
            ),
            "focused_duplicate_audit_call_count": sum(
                1
                for call in llm_calls
                if call.get("module_name") == DUPLICATE_AUDIT_PROMPT_MODULE
            ),
            "focused_duplicate_group_count": len(
                focused_duplicate_audit.duplicate_story_groups
                if focused_duplicate_audit is not None
                else []
            ),
            "focused_duplicate_repaired": focused_duplicate_repaired,
            "focused_duplicate_repair_notes": focused_duplicate_repair_notes,
            "slate_review_provider": slate_review_config.get("effective_provider", ""),
            "slate_review_model": slate_review_config.get("effective_model", ""),
            "slate_review_changed": slate_review_changed,
            "slate_review_reason": slate_review_reason,
            "slate_diversity_assessment": slate_diversity_assessment,
            "slate_diversity_reason": slate_diversity_reason,
            "duplicate_story_group_count": len(duplicate_story_groups),
            "duplicate_story_groups": duplicate_story_groups,
            "selection_strategy": screening["strategy"],
            "screening_round_count": len(screening["rounds"]),
            "final_candidate_story_count": len(candidate_pool),
            "target_finalist_story_count": int(screening["target_finalist_story_count"]),
            "slate_review_candidate_story_count": len(review_pool),
            "slate_review_recovery_candidate_count": len(
                review_recovery["included_story_ids"]
            ),
            "slate_review_recovery_story_ids": review_recovery["included_story_ids"],
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


def _invoke_duplicate_auditor(
    *,
    stories: list[dict],
    config: dict[str, Any],
    review_config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
    attempt: int,
) -> RoundupDuplicateAudit:
    story_contexts, selection_ref_to_story_id = _selection_contexts_with_refs(
        stories,
        config,
    )
    serialized_context_chars, serialized_context_tokens = _validate_call_context(
        story_contexts,
        config,
    )
    payload = {
        "task": "Audit the proposed selected stories for duplicate event coverage.",
        "constraints": {
            "compare_every_selected_story": True,
            "resolve_indirect_or_unnamed_event_descriptions": True,
            "shared_company_or_topic_is_not_duplication": True,
            "return_every_story_assessment_exactly_once": True,
        },
        "selection_identity": {
            "story_id_values_are_opaque_selection_refs": True,
            "copy_story_id_values_exactly": True,
        },
        "selected_stories": story_contexts,
        "required_story_ids": [item["story_id"] for item in story_contexts],
    }
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": json.dumps(payload, ensure_ascii=False, indent=2),
    }
    rendered_prompt = TASK_PROMPT.format(**prompt_inputs)
    chain = TASK_PROMPT | llm.with_structured_output(
        RoundupDuplicateAudit,
        include_raw=True,
    )
    raw = None
    parsed_dict = None
    last_error = ""
    for audit_attempt in range(1, int(review_config["max_attempts"]) + 1):
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
                if isinstance(parsed, RoundupDuplicateAudit)
                else RoundupDuplicateAudit.model_validate(parsed)
            )
            parsed_dict = transport_output.model_dump(mode="json")
            output = _restore_duplicate_audit_story_ids(
                transport_output,
                selection_ref_to_story_id,
            )
            _validate_duplicate_audit(output, stories)
            llm_calls.append(
                build_llm_call_log(
                    provider=review_config["effective_provider"],
                    model=review_config["effective_model"],
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
                        "audit_attempt": audit_attempt,
                    },
                    duration_seconds=time.time() - started,
                    module_name=DUPLICATE_AUDIT_PROMPT_MODULE,
                )
            )
            return output
        except Exception as exc:
            last_error = clean_text(exc)
            llm_calls.append(
                build_llm_call_log(
                    provider=review_config["effective_provider"],
                    model=review_config["effective_model"],
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
                        "audit_attempt": audit_attempt,
                    },
                    duration_seconds=time.time() - started,
                    parse_error=last_error,
                    module_name=DUPLICATE_AUDIT_PROMPT_MODULE,
                )
            )
    raise RuntimeError(f"focused duplicate audit unresolved after bounded retries: {last_error}")


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
    primary_candidate_count: int,
    recovery_story_ids: set[str],
    focused_duplicate_audit: RoundupDuplicateAudit | None,
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
    duplicate_audit_transport = _duplicate_audit_with_selection_refs(
        focused_duplicate_audit,
        selection_ref_to_story_id,
    )
    recovery_selection_refs = [
        selection_ref
        for selection_ref, story_id in selection_ref_to_story_id.items()
        if story_id in recovery_story_ids
    ]
    payload = {
        "task": "Audit and finalize the proposed roundup slate.",
        "channel": config["channel"],
        "constraints": {
            "min_stories": config["min_stories"],
            "max_stories": config["max_stories"],
            "exactly_one_lead": True,
            "all_candidate_ids_must_be_accounted_for": True,
            "do_not_select_duplicate_editorial_stories": True,
            "judge_episode_level_variety_semantically": True,
            "category_quotas_are_forbidden": True,
        },
        "review_pool": {
            "primary_finalist_count": primary_candidate_count,
            "late_stage_recovery_candidate_count": len(recovery_selection_refs),
            "late_stage_recovery_story_ids": recovery_selection_refs,
            "recovery_candidates_may_replace_a_weaker_or_repetitive_selection": True,
        },
        "selection_identity": {
            "story_id_values_are_opaque_selection_refs": True,
            "copy_story_id_values_exactly": True,
        },
        "proposed_slate": proposed_transport,
        "focused_duplicate_audit": duplicate_audit_transport,
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
                    provider=review_config["effective_provider"],
                    model=review_config["effective_model"],
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
                        "primary_candidate_count": primary_candidate_count,
                        "recovery_story_ids": sorted(recovery_story_ids),
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
                    provider=review_config["effective_provider"],
                    model=review_config["effective_model"],
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
                        "primary_candidate_count": primary_candidate_count,
                        "recovery_story_ids": sorted(recovery_story_ids),
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
    target_finalist_count = _effective_target_finalist_story_count(config)
    if _candidate_pool_is_ready(stories, config):
        return list(stories), [], {
            "strategy": "direct_final_selection",
            "input_story_count": len(stories),
            "final_candidate_story_count": len(stories),
            "target_finalist_story_count": target_finalist_count,
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
        if _candidate_pool_is_ready(active, config):
            break
        if len(active) <= int(config["max_stories"]):
            raise ValueError(
                "The minimum viable roundup candidate pool cannot fit one complete-context "
                "selection call; increase the configured context budget or use a larger-context model"
            )
        batches = _balanced_context_batches(active, config)
        target_total = _screening_target_total(
            stories=active,
            batch_sizes=[len(batch) for batch in batches],
            shortlist_per_batch=shortlist_per_batch,
            config=config,
        )
        quotas = _screening_quotas(
            [len(batch) for batch in batches],
            shortlist_per_batch=shortlist_per_batch,
            target_total=target_total,
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
                "target_output_story_count": target_total,
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
        "target_finalist_story_count": target_finalist_count,
        "rounds": rounds,
    }


def _effective_target_finalist_story_count(config: dict[str, Any]) -> int:
    configured = config.get("target_finalist_stories")
    if configured is None:
        configured = max(
            DEFAULT_PREFERRED_FINALIST_STORY_COUNT,
            int(config["max_stories"]) * 2,
            int(config["max_stories"]) + 2,
        )
    return min(int(config["max_candidate_stories"]), int(configured))


def _candidate_pool_is_ready(
    stories: list[dict[str, Any]],
    config: dict[str, Any],
) -> bool:
    return (
        len(stories) <= _effective_target_finalist_story_count(config)
        and _candidate_pool_fits_one_call(stories, config)
    )


def _screening_target_total(
    *,
    stories: list[dict[str, Any]],
    batch_sizes: list[int],
    shortlist_per_batch: int,
    config: dict[str, Any],
) -> int:
    story_count = len(stories)
    if story_count < 2:
        raise ValueError("semantic screening requires at least two candidate stories")

    hard_ceiling = min(
        story_count - 1,
        int(config["max_candidate_stories"]),
        sum(min(batch_size, shortlist_per_batch) for batch_size in batch_sizes),
    )
    minimum_total = max(len(batch_sizes), int(config["max_stories"]))
    if hard_ceiling < minimum_total:
        raise ValueError(
            "Configured editorial screening limits cannot retain a viable roundup pool"
        )

    finalist_target = _effective_target_finalist_story_count(config)
    if story_count > finalist_target:
        desired_total = max(finalist_target, math.ceil(story_count / 2))
    else:
        contexts, _selection_ref_to_story_id = _selection_contexts_with_refs(
            stories,
            config,
        )
        serialized_context = _serialize_story_contexts(contexts)
        serialized_tokens = text_token_count(
            serialized_context,
            model=config["model"],
            fallback_encoding=config["tokenizer_encoding"],
        )
        char_ratio = int(config["max_call_context_chars"]) / max(
            1,
            len(serialized_context),
        )
        token_ratio = int(config["max_call_context_tokens"]) / max(
            1,
            serialized_tokens,
        )
        desired_total = math.floor(story_count * min(char_ratio, token_ratio))
        desired_total = min(desired_total, story_count - 1)

    return max(minimum_total, min(hard_ceiling, desired_total))


def _build_slate_review_pool(
    *,
    candidate_pool: list[dict[str, Any]],
    screened_out: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    config: dict[str, Any],
    review_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requested_count = int(review_config.get("recovery_candidate_count", 0))
    by_id = {clean_text(story.get("story_id")): story for story in stories}
    story_order = {
        clean_text(story.get("story_id")): index
        for index, story in enumerate(stories)
    }
    primary_ids = {clean_text(story.get("story_id")) for story in candidate_pool}
    ranked_reserves = sorted(
        (
            item
            for item in screened_out
            if clean_text(item.get("story_id")) not in primary_ids
            and clean_text(item.get("story_id")) in by_id
        ),
        key=lambda item: (
            -int(item.get("screening_round") or 0),
            int(item.get("screening_batch") or 0),
            story_order[clean_text(item.get("story_id"))],
        ),
    )

    review_pool = list(candidate_pool)
    included_story_ids: list[str] = []
    considered_story_ids: list[str] = []
    omitted_for_context_story_ids: list[str] = []
    for decision in ranked_reserves:
        if len(included_story_ids) >= requested_count:
            break
        story_id = clean_text(decision.get("story_id"))
        considered_story_ids.append(story_id)
        proposed_pool = [*review_pool, by_id[story_id]]
        if not _candidate_pool_fits_one_call(proposed_pool, config):
            omitted_for_context_story_ids.append(story_id)
            continue
        review_pool = proposed_pool
        included_story_ids.append(story_id)

    return review_pool, {
        "requested_count": requested_count,
        "available_story_count": len(ranked_reserves),
        "considered_story_ids": considered_story_ids,
        "included_story_ids": included_story_ids,
        "omitted_for_context_story_ids": omitted_for_context_story_ids,
        "selection_policy": "latest_semantic_screening_round_first_then_complete_context_fit",
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


def _duplicate_audit_with_selection_refs(
    audit: RoundupDuplicateAudit | None,
    selection_ref_to_story_id: dict[str, str],
) -> dict[str, Any] | None:
    if audit is None:
        return None
    story_id_to_selection_ref = {
        story_id: selection_ref
        for selection_ref, story_id in selection_ref_to_story_id.items()
    }
    payload = audit.model_dump(mode="json")
    for assessment in payload["assessments"]:
        story_id = clean_text(assessment.get("story_id"))
        selection_ref = story_id_to_selection_ref.get(story_id)
        if selection_ref is None:
            raise ValueError(
                "focused duplicate audit references a story outside the slate-review pool: "
                f"{story_id}"
            )
        assessment["story_id"] = selection_ref
    for group in payload["duplicate_story_groups"]:
        group["story_ids"] = [
            story_id_to_selection_ref[story_id]
            for story_id in group["story_ids"]
        ]
        group["preferred_story_id"] = story_id_to_selection_ref[
            group["preferred_story_id"]
        ]
    return payload


def _complete_proposed_slate_for_review(
    draft: RoundupSlateDraft,
    *,
    review_pool: list[dict[str, Any]],
    recovery_story_ids: set[str],
) -> RoundupSlateDraft:
    payload = draft.model_dump(mode="json")
    accounted_ids = {
        clean_text(item.get("story_id"))
        for collection_name in ("selected", "non_selected")
        for item in payload[collection_name]
    }
    for story in review_pool:
        story_id = clean_text(story.get("story_id"))
        if story_id in accounted_ids:
            continue
        is_recovery = story_id in recovery_story_ids
        payload["non_selected"].append(
            {
                "story_id": story_id,
                "action": "reserve",
                "reason": (
                    "Late-stage semantic-screening reserve supplied for final editorial review."
                    if is_recovery
                    else "Finalist supplied for complete final editorial review."
                ),
                "confidence": 0.5,
            }
        )
    return RoundupSlateDraft.model_validate(payload)


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


def _restore_duplicate_audit_story_ids(
    audit: RoundupDuplicateAudit,
    selection_ref_to_story_id: dict[str, str],
) -> RoundupDuplicateAudit:
    payload = audit.model_dump(mode="json")
    for assessment in payload["assessments"]:
        selection_ref = clean_text(assessment.get("story_id"))
        if selection_ref not in selection_ref_to_story_id:
            raise ValueError(
                "focused duplicate audit returned unknown selection reference: "
                f"{selection_ref}"
            )
        assessment["story_id"] = selection_ref_to_story_id[selection_ref]
    kept_groups: list[dict[str, Any]] = []
    dropped_group_ids: set[str] = set()
    for group in payload["duplicate_story_groups"]:
        restored_ids: list[str] = []
        for selection_ref in group["story_ids"]:
            if selection_ref not in selection_ref_to_story_id:
                raise ValueError(
                    "focused duplicate audit group returned unknown selection reference: "
                    f"{selection_ref}"
                )
            story_id = selection_ref_to_story_id[selection_ref]
            # A member listed more than once (or two refs resolving to the same
            # story) is a benign model quirk inside a "these are the same story"
            # group — keep the first occurrence instead of failing the whole
            # editorial selection after bounded retries.
            if story_id not in restored_ids:
                restored_ids.append(story_id)
        preferred_ref = clean_text(group.get("preferred_story_id"))
        if preferred_ref not in selection_ref_to_story_id:
            raise ValueError(
                "focused duplicate audit returned unknown preferred selection reference: "
                f"{preferred_ref}"
            )
        # A duplicate group needs at least two distinct stories; if it collapses
        # below that after de-duping, it is not a real group. Drop it and let its
        # lone member fall back to a normal, ungrouped assessment.
        if len(restored_ids) < 2:
            dropped_group_ids.add(clean_text(group.get("group_id")))
            continue
        group["story_ids"] = restored_ids
        group["preferred_story_id"] = selection_ref_to_story_id[preferred_ref]
        kept_groups.append(group)
    payload["duplicate_story_groups"] = kept_groups
    if dropped_group_ids:
        for assessment in payload["assessments"]:
            if clean_text(assessment.get("duplicate_group_id")) in dropped_group_ids:
                assessment["duplicate_group_id"] = ""
    return RoundupDuplicateAudit.model_validate(payload)


def _validate_duplicate_audit(
    audit: RoundupDuplicateAudit,
    stories: list[dict[str, Any]],
) -> None:
    expected = {clean_text(story.get("story_id")) for story in stories}
    returned = [assessment.story_id for assessment in audit.assessments]
    if len(returned) != len(set(returned)) or set(returned) != expected:
        raise ValueError(
            "focused duplicate audit story coverage mismatch; "
            f"missing={sorted(expected - set(returned))}, "
            f"unknown={sorted(set(returned) - expected)}"
        )
    group_ids: set[str] = set()
    grouped_story_ids: set[str] = set()
    for group in audit.duplicate_story_groups:
        if not group.group_id or group.group_id in group_ids:
            raise ValueError("focused duplicate audit group IDs must be non-empty and unique")
        group_ids.add(group.group_id)
        members = list(group.story_ids)
        if len(members) != len(set(members)):
            raise ValueError(
                f"focused duplicate audit group {group.group_id} repeats a story ID"
            )
        unknown = set(members) - expected
        if unknown:
            raise ValueError(
                f"focused duplicate audit group {group.group_id} has unknown IDs: "
                f"{sorted(unknown)}"
            )
        if group.preferred_story_id not in members:
            raise ValueError(
                f"focused duplicate audit group {group.group_id} preferred story is not a member"
            )
        grouped_story_ids.update(members)
    for assessment in audit.assessments:
        group_id = clean_text(assessment.duplicate_group_id)
        if group_id and group_id not in group_ids:
            raise ValueError(
                "focused duplicate audit assessment references unknown group ID: "
                f"{group_id}"
            )
        if not group_id and assessment.story_id in grouped_story_ids:
            raise ValueError(
                "focused duplicate audit grouped story is missing its duplicate_group_id: "
                f"{assessment.story_id}"
            )


def _validate_slate_resolves_duplicate_audit(
    slate: RoundupSlateReviewDraft,
    audit: RoundupDuplicateAudit | None,
) -> None:
    if audit is None:
        return
    unresolved = _unresolved_duplicate_audit_groups(slate, audit)
    if unresolved:
        raise ValueError(
            "final slate did not resolve focused semantic duplicate groups: "
            f"{unresolved}"
        )


def _unresolved_duplicate_audit_groups(
    slate: RoundupSlateReviewDraft,
    audit: RoundupDuplicateAudit,
) -> list[dict[str, Any]]:
    selected_ids = {decision.story_id for decision in slate.selected}
    return [
        {
            "group_id": group.group_id,
            "selected_story_ids": sorted(selected_ids & set(group.story_ids)),
        }
        for group in audit.duplicate_story_groups
        if len(selected_ids & set(group.story_ids)) > 1
    ]


def _repair_slate_duplicate_audit(
    slate: RoundupSlateReviewDraft,
    audit: RoundupDuplicateAudit | None,
    config: dict[str, Any],
) -> tuple[RoundupSlateReviewDraft, bool, list[str]]:
    if audit is None or not _unresolved_duplicate_audit_groups(slate, audit):
        return slate, False, []

    payload = slate.model_dump(mode="json")
    selected = list(payload["selected"])
    non_selected = list(payload["non_selected"])
    selected_ids = [clean_text(item.get("story_id")) for item in selected]
    selected_id_set = set(selected_ids)
    remove_ids: set[str] = set()
    notes: list[str] = []

    for group in audit.duplicate_story_groups:
        group_ids = {clean_text(story_id) for story_id in group.story_ids}
        selected_group_ids = [
            story_id for story_id in selected_ids if story_id in group_ids
        ]
        if len(selected_group_ids) <= 1:
            continue
        preferred_id = clean_text(group.preferred_story_id)
        if preferred_id not in selected_id_set:
            preferred_id = selected_group_ids[0]
        for story_id in selected_group_ids:
            if story_id == preferred_id:
                continue
            remove_ids.add(story_id)
        notes.append(
            "Resolved focused duplicate audit group "
            f"{group.group_id} by retaining {preferred_id} and reserving "
            f"{sorted(set(selected_group_ids) - {preferred_id})}."
        )

    if not remove_ids:
        return slate, False, []

    selected_after = [
        item
        for item in selected
        if clean_text(item.get("story_id")) not in remove_ids
    ]
    selected_after_ids = {clean_text(item.get("story_id")) for item in selected_after}
    promoted_ids: set[str] = set()
    target_selected_count = min(len(selected), int(config["max_stories"]))
    promotion_candidates = [
        item
        for item in non_selected
        if clean_text(item.get("story_id")) not in remove_ids
        and clean_text(item.get("story_id")) not in selected_after_ids
        and item.get("action") == "reserve"
    ]
    if len(selected_after) < int(config["min_stories"]):
        promotion_candidates.extend(
            item
            for item in non_selected
            if clean_text(item.get("story_id")) not in remove_ids
            and clean_text(item.get("story_id")) not in selected_after_ids
            and item.get("action") != "reserve"
        )
    for candidate in promotion_candidates:
        if len(selected_after) >= target_selected_count:
            break
        story_id = clean_text(candidate.get("story_id"))
        if story_id in promoted_ids:
            continue
        reason = clean_text(candidate.get("reason"))
        selected_after.append(
            {
                "story_id": story_id,
                "role": "brief",
                "selection_reason": (
                    "Promoted from review reserve after focused duplicate-audit "
                    f"repair. {reason}"
                ).strip(),
                "viewer_payoff": reason
                or "Adds a distinct reserve story to keep the roundup complete.",
                "confidence": float(candidate.get("confidence") or 0.5),
            }
        )
        promoted_ids.add(story_id)

    non_selected_after = [
        item
        for item in non_selected
        if clean_text(item.get("story_id")) not in promoted_ids
    ]
    existing_non_selected_ids = {
        clean_text(item.get("story_id")) for item in non_selected_after
    }
    for story_id in selected_ids:
        if story_id not in remove_ids or story_id in existing_non_selected_ids:
            continue
        non_selected_after.append(
            {
                "story_id": story_id,
                "action": "reserve",
                "reason": (
                    "Removed from selected slate by focused duplicate-audit repair; "
                    "the audit preferred another member of the same semantic story group."
                ),
                "confidence": 0.9,
            }
        )

    payload["selected"] = _normalize_selected_roles(selected_after)
    payload["non_selected"] = non_selected_after
    payload["review_changed"] = True
    repair_reason = "Focused duplicate-audit repair removed duplicate selected coverage."
    existing_reason = clean_text(payload.get("review_reason"))
    payload["review_reason"] = (
        f"{existing_reason} {repair_reason}".strip()
        if existing_reason
        else repair_reason
    )
    return RoundupSlateReviewDraft.model_validate(payload), True, notes


def _normalize_selected_roles(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(selected):
        next_item = dict(item)
        if index == 0:
            next_item["role"] = "lead"
        elif next_item.get("role") == "lead":
            next_item["role"] = "major"
        normalized.append(next_item)
    return normalized


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
    capacities = [
        min(batch_size, shortlist_per_batch) for batch_size in batch_sizes
    ]
    target_total = min(target_total, sum(capacities), sum(batch_sizes) - 1)
    quotas = [0 for _ in batch_sizes]
    assigned = 0
    while assigned < target_total:
        made_progress = False
        for index, capacity in enumerate(capacities):
            if quotas[index] >= capacity or assigned >= target_total:
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
    final_returned_ids.update(
        clean_text(story.get("story_id")) for story in candidate_pool
    )
    remaining_screened_out = [
        item
        for item in screened_out
        if clean_text(item.get("story_id")) not in final_returned_ids
    ]
    all_non_selected = [*non_selected, *remaining_screened_out]
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
