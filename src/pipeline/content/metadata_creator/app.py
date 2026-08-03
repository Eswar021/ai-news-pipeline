from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time
from typing import Any, Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError

from src.pipeline.contracts import (
    build_artifact_provenance,
    require_matching_run_id,
    validate_script_provenance,
)

from .config import (
    METADATA_PROMPT_MODULE_BY_FORMAT,
    PACKAGE_TYPE,
    SUPPORTED_FORMATS,
)
from .contract import MetadataRequest, MetadataResponse
from .llm_client import make_llm
from .llm_logging import build_llm_call_log
from .prompt_loader import load_prompt_bundle
from .utils import clean_tag, clean_text, clean_thumbnail_text, dedupe, format_timestamp, shorten_title, source_url_from_record


IST = timezone(timedelta(hours=5, minutes=30))

TASK_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        ("human", "{user_preamble}\n\nTask payload:\n{task_payload}"),
    ]
)


class TitleOptionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    accuracy_risk: Literal["low", "medium", "high"]
    click_potential: Literal["low", "medium", "medium_high", "high"]
    why_it_works: str
    angle_strategy: str = Field(
        description=(
            "A short label for the title's strategy — format-appropriate. Roundup titles use strategies "
            "like lead_story_roundup, multi_story_contrast, episode_question, concrete_list; deep-dive "
            "titles use strategies like core_tension, striking_detail, episode_question. Descriptive only."
        )
    )
    represented_story_ids: list[str] = Field(
        description="Exact selected story IDs materially represented by this title."
    )
    relationship_basis: str = Field(
        description=(
            "The script-supported relationship behind comparison or rivalry wording, or an empty string "
            "when the title makes no such relationship claim."
        )
    )
    scope_and_state_check: str = Field(
        description=(
            "A concise self-check that the title signals roundup scope and preserves current, planned, "
            "claimed, and released states from the completed episode."
        )
    )


class ChapterTitleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str


class ThumbnailConceptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_name: str
    visual_hook: str
    primary_subject: str
    secondary_subjects: list[str]
    composition: str
    background_direction: str
    text_overlay: str
    color_direction: str
    emotional_tone: str
    represented_story_ids: list[str]
    source_record_keys: list[str]
    generation_prompt: str
    avoid: list[str]


class MetadataDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_options: list[TitleOptionOutput]
    thumbnail_text_options: list[str]
    thumbnail_concepts: list[ThumbnailConceptOutput]
    blocked_title_angles: list[str] = Field(default_factory=list)
    chapter_titles: list[ChapterTitleOutput]
    description_intro: str
    tags: list[str] = Field(default_factory=list)


