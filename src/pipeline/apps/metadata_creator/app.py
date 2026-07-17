from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from src.pipeline.contracts import (
    build_artifact_provenance,
    require_matching_run_id,
    validate_script_provenance,
)

from .config import METADATA_PROMPT_MODULE, PACKAGE_TYPE, SUPPORTED_FORMAT
from .contract import MetadataRequest, MetadataResponse
from .llm_client import make_llm
from .llm_logging import build_llm_call_log
from .prompt_loader import load_prompt_bundle
from .utils import clean_tag, clean_text, clean_thumbnail_text, dedupe, format_timestamp, shorten_title, source_url_from_record


IST = timezone(timedelta(hours=5, minutes=30))

TASK_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\n"
    "{user_preamble}\n\n"
    "Task payload:\n"
    "{task_payload}"
)


class TitleOptionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    accuracy_risk: Literal["low", "medium", "high"]
    click_potential: Literal["low", "medium", "medium_high", "high"]
    why_it_works: str


class MetadataDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_options: list[TitleOptionOutput]
    thumbnail_text_options: list[str]
    blocked_title_angles: list[str] = Field(default_factory=list)
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
    _validate_supported_roundup(script_generation.data.selected_format, video_packaging.data.selected_format, video_packet)

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
            selected_format=SUPPORTED_FORMAT,
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
            selected_format=SUPPORTED_FORMAT,
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
            selected_format=SUPPORTED_FORMAT,
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
            selected_format=SUPPORTED_FORMAT,
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
            selected_format=SUPPORTED_FORMAT,
            chapters=chapters,
            source_urls=source_urls,
            reason="No source URLs were available from selected story records.",
            llm_calls=llm_calls,
        )

    prompt_bundle = load_prompt_bundle(METADATA_PROMPT_MODULE, config["prompt_version"])
    llm = make_llm(
        provider=config["provider"],
        model=config["model"],
        temperature=float(config["temperature"]),
        base_url=config.get("base_url"),
    )
    draft = _generate_metadata_draft(
        script_package=script_package,
        video_packet=video_packet,
        config=config,
        prompt_bundle=prompt_bundle,
        llm=llm,
        llm_calls=llm_calls,
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
        "selected_format": SUPPORTED_FORMAT,
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
            "selected_format": SUPPORTED_FORMAT,
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
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    structured_llm = llm.with_structured_output(MetadataDraftOutput, include_raw=True)
    chain = TASK_PROMPT | structured_llm
    payload = {
        "task": "Generate YouTube metadata for the completed roundup script.",
        "channel": config["channel"],
        "metadata_policy": config["metadata_policy"],
        "recent_title_angles_to_avoid": _recent_title_angles(config),
        "video_context": _video_context(video_packet, script_package),
        "script_sections": _sections_for_prompt(script_package.get("sections", [])),
        "full_script": clean_text(script_package.get("full_script", "")),
        "selected_stories_context": _stories_for_prompt(video_packet.get("stories", [])),
        "required_output": {
            "title_options": "Use metadata_policy.title_option_count when possible.",
            "thumbnail_text_options": "Use metadata_policy.thumbnail_text_option_count when possible.",
            "description_intro": "Short description opener only. Do not include chapters or source links.",
            "tags": "Useful YouTube tags only.",
        },
    }
    return _invoke_chain(
        module_name=METADATA_PROMPT_MODULE,
        output_model=MetadataDraftOutput,
        chain=chain,
        prompt_bundle=prompt_bundle,
        task_payload=json.dumps(payload, ensure_ascii=False, indent=2),
        config=config,
        metadata={"selected_format": SUPPORTED_FORMAT, "story_count": len(video_packet.get("stories", []))},
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
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": task_payload,
    }
    rendered_prompt = TASK_PROMPT.format(**prompt_inputs)
    started = time.time()
    result = chain.invoke(prompt_inputs)
    duration = time.time() - started

    raw = result.get("raw") if isinstance(result, dict) else None
    parsed = result.get("parsed") if isinstance(result, dict) else result
    parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
    if parsing_error is not None or parsed is None:
        llm_calls.append(
            build_llm_call_log(
                module_name=module_name,
                provider=config["provider"],
                model=config["model"],
                rendered_prompt=rendered_prompt,
                raw_response=raw,
                parsed_output=None,
                metadata=metadata,
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
            provider=config["provider"],
            model=config["model"],
            rendered_prompt=rendered_prompt,
            raw_response=raw,
            parsed_output=parsed_output,
            metadata=metadata,
            duration_seconds=duration,
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
) -> list[dict[str, str]]:
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


def _chapter_title(section: dict[str, Any], *, max_title_chars: int = 64) -> str:
    section_type = clean_text(section.get("section_type", ""))
    if section_type == "intro":
        return "Intro"
    if section_type == "closing":
        return "Closing"
    title_card = section.get("title_card") or {}
    title = clean_text(
        section.get("chapter_title")
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
        "chapter_count": len(metadata.get("chapters", [])),
        "tag_count": len(metadata.get("tags", [])),
        "source_url_count": len(metadata.get("source_urls", [])),
        "llm_call_count": len(llm_calls),
        "failure_reason": failure_reason,
    }


def _script_sections(script_package: dict[str, Any]) -> list[dict[str, Any]]:
    sections = list(script_package.get("sections", []))
    return sorted(sections, key=lambda section: int(section.get("section_order", 0)))


def _validate_supported_roundup(script_format: str, packaging_format: str, video_packet: dict[str, Any]) -> None:
    packet_format = clean_text(video_packet.get("selected_format") or video_packet.get("packet_type"))
    if script_format != SUPPORTED_FORMAT or packaging_format != SUPPORTED_FORMAT or packet_format != SUPPORTED_FORMAT:
        raise NotImplementedError(
            "metadata_creator currently supports only roundup. "
            f"Received script_format={script_format!r}, packaging_format={packaging_format!r}, packet_format={packet_format!r}."
        )


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


def _video_context(video_packet: dict[str, Any], script_package: dict[str, Any]) -> dict[str, Any]:
    episode_direction = script_package.get("episode_direction") if isinstance(script_package.get("episode_direction"), dict) else {}
    return {
        "selected_format": SUPPORTED_FORMAT,
        "duration_policy": script_package.get("duration_policy") or video_packet.get("duration_policy") or {},
        "observed_script_duration_seconds": (script_package.get("full_script_stats") or {}).get(
            "estimated_duration_seconds", 0
        ),
        "story_count": video_packet.get("story_count", len(video_packet.get("stories", []))),
        "selected_story_ids": list(video_packet.get("selected_story_ids", [])),
        "generation_strategy": clean_text(script_package.get("generation_strategy", "")),
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


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
