from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from typing import Any

from langchain_core.prompts import PromptTemplate

from src.pipeline.contracts import (
    artifact_fingerprint,
    build_artifact_provenance,
    require_matching_run_id,
    validate_script_provenance,
)

from ..common import clean_text, dedupe, iso_now
from .config import NEXT_MODULE, PACKAGE_TYPE, RESEARCH_VERSION
from .contract import (
    StoryVisualResearchDraft,
    VisualResearchRequest,
    VisualResearchResponse,
    visual_research_identity_payload,
)
from .llm_client import make_llm
from .llm_logging import build_llm_call_log
from .prompt_loader import load_prompt_bundle


TASK_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\n{user_preamble}\n\nTask payload:\n{task_payload}"
)


def run(input_json: dict) -> dict:
    request = VisualResearchRequest.model_validate(input_json)
    run_id = request.run.run_id
    generated_at = iso_now()
    config = request.config.model_dump(mode="json")
    script_result = request.input.script_generation
    packaging_result = request.input.video_packaging

    require_matching_run_id(run_id, script_result.data.run_id, "script_generation")
    require_matching_run_id(run_id, packaging_result.data.run_id, "video_packaging")
    if clean_text(packaging_result.data.selected_format) != "roundup":
        raise ValueError("visual research currently supports selected_format='roundup' only")

    script_package = script_result.data.script_package
    script_provenance = validate_script_provenance(
        script_package,
        run_id=run_id,
        upstream_run_id=script_result.data.run_id,
    )
    stories = _selected_stories(packaging_result.data.video_packet)
    sections = _story_sections(script_package)
    missing_sections = [
        clean_text(story.get("story_id"))
        for story in stories
        if clean_text(story.get("story_id")) not in sections
    ]
    if missing_sections:
        raise ValueError(f"script package is missing selected story sections: {missing_sections}")

    prompt_bundle = load_prompt_bundle(config["prompt_version"])
    llm = make_llm(
        provider=config["provider"],
        model=config["model"],
        temperature=float(config["temperature"]),
        base_url=config.get("base_url"),
        provider_options=config.get("provider_options"),
    )
    results: dict[str, dict[str, Any]] = {}
    calls_by_story: dict[str, list[dict[str, Any]]] = {}
    failures: dict[str, str] = {}
    worker_count = min(int(config["worker_count"]), len(stories))

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _research_story,
                story=story,
                section=sections[clean_text(story.get("story_id"))],
                config=config,
                prompt_bundle=prompt_bundle,
                llm=llm,
            ): clean_text(story.get("story_id"))
            for story in stories
        }
        for future in as_completed(futures):
            story_id = futures[future]
            try:
                result, call_logs = future.result()
                results[story_id] = result
                calls_by_story[story_id] = call_logs
            except Exception as exc:
                failures[story_id] = f"{type(exc).__name__}: {exc}"

    ordered_story_ids = [clean_text(story.get("story_id")) for story in stories]
    llm_calls = [
        call
        for story_id in ordered_story_ids
        for call in calls_by_story.get(story_id, [])
    ]
    story_research = [results[story_id] for story_id in ordered_story_ids if story_id in results]
    package = {
        "package_type": PACKAGE_TYPE,
        "research_version": RESEARCH_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "research_strategy": "one_complete_story_call_per_selected_story",
        "source_policy": {
            "selected_stories_only": True,
            "full_story_records_in_prompt": True,
            "external_search_enabled": bool(config["external_search_enabled"]),
        },
        "active_render_kinds": list(config["active_render_kinds"]),
        "story_research": story_research,
        "failed_story_ids": list(failures),
    }
    package["provenance"] = build_artifact_provenance(
        artifact_type="visual_research",
        run_id=run_id,
        parents={"script": script_provenance["script_fingerprint"]},
        script_source=script_provenance.get("script_source", ""),
        payload=visual_research_identity_payload(package),
    )

    status = "failed" if failures else "ok"
    failure_reason = (
        "Visual research failed for story section(s): "
        f"{list(failures)}"
        if failures
        else ""
    )
    summary = {
        "story_count": len(stories),
        "researched_story_count": len(story_research),
        "failed_story_count": len(failures),
        "asset_need_count": sum(len(item.get("asset_needs", [])) for item in story_research),
        "sequence_note_count": sum(len(item.get("sequence_notes", [])) for item in story_research),
        "unresolved_gap_count": sum(len(item.get("unresolved_gaps", [])) for item in story_research),
        "llm_call_count": len(llm_calls),
        "failure_reason": failure_reason,
        "story_failures": failures,
    }
    response = VisualResearchResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "visual_research_package": package,
        },
        summary=summary,
        handoff={
            "ready_for_asset_catalog": status == "ok",
            "next_module": NEXT_MODULE,
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _research_story(
    *,
    story: dict[str, Any],
    section: dict[str, Any],
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    story_id = clean_text(story.get("story_id"))
    beat_ids = [
        clean_text(beat.get("beat_id"))
        for beat in section.get("beats", [])
        if isinstance(beat, dict) and clean_text(beat.get("beat_id"))
    ]
    record_keys = [
        clean_text(record.get("record_key"))
        for record in story.get("records", [])
        if isinstance(record, dict) and clean_text(record.get("record_key"))
    ]
    payload = {
        "task": "Research the concrete visual material needed to tell this one roundup story.",
        "story": story,
        "canonical_script_section": section,
        "canonical_beat_ids": beat_ids,
        "selected_source_record_keys": record_keys,
        "active_render_kinds": config["active_render_kinds"],
        "collectable_asset_types": config["collectable_asset_types"],
        "external_search_enabled": bool(config["external_search_enabled"]),
        "required_behavior": {
            "use_complete_story_context": True,
            "plan_asset_needs_not_final_scenes": True,
            "use_only_supplied_beat_ids": True,
            "use_only_supplied_record_keys": True,
            "do_not_author_timestamps_or_asset_ids": True,
            "do_not_substitute_generic_ai_stock_media": True,
            "treat_sequence_as_two_to_four_adjacent_short_shots": True,
        },
    }
    last_error = ""
    call_logs: list[dict[str, Any]] = []
    chain = TASK_PROMPT | _structured_llm(llm, StoryVisualResearchDraft, config)
    for attempt in range(1, int(config["max_attempts"]) + 1):
        attempt_payload = dict(payload)
        if last_error:
            attempt_payload["repair_context"] = {
                "previous_error": last_error,
                "instruction": (
                    "Return a complete corrected result using only the supplied story ID, "
                    "beat IDs, record keys, and asset types."
                ),
            }
        rendered = TASK_PROMPT.format(
            system_prompt=prompt_bundle["system"],
            user_preamble=prompt_bundle["user_preamble"],
            task_payload=json.dumps(attempt_payload, ensure_ascii=False, indent=2),
        )
        started = time.monotonic()
        raw = None
        parsed_output: dict[str, Any] | None = None
        parse_error = ""
        try:
            result = chain.invoke(
                {
                    "system_prompt": prompt_bundle["system"],
                    "user_preamble": prompt_bundle["user_preamble"],
                    "task_payload": json.dumps(attempt_payload, ensure_ascii=False, indent=2),
                }
            )
            if isinstance(result, dict) and "parsed" in result:
                raw = result.get("raw")
                parsed = result.get("parsed")
                parsing_error = result.get("parsing_error")
                if parsing_error:
                    raise ValueError(f"structured output parse failed: {parsing_error}")
            else:
                parsed = result
                raw = result
            parsed_output = (
                parsed.model_dump(mode="json")
                if hasattr(parsed, "model_dump")
                else dict(parsed)
                if isinstance(parsed, dict)
                else None
            )
            if parsed_output is None:
                raise ValueError("structured output did not return a parsed object")
            errors = _research_errors(
                parsed_output,
                story_id=story_id,
                beat_ids=set(beat_ids),
                record_keys=set(record_keys),
                asset_types=set(config["collectable_asset_types"]),
            )
            if errors:
                raise ValueError("; ".join(errors))
            parsed_output = _with_stable_need_ids(parsed_output, story_id=story_id)
            call_logs.append(
                build_llm_call_log(
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered,
                    raw_response=raw,
                    parsed_output=parsed_output,
                    metadata={"story_id": story_id, "attempt": attempt},
                    duration_seconds=time.monotonic() - started,
                )
            )
            return parsed_output, call_logs
        except Exception as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
            call_logs.append(
                build_llm_call_log(
                    provider=config["provider"],
                    model=config["model"],
                    rendered_prompt=rendered,
                    raw_response=raw,
                    parsed_output=parsed_output,
                    metadata={"story_id": story_id, "attempt": attempt},
                    duration_seconds=time.monotonic() - started,
                    parse_error=parse_error,
                )
            )
            last_error = parse_error
    raise RuntimeError(
        f"story visual research failed after {config['max_attempts']} bounded attempt(s): {last_error}"
    )


def _structured_llm(llm, output_model, config: dict[str, Any]):
    structured = dict(config.get("structured_output") or {})
    kwargs: dict[str, Any] = {"include_raw": True}
    if config["provider"] in {"openai", "lmstudio", "moonshot"}:
        kwargs["method"] = structured.get("method", "json_schema")
        if kwargs["method"] != "json_mode":
            kwargs["strict"] = bool(structured.get("strict", True))
    return llm.with_structured_output(output_model, **kwargs)


def _research_errors(
    result: dict[str, Any],
    *,
    story_id: str,
    beat_ids: set[str],
    record_keys: set[str],
    asset_types: set[str],
) -> list[str]:
    errors: list[str] = []
    if clean_text(result.get("story_id")) != story_id:
        errors.append(f"story_id must be {story_id!r}")
    if not result.get("asset_needs"):
        errors.append("asset_needs must not be empty")
    for index, need in enumerate(result.get("asset_needs", []), start=1):
        if not isinstance(need, dict):
            errors.append(f"asset_needs[{index}] must be an object")
            continue
        unknown_beats = sorted(set(need.get("beat_ids", [])) - beat_ids)
        unknown_records = sorted(set(need.get("preferred_source_record_keys", [])) - record_keys)
        unknown_types = sorted(set(need.get("preferred_asset_types", [])) - asset_types)
        if unknown_beats:
            errors.append(f"asset_needs[{index}] contains unknown beat IDs: {unknown_beats}")
        if unknown_records:
            errors.append(f"asset_needs[{index}] contains unknown record keys: {unknown_records}")
        if unknown_types:
            errors.append(f"asset_needs[{index}] contains unsupported asset types: {unknown_types}")
    for index, sequence in enumerate(result.get("sequence_notes", []), start=1):
        if not isinstance(sequence, dict):
            errors.append(f"sequence_notes[{index}] must be an object")
            continue
        unknown_beats = sorted(set(sequence.get("beat_ids", [])) - beat_ids)
        if unknown_beats:
            errors.append(f"sequence_notes[{index}] contains unknown beat IDs: {unknown_beats}")
    return errors


def _with_stable_need_ids(result: dict[str, Any], *, story_id: str) -> dict[str, Any]:
    normalized = dict(result)
    normalized["story_id"] = story_id
    needs = []
    for order, raw_need in enumerate(result.get("asset_needs", []), start=1):
        need = dict(raw_need)
        need["asset_need_id"] = "visual_need_" + artifact_fingerprint(
            {
                "story_id": story_id,
                "order": order,
                "beat_ids": need.get("beat_ids", []),
                "subject": clean_text(need.get("subject")),
                "asset_types": need.get("preferred_asset_types", []),
            }
        ).removeprefix("sha256:")[:14]
        need["asset_need_order"] = order
        needs.append(need)
    normalized["asset_needs"] = needs
    return normalized


def _selected_stories(video_packet: dict[str, Any]) -> list[dict[str, Any]]:
    stories = video_packet.get("stories") or video_packet.get("selected_stories")
    if not isinstance(stories, list) or not stories:
        raise ValueError("video_packet.stories must be a non-empty list")
    return [story for story in stories if isinstance(story, dict)]


def _story_sections(script_package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sections = script_package.get("sections")
    if not isinstance(sections, list):
        raise ValueError("script_package.sections must be a list")
    return {
        clean_text(section.get("story_id")): section
        for section in sections
        if isinstance(section, dict)
        and clean_text(section.get("section_type")) == "story"
        and clean_text(section.get("story_id"))
    }