def run(input_json: dict) -> dict:
    request = MetadataRequest.model_validate(input_json)
    generated_at = _iso_now()
    run_id = request.run.run_id
    config = request.config.model_dump(mode="json")
    script_generation = request.input.script_generation
    video_packaging = request.input.video_packaging
    script_package = script_generation.data.script_package
    video_packet = video_packaging.data.video_packet
    llm_calls: list[dict[str, Any]] = []

    require_matching_run_id(run_id, script_generation.data.run_id, "script_generation")
    require_matching_run_id(run_id, video_packaging.data.run_id, "video_packaging")
    script_provenance = validate_script_provenance(
        script_package,
        run_id=run_id,
        upstream_run_id=script_generation.data.run_id,
    )
    selected_format = _resolve_supported_format(
        script_generation.data.selected_format, video_packaging.data.selected_format, video_packet
    )

    sections = _script_sections(script_package)
    chapters = _build_chapters(
        sections,
        max_title_chars=int(config["metadata_policy"]["chapter_title_max_chars"]),
    )
    source_urls = _source_urls(video_packet)
    if script_generation.status != "ok" or not bool(
        script_generation.handoff.get("ready_for_metadata_creation", False)
    ):
        return _failed_response(
            run_id=run_id,
            generated_at=generated_at,
            config=config,
            selected_format=selected_format,
            chapters=chapters,
            source_urls=source_urls,
            reason="Upstream script_generation result is not ready for metadata creation.",
            llm_calls=llm_calls,
        )
    if video_packaging.status != "ok" or not bool(video_packaging.handoff.get("ready_for_script_generation", False)):
        return _failed_response(
            run_id=run_id,
            generated_at=generated_at,
            config=config,
            selected_format=selected_format,
            chapters=chapters,
            source_urls=source_urls,
            reason="Upstream video_packaging result is not valid for metadata creation.",
            llm_calls=llm_calls,
        )

    full_script = clean_text(script_package.get("full_script", ""))
    if not full_script:
        return _failed_response(
            run_id=run_id,
            generated_at=generated_at,
            config=config,
            selected_format=selected_format,
            chapters=chapters,
            source_urls=source_urls,
            reason="script_generation.data.script_package.full_script is missing or empty.",
            llm_calls=llm_calls,
        )
    if not sections:
        return _failed_response(
            run_id=run_id,
            generated_at=generated_at,
            config=config,
            selected_format=selected_format,
            chapters=chapters,
            source_urls=source_urls,
            reason="script_generation.data.script_package.sections is missing or empty.",
            llm_calls=llm_calls,
        )
    if bool(config["metadata_policy"]["include_source_urls"]) and not source_urls:
        return _failed_response(
            run_id=run_id,
            generated_at=generated_at,
            config=config,
            selected_format=selected_format,
            chapters=chapters,
            source_urls=source_urls,
            reason="No source URLs were available from selected story records.",
            llm_calls=llm_calls,
        )

    prompt_bundle = load_prompt_bundle(
        METADATA_PROMPT_MODULE_BY_FORMAT[selected_format], config["prompt_version"]
    )
    try:
        draft = _generate_metadata_draft(
            script_package=script_package,
            video_packet=video_packet,
            config=config,
            selected_format=selected_format,
            prompt_bundle=prompt_bundle,
            llm_runtime=_build_llm_runtime(config),
            llm_calls=llm_calls,
        )
    except Exception as exc:
        return _failed_response(
            run_id=run_id,
            generated_at=generated_at,
            config=config,
            selected_format=selected_format,
            chapters=chapters,
            source_urls=source_urls,
            reason=f"{type(exc).__name__}: {exc}",
            llm_calls=llm_calls,
        )
    chapters = _apply_generated_chapter_titles(
        chapters=chapters,
        sections=sections,
        generated_titles=draft.get("chapter_titles", []),
    )
    metadata = _build_youtube_metadata(
        draft=draft,
        script_package=script_package,
        video_packet=video_packet,
        config=config,
        chapters=chapters,
        source_urls=source_urls,
    )
    checks = _check_metadata(metadata, sections, config)
    metadata_package = {
        "package_type": PACKAGE_TYPE,
        "package_stage": "draft",
        "selected_format": selected_format,
        "youtube_metadata": metadata,
        "checks": checks,
    }
    metadata_package["provenance"] = build_artifact_provenance(
        artifact_type="metadata_draft",
        run_id=run_id,
        parents={"script": script_provenance["script_fingerprint"]},
        script_source=script_provenance.get("script_source", ""),
        payload=metadata,
    )
    status = "ok" if checks["passed"] else "failed"
    failure_reason = "" if status == "ok" else "; ".join(checks["errors"])
    response = MetadataResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": selected_format,
            "metadata_package": metadata_package,
        },
        summary=_build_summary(metadata, llm_calls, failure_reason),
        handoff={
            "ready_for_metadata_finalization": status == "ok",
            "chapters_finalized": False,
            "ready_for_media_production": False,
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _generate_metadata_draft(
    *,
    script_package: dict[str, Any],
    video_packet: dict[str, Any],
    config: dict[str, Any],
    selected_format: str,
    prompt_bundle: dict[str, str],
    llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "task": f"Generate YouTube metadata for the completed {selected_format} script.",
        "channel": config["channel"],
        "metadata_policy": config["metadata_policy"],
        "recent_title_angles_to_avoid": _recent_title_angles(config),
        "video_context": _video_context(video_packet, script_package, selected_format),
        "script_sections": _sections_for_prompt(script_package.get("sections", [])),
        "full_script": clean_text(script_package.get("full_script", "")),
        "selected_stories_context": _stories_for_prompt(video_packet.get("stories", [])),
        "source_meaning_boundaries": _source_meaning_boundaries_for_prompt(script_package),
        "required_output": {
            "title_options": (
                "Use metadata_policy.title_option_count when possible. For every option, identify its angle strategy, "
                "the exact represented story IDs, any real relationship basis, and a scope/state self-check."
            ),
            "thumbnail_text_options": "Use metadata_policy.thumbnail_text_option_count when possible.",
            "thumbnail_concepts": (
                "Return metadata_policy.thumbnail_concept_count distinct, production-ready visual directions. "
                "Each concept must describe its visual hook, subjects, composition, background, overlay text, "
                "color, emotion, represented story IDs, useful source record keys, a standalone image-generation "
                "prompt, and visual elements to avoid. Do not claim that a source asset exists unless its exact "
                "record key appears in selected_stories_context."
            ),
            "chapter_titles": (
                "Return one concise, complete chapter title for every exact script section_id. Keep each title within "
                "metadata_policy.chapter_title_max_chars. Do not return timestamps and never cut a phrase mid-thought."
            ),
            "description_intro": "Short description opener only. Do not include chapters or source links.",
            "tags": "Useful YouTube tags only.",
        },
    }
    return _invoke_runtime_chain(
        module_name=METADATA_PROMPT_MODULE_BY_FORMAT[selected_format],
        output_model=MetadataDraftOutput,
        llm_runtime=llm_runtime,
        prompt_bundle=prompt_bundle,
        task_payload=json.dumps(payload, ensure_ascii=False, indent=2),
        metadata={"selected_format": selected_format, "story_count": len(video_packet.get("stories", []))},
        llm_calls=llm_calls,
    )


def _build_llm_runtime(config: dict[str, Any]) -> dict[str, Any]:
    runtime = {
        "config": config,
        "llm": make_llm(
            provider=config["provider"],
            model=config["model"],
            temperature=float(config["temperature"]),
            base_url=config.get("base_url"),
            max_retries=0,
            provider_options=config.get("provider_options"),
        ),
    }
    fallback_config = config.get("content_filter_fallback")
    if fallback_config:
        fallback_config = dict(fallback_config)
        fallback_config["llm_retry"] = dict(
            fallback_config.get("llm_retry") or config.get("llm_retry") or {}
        )
        runtime["content_filter_fallback"] = {
            "config": fallback_config,
            "llm": make_llm(
                provider=fallback_config["provider"],
                model=fallback_config["model"],
                temperature=float(fallback_config["temperature"]),
                base_url=fallback_config.get("base_url"),
                max_retries=0,
                provider_options=fallback_config.get("provider_options"),
            ),
        }
    return runtime


def _structured_chain(*, llm, output_model, config: dict[str, Any]):
    structured_config = dict(config.get("structured_output") or {})
    structured_llm = llm.with_structured_output(
        output_model,
        **_structured_output_options(structured_config),
    )
    return TASK_PROMPT | structured_llm


def _structured_output_options(structured_config: dict[str, Any]) -> dict[str, Any]:
    method = str(structured_config.get("method") or "json_schema")
    options: dict[str, Any] = {
        "include_raw": True,
        "method": method,
    }
    if method != "json_mode":
        options["strict"] = bool(structured_config.get("strict", True))
    return options


def _task_payload_for_structured_output(
    task_payload: str,
    *,
    output_model,
    method: str,
) -> str:
    if method != "json_mode":
        return task_payload
    schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    return (
        f"{task_payload}\n\n"
        "Return only one JSON object matching the following JSON Schema exactly. "
        "Use only enum values defined by the schema, use null only where allowed, "
        "and do not wrap the object in Markdown.\n"
        f"JSON Schema:\n{schema}"
    )


def _invoke_runtime_chain(
    *,
    module_name: str,
    output_model,
    llm_runtime: dict[str, Any],
    prompt_bundle: dict[str, str],
    task_payload: str,
    metadata: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    primary_config = llm_runtime["config"]
    fallback_runtime = llm_runtime.get("content_filter_fallback")
    try:
        return _invoke_chain(
            module_name=module_name,
            output_model=output_model,
            chain=_structured_chain(
                llm=llm_runtime["llm"],
                output_model=output_model,
                config=primary_config,
            ),
            prompt_bundle=prompt_bundle,
            task_payload=task_payload,
            config=primary_config,
            metadata={
                **metadata,
                "route_attempt": "primary",
                "content_filter_fallback_configured": fallback_runtime is not None,
            },
            llm_calls=llm_calls,
        )
    except Exception as exc:
        if fallback_runtime is None or not _is_content_filter_error(exc):
            raise

    fallback_config = fallback_runtime["config"]
    return _invoke_chain(
        module_name=module_name,
        output_model=output_model,
        chain=_structured_chain(
            llm=fallback_runtime["llm"],
            output_model=output_model,
            config=fallback_config,
        ),
        prompt_bundle=prompt_bundle,
        task_payload=task_payload,
        config=fallback_config,
        metadata={
            **metadata,
            "route_attempt": "content_filter_fallback",
            "fallback_trigger": "content_filter",
            "fallback_from_provider": primary_config.get("provider", ""),
            "fallback_from_model": primary_config.get("model", ""),
        },
        llm_calls=llm_calls,
    )


def _invoke_chain(
    *,
    module_name: str,
    output_model,
    chain,
    prompt_bundle: dict[str, str],
    task_payload: str,
    config: dict[str, Any],
    metadata: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    structured_config = dict(config.get("structured_output") or {})
    task_payload = _task_payload_for_structured_output(
        task_payload,
        output_model=output_model,
        method=str(structured_config.get("method") or "json_schema"),
    )
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": task_payload,
    }
    rendered_messages = [
        {
            "role": "system" if message.type == "system" else "user",
            "content": str(message.content),
        }
        for message in TASK_PROMPT.format_messages(**prompt_inputs)
    ]
    started = time.time()
    retry_config = dict(config.get("llm_retry") or {})
    retry_enabled = bool(retry_config.get("enabled", True))
    max_transient_attempts = int(retry_config.get("max_attempts", 2)) if retry_enabled else 1
    max_structured_attempts = int(retry_config.get("max_structured_output_attempts", 2)) if retry_enabled else 1
    transient_failures = 0
    structured_failures = 0
    retry_errors: list[dict[str, Any]] = []
    attempt_count = 0

    while True:
        attempt_count += 1
        attempt_started = time.time()
        try:
            result = chain.invoke(prompt_inputs)
        except Exception as exc:
            status_code = _exception_status_code(exc)
            is_structured = _is_structured_output_error(exc)
            if is_structured:
                structured_failures += 1
                can_retry = retry_enabled and structured_failures < max_structured_attempts
            else:
                transient_failures += 1
                can_retry = (
                    retry_enabled
                    and _is_retryable_llm_error(exc, status_code=status_code)
                    and transient_failures < max_transient_attempts
                )
            retry_entry = {
                "attempt": attempt_count,
                "status_code": status_code,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            if can_retry:
                delay = _retry_delay_seconds(attempt_count, retry_config)
                retry_entry["delay_seconds"] = round(delay, 3)
                retry_errors.append(retry_entry)
                time.sleep(delay)
                continue
            retry_errors.append(retry_entry)
            llm_calls.append(
                build_llm_call_log(
                    module_name=module_name,
                    provider=config["provider"],
                    model=config["model"],
                    messages=rendered_messages,
                    raw_response=None,
                    parsed_output=None,
                    metadata={
                        **metadata,
                        "attempt_count": attempt_count,
                        "retry_count": max(0, attempt_count - 1),
                        "retry_errors": retry_errors,
                    },
                    duration_seconds=time.time() - started,
                    parse_error=str(exc),
                )
            )
            raise

        raw = result.get("raw") if isinstance(result, dict) else None
        parsed = result.get("parsed") if isinstance(result, dict) else result
        parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
        parsed_model = None
        if parsing_error is None and parsed is not None:
            try:
                parsed_model = parsed if isinstance(parsed, output_model) else output_model.model_validate(parsed)
            except PydanticValidationError as exc:
                parsing_error = exc

        call_metadata = {
            **metadata,
            "attempt_count": attempt_count,
            "retry_count": max(0, attempt_count - 1),
        }
        if retry_errors:
            call_metadata["retry_errors"] = list(retry_errors)
        if parsing_error is not None or parsed_model is None:
            structured_failures += 1
            parse_error_text = str(parsing_error or "missing parsed output")
            llm_calls.append(
                build_llm_call_log(
                    module_name=module_name,
                    provider=config["provider"],
                    model=config["model"],
                    messages=rendered_messages,
                    raw_response=raw,
                    parsed_output=None,
                    metadata=call_metadata,
                    duration_seconds=time.time() - attempt_started,
                    parse_error=parse_error_text,
                )
            )
            if retry_enabled and structured_failures < max_structured_attempts:
                delay = _retry_delay_seconds(structured_failures, retry_config)
                retry_errors.append(
                    {
                        "attempt": attempt_count,
                        "status_code": None,
                        "error_type": "StructuredOutputError",
                        "error": parse_error_text,
                        "delay_seconds": round(delay, 3),
                    }
                )
                time.sleep(delay)
                continue
            error = ValueError(f"LLM structured output failed for {module_name}: {parse_error_text}")
            if isinstance(parsing_error, BaseException):
                raise error from parsing_error
            raise error

        parsed_output = parsed_model.model_dump(mode="json")
        llm_calls.append(
            build_llm_call_log(
                module_name=module_name,
                provider=config["provider"],
                model=config["model"],
                messages=rendered_messages,
                raw_response=raw,
                parsed_output=parsed_output,
                metadata=call_metadata,
                duration_seconds=time.time() - attempt_started,
            )
        )
        return parsed_output


def _build_youtube_metadata(
    *,
    draft: dict[str, Any],
    script_package: dict[str, Any],
    video_packet: dict[str, Any],
    config: dict[str, Any],
    chapters: list[dict[str, Any]],
    source_urls: list[str],
) -> dict[str, Any]:
    policy = config["metadata_policy"]
    title_options = _clean_title_options(
        draft.get("title_options", []),
        int(policy["title_option_count"]),
    )
    thumbnail_options = _clean_thumbnail_options(
        draft.get("thumbnail_text_options", []),
        int(policy["thumbnail_text_option_count"]),
    )
    thumbnail_concepts = _clean_thumbnail_concepts(
        draft.get("thumbnail_concepts", []),
        int(policy["thumbnail_concept_count"]),
    )
    tags = _build_tags(
        draft.get("tags", []),
        video_packet,
        int(policy["max_tags"]),
        blocked_tags=list(policy.get("blocked_tags", [])),
    )
    description = _build_description(
        description_intro=draft.get("description_intro", ""),
        chapters=chapters,
        source_urls=source_urls if bool(policy["include_source_urls"]) else [],
        channel=config["channel"],
    )
    return {
        "title_options": title_options,
        "thumbnail_text_options": thumbnail_options,
        "thumbnail_concepts": thumbnail_concepts,
        "blocked_title_angles": dedupe([clean_text(value) for value in draft.get("blocked_title_angles", [])]),
        "description_draft": description,
        "description_components": {
            "intro": clean_text(draft.get("description_intro", "")),
            "channel_footer": _channel_footer(config["channel"]),
            "include_source_urls": bool(policy["include_source_urls"]),
        },
        "chapters": chapters,
        "tags": tags,
        "source_urls": source_urls if bool(policy["include_source_urls"]) else [],
        "metadata_basis": {
            "script_section_count": len(script_package.get("sections", [])),
            "script_beat_count": sum(len(section.get("beats", [])) for section in script_package.get("sections", [])),
            "selected_story_count": len(video_packet.get("stories", [])),
            "source_policy": "final_script_primary_video_packet_sources",
            "chapter_timing_source": "script_estimate",
            "chapters_finalized": False,
        },
    }


def _clean_title_options(
    raw_options: list[Any],
    limit: int,
) -> list[dict[str, Any]]:
    cleaned = []
    for item in raw_options:
        if isinstance(item, str):
            option = {
                "title": clean_text(item),
                "accuracy_risk": "medium",
                "click_potential": "medium",
                "why_it_works": "",
            }
        else:
            option = dict(item)
        title = clean_text(option.get("title", ""))
        if not title:
            continue
        cleaned.append(
            {
                "title": title,
                "accuracy_risk": _allowed_value(option.get("accuracy_risk", ""), {"low", "medium", "high"}, "medium"),
                "click_potential": _allowed_value(
                    option.get("click_potential", ""),
                    {"low", "medium", "medium_high", "high"},
                    "medium",
                ),
                "why_it_works": clean_text(option.get("why_it_works", "")),
                "angle_strategy": clean_text(option.get("angle_strategy", "")),
                "represented_story_ids": dedupe(list(option.get("represented_story_ids") or [])),
                "relationship_basis": clean_text(option.get("relationship_basis", "")),
                "scope_and_state_check": clean_text(option.get("scope_and_state_check", "")),
            }
        )
    deduped = []
    seen = set()
    for option in cleaned:
        lookup = option["title"].lower()
        if lookup in seen:
            continue
        seen.add(lookup)
        deduped.append(option)
    return deduped[:limit]


def _clean_thumbnail_options(raw_options: list[Any], limit: int) -> list[str]:
    return dedupe([clean_thumbnail_text(str(value)) for value in raw_options])[:limit]


def _clean_thumbnail_concepts(raw_concepts: list[Any], limit: int) -> list[dict[str, Any]]:
    concepts: list[dict[str, Any]] = []
    for item in raw_concepts:
        if not isinstance(item, dict):
            continue
        visual_hook = clean_text(item.get("visual_hook", ""))
        composition = clean_text(item.get("composition", ""))
        generation_prompt = clean_text(item.get("generation_prompt", ""))
        if not visual_hook or not composition or not generation_prompt:
            continue
        concepts.append(
            {
                "concept_id": f"thumbnail_{len(concepts) + 1:02d}",
                "concept_name": clean_text(item.get("concept_name", "")),
                "visual_hook": visual_hook,
                "primary_subject": clean_text(item.get("primary_subject", "")),
                "secondary_subjects": dedupe(list(item.get("secondary_subjects") or [])),
                "composition": composition,
                "background_direction": clean_text(item.get("background_direction", "")),
                "text_overlay": clean_thumbnail_text(item.get("text_overlay", "")),
                "color_direction": clean_text(item.get("color_direction", "")),
                "emotional_tone": clean_text(item.get("emotional_tone", "")),
                "represented_story_ids": dedupe(list(item.get("represented_story_ids") or [])),
                "source_record_keys": dedupe(list(item.get("source_record_keys") or [])),
                "generation_prompt": generation_prompt,
                "avoid": dedupe(list(item.get("avoid") or [])),
            }
        )
        if len(concepts) >= limit:
            break
    return concepts


def _build_chapters(
    sections: list[dict[str, Any]],
    *,
    max_title_chars: int = 64,
) -> list[dict[str, Any]]:
    chapters = []
    elapsed = 0.0
    for section in sections:
        chapters.append(
            {
                "timestamp": format_timestamp(elapsed),
                "start_seconds": int(round(elapsed)),
                "section_id": section["section_id"],
                "title": _chapter_title(section, max_title_chars=max_title_chars),
            }
        )
        elapsed += max(1.0, float(section.get("estimated_seconds") or section.get("target_seconds") or 1))
    return chapters


def _apply_generated_chapter_titles(
    *,
    chapters: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    generated_titles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expected_ids = [clean_text(section.get("section_id", "")) for section in sections]
    title_by_section: dict[str, str] = {}
    for item in generated_titles:
        section_id = clean_text(item.get("section_id", ""))
        title = clean_text(item.get("title", ""))
        if not section_id or not title:
            raise ValueError("Metadata chapter titles require non-empty section_id and title values")
        if section_id in title_by_section:
            raise ValueError(f"Metadata returned duplicate chapter title for {section_id}")
        title_by_section[section_id] = title

    missing = [section_id for section_id in expected_ids if section_id not in title_by_section]
    unknown = sorted(set(title_by_section) - set(expected_ids))
    if missing or unknown:
        raise ValueError(f"Metadata chapter section coverage mismatch; missing={missing}, unknown={unknown}")

    return [
        {**chapter, "title": title_by_section[clean_text(chapter.get("section_id", ""))]}
        for chapter in chapters
    ]


def _chapter_title(section: dict[str, Any], *, max_title_chars: int = 64) -> str:
    section_type = clean_text(section.get("section_type", ""))
    if section_type == "intro":
        return "Intro"
    if section_type == "closing":
        return "Closing"
    title_card = section.get("title_card") or {}
    title = clean_text(
        section.get("chapter_title")
        or title_card.get("subtitle")
        or title_card.get("display_title")
        or section.get("story_title")
        or section.get("section_id")
    )
    return shorten_title(title, max_title_chars)


def _source_urls(video_packet: dict[str, Any]) -> list[str]:
    urls = []
    for story in video_packet.get("stories", []):
        for record in story.get("records", []):
            url = source_url_from_record(record)
            if url:
                urls.append(url)
    return dedupe(urls)


def _build_description(
    *,
    description_intro: str,
    chapters: list[dict[str, Any]],
    source_urls: list[str],
    channel: dict[str, Any],
) -> str:
    lines = [clean_text(description_intro), "", "Chapters:"]
    lines.extend(f"{chapter['timestamp']} {chapter['title']}" for chapter in chapters)
    if source_urls:
        lines.extend(["", "Sources:"])
        lines.extend(source_urls)
    footer = _channel_footer(channel)
    if footer:
        lines.extend(["", footer])
    return "\n".join(line for line in lines if line is not None).strip()


def _channel_footer(channel: dict[str, Any]) -> str:
    return " - ".join(
        value
        for value in (
            clean_text(channel.get("channel_name", "")),
            clean_text(channel.get("content_promise", "")),
        )
        if value
    )


def _build_tags(
    llm_tags: list[Any],
    video_packet: dict[str, Any],
    max_tags: int,
    *,
    blocked_tags: list[str] | None = None,
) -> list[str]:
    tags = [clean_tag(tag) for tag in llm_tags]
    tags.extend(["AI news", "Artificial Intelligence", "LLM"])
    for story in video_packet.get("stories", []):
        identity = story.get("story_identity") or {}
        for key in ("owning_org", "primary_entity", "product_or_project"):
            tags.append(clean_tag(identity.get(key, "")))
        for record in story.get("records", []):
            tags.append(clean_tag(record.get("source_name", "")))
    blocked = {clean_text(value).casefold() for value in (blocked_tags or []) if clean_text(value)}
    return dedupe([tag for tag in tags if tag and tag.casefold() not in blocked])[:max_tags]


def _check_metadata(metadata: dict[str, Any], sections: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    errors = []
    warnings = []
    if len(metadata.get("title_options", [])) < 3:
        errors.append("fewer than 3 usable title options")
    if len(metadata.get("thumbnail_text_options", [])) < 3:
        errors.append("fewer than 3 usable thumbnail text options")
    if not metadata.get("thumbnail_concepts"):
        errors.append("missing usable thumbnail concepts")
    if len(metadata.get("chapters", [])) != len(sections):
        errors.append("chapter count does not match script section count")
    if not clean_text(metadata.get("description_draft", "")):
        errors.append("missing description draft")
    if bool(config["metadata_policy"]["include_source_urls"]) and not metadata.get("source_urls", []):
        errors.append("missing source URLs")

    bad_urls = [
        url
        for url in metadata.get("source_urls", [])
        if not clean_text(url).startswith(("http://", "https://"))
    ]
    if bad_urls:
        errors.append(f"invalid source URLs: {bad_urls}")
    if len(metadata.get("tags", [])) < 3:
        warnings.append("fewer than 3 tags")
    chapter_title_limit = int(config["metadata_policy"].get("chapter_title_max_chars", 64))
    long_chapters = [
        chapter.get("section_id", "")
        for chapter in metadata.get("chapters", [])
        if len(clean_text(chapter.get("title", ""))) > chapter_title_limit
    ]
    if long_chapters:
        warnings.append(f"chapter titles exceed configured guidance: {long_chapters}")
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _failed_response(
    *,
    run_id: str,
    generated_at: str,
    config: dict[str, Any],
    selected_format: str,
    chapters: list[dict[str, Any]],
    source_urls: list[str],
    reason: str,
    llm_calls: list[dict[str, Any]],
) -> dict:
    metadata = {
        "title_options": [],
        "thumbnail_text_options": [],
        "thumbnail_concepts": [],
        "blocked_title_angles": [],
        "description_draft": "",
        "chapters": chapters,
        "tags": [],
        "source_urls": source_urls if bool(config.get("metadata_policy", {}).get("include_source_urls", True)) else [],
    }
    metadata_package = {
        "package_type": PACKAGE_TYPE,
        "package_stage": "draft",
        "selected_format": selected_format,
        "youtube_metadata": metadata,
        "checks": {
            "passed": False,
            "errors": [reason],
            "warnings": [],
        },
    }
    response = MetadataResponse(
        status="failed",
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": selected_format,
            "metadata_package": metadata_package,
        },
        summary=_build_summary(metadata, llm_calls, reason),
        handoff={
            "ready_for_metadata_finalization": False,
            "chapters_finalized": False,
            "ready_for_media_production": False,
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _build_summary(metadata: dict[str, Any], llm_calls: list[dict[str, Any]], failure_reason: str) -> dict[str, Any]:
    return {
        "title_option_count": len(metadata.get("title_options", [])),
        "thumbnail_option_count": len(metadata.get("thumbnail_text_options", [])),
        "thumbnail_concept_count": len(metadata.get("thumbnail_concepts", [])),
        "chapter_count": len(metadata.get("chapters", [])),
        "tag_count": len(metadata.get("tags", [])),
        "source_url_count": len(metadata.get("source_urls", [])),
        "llm_call_count": len(llm_calls),
        "provider_failover": _provider_failover_summary(llm_calls),
        "failure_reason": failure_reason,
    }


def _provider_failover_summary(llm_calls: list[dict[str, Any]]) -> dict[str, Any]:
    events = []
    for call in llm_calls:
        metadata = call.get("metadata") or {}
        if metadata.get("route_attempt") != "content_filter_fallback":
            continue
        events.append(
            {
                "module_name": call.get("module_name", ""),
                "trigger": metadata.get("fallback_trigger", "content_filter"),
                "from_provider": metadata.get("fallback_from_provider", ""),
                "from_model": metadata.get("fallback_from_model", ""),
                "to_provider": call.get("provider", ""),
                "to_model": call.get("model", ""),
            }
        )
    return {
        "content_filter_fallback_call_count": len(events),
        "events": events,
    }


def _script_sections(script_package: dict[str, Any]) -> list[dict[str, Any]]:
    sections = list(script_package.get("sections", []))
    return sorted(sections, key=lambda section: int(section.get("section_order", 0)))


def _resolve_supported_format(script_format: str, packaging_format: str, video_packet: dict[str, Any]) -> str:
    """The single format the run is in; the three signals must agree and be
    supported. Returned so the module tags its outputs and picks its prompt by
    the actual format instead of assuming roundup."""
    script_format = clean_text(script_format)
    packaging_format = clean_text(packaging_format)
    packet_format = clean_text(video_packet.get("selected_format") or video_packet.get("packet_type"))
    if not (script_format == packaging_format == packet_format):
        raise ValueError(
            "metadata_creator received mismatched formats: "
            f"script={script_format!r}, packaging={packaging_format!r}, packet={packet_format!r}."
        )
    if script_format not in SUPPORTED_FORMATS:
        raise NotImplementedError(
            f"metadata_creator does not support format {script_format!r}; "
            f"supported: {', '.join(SUPPORTED_FORMATS)}."
        )
    return script_format


def _allowed_value(value: Any, allowed: set[str], fallback: str) -> str:
    cleaned = clean_text(value)
    return cleaned if cleaned in allowed else fallback


def _recent_title_angles(config: dict[str, Any]) -> list[str]:
    recent = []
    for item in config.get("memory_context", {}).get("recent_title_angles", [])[-20:]:
        if isinstance(item, dict):
            value = item.get("title", "")
        else:
            value = item
        if clean_text(value):
            recent.append(clean_text(value))
    return recent


def _video_context(video_packet: dict[str, Any], script_package: dict[str, Any], selected_format: str) -> dict[str, Any]:
    episode_direction = script_package.get("episode_direction") if isinstance(script_package.get("episode_direction"), dict) else {}
    return {
        "selected_format": selected_format,
        "duration_policy": script_package.get("duration_policy") or video_packet.get("duration_policy") or {},
        "observed_script_duration_seconds": (script_package.get("full_script_stats") or {}).get(
            "estimated_duration_seconds", 0
        ),
        "story_count": video_packet.get("story_count", len(video_packet.get("stories", []))),
        "selected_story_ids": list(video_packet.get("selected_story_ids", [])),
        "generation_strategy": clean_text(script_package.get("generation_strategy", "")),
        "episode_shape": clean_text(episode_direction.get("episode_shape", "")),
        "episode_connection_reason": clean_text(episode_direction.get("episode_connection_reason", "")),
        "episode_thesis": clean_text(episode_direction.get("episode_thesis", "")),
        "review_revision_count": int((script_package.get("review") or {}).get("revision_count", 0) or 0),
    }


def _sections_for_prompt(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "section_id": section.get("section_id", ""),
            "section_type": section.get("section_type", ""),
            "section_order": section.get("section_order", 0),
            "story_id": section.get("story_id", ""),
            "story_title": section.get("story_title", ""),
            "role": section.get("role", ""),
            "narration_preview": clean_text(section.get("narration_text", ""))[:900],
        }
        for section in _script_sections({"sections": sections})
    ]


def _stories_for_prompt(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for story in stories:
        records = story.get("records", [])
        compact.append(
            {
                "story_id": story.get("story_id", ""),
                "story_title": story.get("story_title", ""),
                "priority_bucket": story.get("priority_bucket", ""),
                "story_identity": story.get("story_identity", {}),
                "video_segment": story.get("video_segment", {}),
                "record_titles": [clean_text(record.get("title", "")) for record in records[:6] if clean_text(record.get("title", ""))],
                "source_names": dedupe(
                    [clean_text(record.get("source_name", "")) for record in records if clean_text(record.get("source_name", ""))]
                )[:6],
            }
        )
    return compact


def _source_meaning_boundaries_for_prompt(script_package: dict[str, Any]) -> list[dict[str, Any]]:
    boundaries = []
    for packet in script_package.get("story_context_packets", []):
        if not isinstance(packet, dict):
            continue
        source_brief = packet.get("semantic_source_brief") or {}
        story_boundaries = source_brief.get("meaning_boundaries") or []
        if story_boundaries:
            boundaries.append(
                {
                    "story_id": clean_text(packet.get("story_id", "")),
                    "boundaries": story_boundaries,
                }
            )
    return boundaries


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


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


def _is_content_filter_error(exc: Exception) -> bool:
    status_code = _exception_status_code(exc)
    text = str(exc).casefold().replace("_", " ")
    markers = ("content filter", "high risk", "highrisk")
    return status_code in {400, 403} and any(marker in text for marker in markers)


def _is_structured_output_error(exc: Exception) -> bool:
    return isinstance(exc, PydanticValidationError) or type(exc).__name__ in {
        "OutputParserException",
        "ValidationError",
    }


def _retry_delay_seconds(attempt: int, retry_config: dict[str, Any]) -> float:
    initial = float(retry_config.get("initial_delay_seconds", 1.0))
    maximum = float(retry_config.get("max_delay_seconds", 10.0))
    return min(maximum, initial * (2 ** max(0, attempt - 1)))
