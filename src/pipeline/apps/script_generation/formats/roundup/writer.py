from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time
from typing import Any

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel

from .asset_hints import build_story_asset_hints
from .llm_logging import build_llm_call_log
from .models import (
    BookendOutput,
    BookendReviewOutput,
    EpisodeDirectorOutput,
    StoryReviewOutput,
    StorySegmentOutput,
)
from .utils import clean_text, dedupe, json_dumps, source_record_keys, story_id, story_title


TASK_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\n"
    "{user_preamble}\n\n"
    "Task payload:\n"
    "{task_payload}"
)


def generate_roundup_script(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    script_cfg: dict[str, Any],
    prompt_bundles: dict[str, dict[str, str]],
    llm,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    director = direct_episode(
        video_packet=video_packet,
        section_plan=section_plan,
        script_cfg=script_cfg,
        prompt_bundle=prompt_bundles["director"],
        llm=llm,
        llm_calls=llm_calls,
    )
    story_segments, story_reviews = write_story_segments(
        video_packet=video_packet,
        section_plan=section_plan,
        director=director,
        script_cfg=script_cfg,
        writer_prompt_bundle=prompt_bundles["story_writer"],
        reviewer_prompt_bundle=prompt_bundles["story_reviewer"],
        llm=llm,
        llm_calls=llm_calls,
    )
    bookends, bookend_reviews = write_bookends(
        video_packet=video_packet,
        section_plan=section_plan,
        director=director,
        story_segments=story_segments,
        script_cfg=script_cfg,
        writer_prompt_bundle=prompt_bundles["bookend_writer"],
        reviewer_prompt_bundle=prompt_bundles["bookend_reviewer"],
        llm=llm,
        llm_calls=llm_calls,
    )
    return {
        "director": director,
        "story_segments": story_segments,
        "story_asset_hints": [build_story_asset_hints(story) for story in _ordered_stories(video_packet)],
        "bookends": bookends,
        "review": {
            "enabled": bool(script_cfg.get("review", {}).get("enabled", True)),
            "max_revision_passes": int(script_cfg.get("review", {}).get("max_revision_passes", 1)),
            "story_reviews": story_reviews,
            "bookend_reviews": bookend_reviews,
            "bookend_final_gate_issues": _bookend_gate_issues(bookends, video_packet),
            "revision_count": sum(len(item.get("passes", [])) for item in story_reviews) + len(bookend_reviews),
        },
    }


def direct_episode(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    script_cfg: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "task": "Create the editorial through-line for one roundup episode without writing narration.",
        "script_style": script_cfg["script_style"],
        "video_context": _video_context(video_packet),
        "required_story_order": [story_id(story) for story in _ordered_stories(video_packet)],
        "selected_story_summaries": [_director_story(story) for story in _ordered_stories(video_packet)],
        "section_guidance": _compact_section_plan(section_plan),
    }
    response = _invoke_chain(
        module_name="roundup_director",
        output_model=EpisodeDirectorOutput,
        llm=llm,
        prompt_bundle=prompt_bundle,
        task_payload=json_dumps(payload),
        script_cfg=script_cfg,
        metadata={"story_count": len(video_packet.get("stories", []))},
        llm_calls=llm_calls,
    )
    raw = response.model_dump(mode="json")
    required_ids = [story_id(story) for story in _ordered_stories(video_packet)]
    if raw["ordered_story_ids"] != required_ids:
        raise ValueError(
            "roundup_director must preserve the deterministic video packet story order: "
            f"{raw['ordered_story_ids']} != {required_ids}"
        )
    brief_ids = [clean_text(item.get("story_id")) for item in raw["story_briefs"]]
    if brief_ids != required_ids:
        raise ValueError(f"roundup_director returned invalid story briefs: {brief_ids} != {required_ids}")
    return raw


def write_story_segments(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    director: dict[str, Any],
    script_cfg: dict[str, Any],
    writer_prompt_bundle: dict[str, str],
    reviewer_prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stories = _ordered_stories(video_packet)
    story_plans = {clean_text(item.get("story_id")): item for item in section_plan if item.get("section_type") == "story"}
    briefs = {clean_text(item.get("story_id")): item for item in director.get("story_briefs", [])}
    worker_count = min(max(1, int(script_cfg.get("worker_count", 1))), len(stories))

    def generate(index: int, story: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        local_calls: list[dict[str, Any]] = []
        sid = story_id(story)
        segment, review = _write_one_story(
            story=story,
            plan=story_plans[sid],
            brief=briefs[sid],
            previous_story=stories[index - 1] if index else None,
            next_story=stories[index + 1] if index + 1 < len(stories) else None,
            script_cfg=script_cfg,
            writer_prompt_bundle=writer_prompt_bundle,
            reviewer_prompt_bundle=reviewer_prompt_bundle,
            llm=llm,
            llm_calls=local_calls,
        )
        return index, segment, review, local_calls

    ordered: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None] = [None] * len(stories)
    if worker_count == 1:
        for index, story in enumerate(stories):
            _, segment, review, calls = generate(index, story)
            ordered[index] = (segment, review, calls)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {executor.submit(generate, index, story): index for index, story in enumerate(stories)}
            for future in as_completed(future_map):
                index, segment, review, calls = future.result()
                ordered[index] = (segment, review, calls)

    if any(item is None for item in ordered):
        raise RuntimeError("Story generation completed with missing story segments")
    segments: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for item in ordered:
        if item is None:
            continue
        segment, review, calls = item
        segments.append(segment)
        reviews.append(review)
        llm_calls.extend(calls)
    return segments, reviews


def _write_one_story(
    *,
    story: dict[str, Any],
    plan: dict[str, Any],
    brief: dict[str, Any],
    previous_story: dict[str, Any] | None,
    next_story: dict[str, Any] | None,
    script_cfg: dict[str, Any],
    writer_prompt_bundle: dict[str, str],
    reviewer_prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    sid = story_id(story)
    payload = {
        "task": "Write only this story's body as useful audiovisual narration beats.",
        "required_story_id": sid,
        "story_role": plan.get("role", ""),
        "writing_guidance": plan.get("writing_guidance", {}),
        "script_style": script_cfg["script_style"],
        "director_brief": brief,
        "assigned_story_with_full_records": story,
        "available_story_assets": build_story_asset_hints(story),
        "allowed_source_record_keys": source_record_keys(story),
        "previous_story_preview": _story_preview(previous_story),
        "next_story_preview": _story_preview(next_story),
        "rules": [
            "Do not write the episode intro, conclusion, or transition into this story.",
            "Treat suggested_words as soft guidance, never as a quota.",
            "Finish when the story is clear; do not add repetition, filler, or generic commentary to make it longer.",
            "Each beat must be a coherent spoken unit that can anchor one or more visuals.",
            "Use only source_record_keys from this assigned story.",
            "Do not put camera directions inside narration_text.",
        ],
    }
    response = _invoke_chain(
        module_name="roundup_story_writer",
        output_model=StorySegmentOutput,
        llm=llm,
        prompt_bundle=writer_prompt_bundle,
        task_payload=json_dumps(payload),
        script_cfg=script_cfg,
        metadata={"story_id": sid, "story_role": plan.get("role", "")},
        llm_calls=llm_calls,
    )
    current = _validate_story_segment(
        response.model_dump(mode="json"),
        story=story,
        script_cfg=script_cfg,
    )
    passes: list[dict[str, Any]] = []
    max_passes = int(script_cfg.get("review", {}).get("max_revision_passes", 1))
    if not bool(script_cfg.get("review", {}).get("enabled", True)):
        max_passes = 0

    for pass_index in range(1, max_passes + 1):
        issues = _story_gate_issues(current, story=story)
        review_payload = {
            "task": "Review and, only when useful, improve this story segment without touching another section.",
            "required_story_id": sid,
            "writing_guidance": plan.get("writing_guidance", {}),
            "structural_issues": issues,
            "quality_criteria": list(script_cfg.get("review", {}).get("quality_criteria", [])),
            "script_style": script_cfg["script_style"],
            "director_brief": brief,
            "assigned_story_with_full_records": story,
            "available_story_assets": build_story_asset_hints(story),
            "allowed_source_record_keys": source_record_keys(story),
            "current_segment": current,
        }
        review_response = _invoke_chain(
            module_name="roundup_story_reviewer",
            output_model=StoryReviewOutput,
            llm=llm,
            prompt_bundle=reviewer_prompt_bundle,
            task_payload=json_dumps(review_payload),
            script_cfg=script_cfg,
            metadata={"story_id": sid, "pass_index": pass_index, "structural_issues": issues},
            llm_calls=llm_calls,
        ).model_dump(mode="json")
        candidate = _validate_story_segment(
            review_response["revised_segment"],
            story=story,
            script_cfg=script_cfg,
        )
        candidate_issues = _story_gate_issues(candidate, story=story)
        applied = bool(review_response["should_apply_revision"]) and not candidate_issues
        if issues and len(candidate_issues) < len(issues):
            applied = True
        if applied:
            current = candidate
        passes.append(
            {
                "pass_index": pass_index,
                "structural_issues": issues,
                "diagnosis": review_response.get("diagnosis", []),
                "model_recommended_apply": bool(review_response["should_apply_revision"]),
                "candidate_structural_issues": candidate_issues,
                "applied": applied,
            }
        )
        if not applied:
            break

    return current, {
        "story_id": sid,
        "passes": passes,
        "writing_guidance": plan.get("writing_guidance", {}),
        "final_gate_issues": _story_gate_issues(current, story=story),
    }


def write_bookends(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    director: dict[str, Any],
    story_segments: list[dict[str, Any]],
    script_cfg: dict[str, Any],
    writer_prompt_bundle: dict[str, str],
    reviewer_prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    intro_plan = next(item for item in section_plan if item["section_type"] == "intro")
    closing_plan = next(item for item in section_plan if item["section_type"] == "closing")
    payload = {
        "task": "Write the episode intro, story connectors, title-card copy, and conclusion after story bodies are fixed.",
        "script_style": script_cfg["script_style"],
        "episode_direction": director,
        "intro_writing_guidance": intro_plan.get("writing_guidance", {}),
        "closing_writing_guidance": closing_plan.get("writing_guidance", {}),
        "connector_writing_guidance": script_cfg.get("writing_guidance", {}).get("connector", {}),
        "required_story_ids": [story_id(story) for story in _ordered_stories(video_packet)],
        "story_sequence": _segments_for_bookends(video_packet, story_segments),
        "rules": [
            "Do not rewrite or repeat the story bodies.",
            "Connector lines should be short and spoken while the next story title card appears.",
            "The conclusion should synthesize the episode thesis, not introduce a new fact.",
            "Treat suggested word counts as soft guidance, never as quotas.",
            "Finish each bookend when it has done its editorial job; never pad it with filler or repetition.",
            "Visual briefs are directions for downstream planning, never spoken narration.",
        ],
    }
    response = _invoke_chain(
        module_name="roundup_bookend_writer",
        output_model=BookendOutput,
        llm=llm,
        prompt_bundle=writer_prompt_bundle,
        task_payload=json_dumps(payload),
        script_cfg=script_cfg,
        metadata={"story_count": len(story_segments)},
        llm_calls=llm_calls,
    )
    current = _validate_bookends(response.model_dump(mode="json"), video_packet)
    passes: list[dict[str, Any]] = []
    max_passes = int(script_cfg.get("review", {}).get("max_revision_passes", 1))
    if not bool(script_cfg.get("review", {}).get("enabled", True)):
        max_passes = 0

    for pass_index in range(1, max_passes + 1):
        issues = _bookend_gate_issues(current, video_packet)
        review_payload = {
            "task": "Review and, only when useful, improve the bookends and connectors for a stronger YouTube episode.",
            "script_style": script_cfg["script_style"],
            "quality_criteria": list(script_cfg.get("review", {}).get("quality_criteria", [])),
            "episode_direction": {
                key: director.get(key, "")
                for key in ("episode_thesis", "viewer_promise", "hook_strategy", "pacing_strategy")
            },
            "intro_writing_guidance": intro_plan.get("writing_guidance", {}),
            "closing_writing_guidance": closing_plan.get("writing_guidance", {}),
            "connector_writing_guidance": script_cfg.get("writing_guidance", {}).get("connector", {}),
            "required_story_ids": payload["required_story_ids"],
            "story_sequence": [
                {
                    key: item.get(key, "")
                    for key in ("story_id", "display_title", "story_thesis", "viewer_takeaway")
                }
                for item in payload["story_sequence"]
            ],
            "structural_issues": issues,
            "current_bookends": current,
            "rules": [
                "Apply a revision only when it materially improves hook, continuity, clarity, pacing, or concision.",
                "Do not lengthen a section merely to approach a suggested word count.",
                "Preserve the required story order and do not introduce new factual claims.",
            ],
        }
        review_response = _invoke_chain(
            module_name="roundup_bookend_reviewer",
            output_model=BookendReviewOutput,
            llm=llm,
            prompt_bundle=reviewer_prompt_bundle,
            task_payload=json_dumps(review_payload),
            script_cfg=script_cfg,
            metadata={"pass_index": pass_index, "structural_issues": issues},
            llm_calls=llm_calls,
        ).model_dump(mode="json")
        candidate = _validate_bookends(review_response["revised_bookends"], video_packet)
        candidate_issues = _bookend_gate_issues(candidate, video_packet)
        applied = bool(review_response["should_apply_revision"]) and not candidate_issues
        if issues and len(candidate_issues) < len(issues):
            applied = True
        if applied:
            current = candidate
        passes.append(
            {
                "pass_index": pass_index,
                "structural_issues": issues,
                "diagnosis": review_response.get("diagnosis", []),
                "model_recommended_apply": bool(review_response["should_apply_revision"]),
                "candidate_structural_issues": candidate_issues,
                "applied": applied,
            }
        )
        if not applied:
            break
    return current, passes


def _invoke_chain(
    *,
    module_name: str,
    output_model,
    llm,
    prompt_bundle: dict[str, str],
    task_payload: str,
    script_cfg: dict[str, Any],
    metadata: dict[str, Any],
    llm_calls: list[dict[str, Any]],
):
    structured_options: dict[str, Any] = {"include_raw": True}
    if str(script_cfg.get("provider", "")).lower() == "openai":
        structured_options["strict"] = True
    structured_llm = llm.with_structured_output(output_model, **structured_options)
    chain = TASK_PROMPT | structured_llm
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": task_payload,
    }
    rendered_prompt = TASK_PROMPT.format(**prompt_inputs)
    started = time.time()
    retry_config = script_cfg.get("llm_retry", {})
    retry_enabled = bool(retry_config.get("enabled", True))
    max_attempts = int(retry_config.get("max_attempts", 5)) if retry_enabled else 1
    retry_errors: list[dict[str, Any]] = []
    attempt_count = 0
    while True:
        attempt_count += 1
        try:
            result = chain.invoke(prompt_inputs)
            break
        except Exception as exc:
            status_code = _exception_status_code(exc)
            retryable = _is_retryable_llm_error(exc, status_code=status_code)
            retry_entry = {
                "attempt": attempt_count,
                "status_code": status_code,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            if not retryable or attempt_count >= max_attempts:
                retry_errors.append(retry_entry)
                call_metadata = {
                    **metadata,
                    "attempt_count": attempt_count,
                    "retry_count": max(0, attempt_count - 1),
                    "retry_errors": retry_errors,
                }
                llm_calls.append(
                    build_llm_call_log(
                        module_name=module_name,
                        provider=str(script_cfg.get("provider", "")),
                        model=str(script_cfg.get("model", "")),
                        rendered_prompt=rendered_prompt,
                        raw_response=None,
                        parsed_output=None,
                        metadata=call_metadata,
                        duration_seconds=time.time() - started,
                        parse_error=str(exc),
                    )
                )
                raise
            delay_seconds = _retry_delay_seconds(
                exc,
                attempt=attempt_count,
                retry_config=retry_config,
            )
            retry_entry["delay_seconds"] = round(delay_seconds, 3)
            retry_errors.append(retry_entry)
            time.sleep(delay_seconds)
    duration = time.time() - started
    call_metadata = {
        **metadata,
        "attempt_count": attempt_count,
        "retry_count": max(0, attempt_count - 1),
    }
    if retry_errors:
        call_metadata["retry_errors"] = retry_errors
    raw = result.get("raw") if isinstance(result, dict) else None
    parsed = result.get("parsed") if isinstance(result, dict) else result
    parsing_error = result.get("parsing_error") if isinstance(result, dict) else None

    if parsing_error is not None or parsed is None:
        llm_calls.append(
            build_llm_call_log(
                module_name=module_name,
                provider=str(script_cfg.get("provider", "")),
                model=str(script_cfg.get("model", "")),
                rendered_prompt=rendered_prompt,
                raw_response=raw,
                parsed_output=None,
                metadata=call_metadata,
                duration_seconds=duration,
                parse_error=str(parsing_error),
            )
        )
        error = ValueError(f"LLM structured output failed for {module_name}")
        if isinstance(parsing_error, BaseException):
            raise error from parsing_error
        raise error

    parsed_model = parsed if isinstance(parsed, output_model) else output_model.model_validate(parsed)
    parsed_output = parsed_model.model_dump(mode="json")
    llm_calls.append(
        build_llm_call_log(
            module_name=module_name,
            provider=str(script_cfg.get("provider", "")),
            model=str(script_cfg.get("model", "")),
            rendered_prompt=rendered_prompt,
            raw_response=raw,
            parsed_output=parsed_output,
            metadata=call_metadata,
            duration_seconds=duration,
        )
    )
    return parsed_model


def _exception_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _is_retryable_llm_error(exc: Exception, *, status_code: int | None) -> bool:
    if status_code in {429, 500, 502, 503, 504}:
        return True
    return type(exc).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
        "ServiceUnavailableError",
    }


def _retry_delay_seconds(
    exc: Exception,
    *,
    attempt: int,
    retry_config: dict[str, Any],
) -> float:
    initial_delay = float(retry_config.get("initial_delay_seconds", 1.0))
    maximum_delay = float(retry_config.get("max_delay_seconds", 30.0))
    exponential_delay = initial_delay * (2 ** max(0, attempt - 1))
    server_delay = _server_retry_delay_seconds(exc)
    if server_delay is not None:
        exponential_delay = max(exponential_delay, server_delay + 0.25)
    return min(maximum_delay, exponential_delay)


def _server_retry_delay_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    for key, milliseconds in (
        ("retry-after-ms", True),
        ("retry-after", False),
        ("x-ratelimit-reset-tokens", False),
        ("x-ratelimit-reset-requests", False),
    ):
        value = headers.get(key) if hasattr(headers, "get") else None
        parsed = _parse_retry_delay(value, milliseconds=milliseconds)
        if parsed is not None:
            return parsed
    match = re.search(
        r"try again in\s+([0-9]+(?:\.[0-9]+)?)\s*(ms|milliseconds?|s|seconds?)",
        str(exc),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1))
    return value / 1000 if match.group(2).lower().startswith("m") else value


def _parse_retry_delay(value: Any, *, milliseconds: bool) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if milliseconds:
        try:
            return float(text) / 1000
        except ValueError:
            return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(ms|s)?", text)
    if not match:
        return None
    delay = float(match.group(1))
    return delay / 1000 if match.group(2) == "ms" else delay


def _validate_story_segment(
    segment: dict[str, Any],
    *,
    story: dict[str, Any],
    script_cfg: dict[str, Any],
) -> dict[str, Any]:
    raw = StorySegmentOutput.model_validate(segment).model_dump(mode="json")
    sid = story_id(story)
    if clean_text(raw.get("story_id")) != sid:
        raise ValueError(f"Story writer returned story_id {raw.get('story_id')!r}; expected {sid!r}")
    allowed_keys = set(source_record_keys(story))
    used_keys: list[str] = []
    for beat in raw["beats"]:
        beat["narration_text"] = clean_text(beat["narration_text"])
        beat["source_record_keys"] = dedupe(list(beat.get("source_record_keys") or []))
        unknown = sorted(set(beat["source_record_keys"]) - allowed_keys)
        if unknown:
            raise ValueError(f"Story writer used source keys outside {sid}: {unknown}")
        used_keys.extend(beat["source_record_keys"])
    if allowed_keys and not used_keys:
        raise ValueError(f"Story writer did not ground {sid} in any assigned source record")
    raw["display_title"] = clean_text(raw.get("display_title")) or story_title(story)
    return raw


def _validate_bookends(bookends: dict[str, Any], video_packet: dict[str, Any]) -> dict[str, Any]:
    raw = BookendOutput.model_validate(bookends).model_dump(mode="json")
    required_ids = [story_id(story) for story in _ordered_stories(video_packet)]
    connector_ids = [clean_text(item.get("story_id")) for item in raw["story_connectors"]]
    if connector_ids != required_ids:
        raise ValueError(f"Bookend writer connector IDs must match story order: {connector_ids} != {required_ids}")
    if not raw["intro_beats"] or not raw["closing_beats"]:
        raise ValueError("Bookend writer must return intro and closing beats")
    return raw


def _story_gate_issues(
    segment: dict[str, Any],
    *,
    story: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    beats = list(segment.get("beats") or [])
    if not beats:
        issues.append("story_has_no_narration_beats")
        return issues
    allowed_keys = set(source_record_keys(story))
    used_keys = {
        clean_text(key)
        for beat in beats
        for key in list(beat.get("source_record_keys") or [])
        if clean_text(key)
    }
    if allowed_keys and not used_keys:
        issues.append("story_has_no_assigned_source_grounding")
    unknown_keys = sorted(used_keys - allowed_keys)
    if unknown_keys:
        issues.append(f"story_uses_unassigned_source_keys:{unknown_keys}")
    return issues


def _bookend_gate_issues(
    bookends: dict[str, Any],
    video_packet: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    if not list(bookends.get("intro_beats") or []):
        issues.append("missing_intro_beats")
    if not list(bookends.get("closing_beats") or []):
        issues.append("missing_closing_beats")
    required_ids = [story_id(story) for story in _ordered_stories(video_packet)]
    connectors = list(bookends.get("story_connectors") or [])
    connector_ids = [clean_text(item.get("story_id")) for item in connectors]
    if connector_ids != required_ids:
        issues.append(f"connector_story_order_mismatch:{connector_ids}!={required_ids}")
    for connector in connectors:
        sid = clean_text(connector.get("story_id"))
        if not clean_text(connector.get("display_title")):
            issues.append(f"missing_connector_display_title:{sid}")
        if not clean_text(connector.get("transition_line")):
            issues.append(f"missing_connector_transition:{sid}")
    return issues


def _ordered_stories(video_packet: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        list(video_packet.get("stories", [])),
        key=lambda story: int((story.get("video_segment") or {}).get("segment_order", 999999)),
    )


def _video_context(video_packet: dict[str, Any]) -> dict[str, Any]:
    duration_policy = dict(video_packet.get("duration_policy") or {})
    if not duration_policy:
        legacy_ceiling = video_packet.get("target_duration_seconds")
        duration_policy = {
            "mode": "content_driven",
            "configured_ceiling_seconds": legacy_ceiling,
            "timing_source_of_truth": "voiceover",
        }
    return {
        "selected_format": video_packet.get("selected_format", ""),
        "duration_policy": duration_policy,
        "story_count": len(video_packet.get("stories", [])),
    }


def _compact_section_plan(section_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "section_id": item["section_id"],
            "section_type": item["section_type"],
            "story_id": item.get("story_id", ""),
            "story_title": item.get("story_title", ""),
            "role": item.get("role", ""),
            "writing_guidance": item.get("writing_guidance", {}),
        }
        for item in section_plan
    ]


def _director_story(story: dict[str, Any]) -> dict[str, Any]:
    identity = story.get("story_identity") or {}
    segment = story.get("video_segment") or {}
    return {
        "story_id": story_id(story),
        "story_title": story_title(story),
        "role": segment.get("role", ""),
        "primary_entity": identity.get("primary_entity", ""),
        "product_or_project": identity.get("product_or_project", ""),
        "story_action": identity.get("story_action", ""),
        "one_sentence_story": identity.get("one_sentence_story", ""),
        "why_it_matters": identity.get("why_it_matters", ""),
    }


def _story_preview(story: dict[str, Any] | None) -> dict[str, Any]:
    return _director_story(story) if story else {}


def _segments_for_bookends(video_packet: dict[str, Any], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {clean_text(item.get("story_id")): item for item in segments}
    output: list[dict[str, Any]] = []
    for story in _ordered_stories(video_packet):
        sid = story_id(story)
        segment = by_id[sid]
        output.append(
            {
                **_director_story(story),
                "display_title": segment.get("display_title", ""),
                "story_thesis": segment.get("story_thesis", ""),
                "viewer_takeaway": segment.get("viewer_takeaway", ""),
                "beat_summaries": [
                    {
                        "beat_type": beat.get("beat_type", ""),
                        "narration_preview": clean_text(beat.get("narration_text", ""))[:240],
                    }
                    for beat in segment.get("beats", [])
                ],
            }
        )
    return output
