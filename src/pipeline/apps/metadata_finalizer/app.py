from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.pipeline.contracts import (
    build_artifact_provenance,
    require_matching_run_id,
    require_parent_fingerprint,
    validate_artifact_provenance,
    validate_script_provenance,
    voiceover_artifact_payload,
)
from .config import PACKAGE_TYPE, SUPPORTED_FORMAT
from .contract import MetadataFinalizerRequest, MetadataFinalizerResponse
from .utils import clean_text, format_timestamp, iso_now


def run(input_json: dict) -> dict:
    request = MetadataFinalizerRequest.model_validate(input_json)
    run_id = request.run.run_id
    generated_at = iso_now()

    script_result = request.input.script_generation
    metadata_result = request.input.metadata_creator
    voiceover_package = _voiceover_package(request.input.voiceover)
    _require_ok(script_result, "script_generation")
    _require_ok(metadata_result, "metadata_creator")

    script_data = script_result.get("data") or {}
    metadata_data = metadata_result.get("data") or {}
    script_package = script_data.get("script_package") or {}
    metadata_package = metadata_data.get("metadata_package") or {}
    require_matching_run_id(run_id, script_data.get("run_id"), "script_generation")
    require_matching_run_id(run_id, metadata_data.get("run_id"), "metadata_creator")
    require_matching_run_id(run_id, voiceover_package.get("run_id"), "voiceover")

    script_provenance = validate_script_provenance(
        script_package,
        run_id=run_id,
        upstream_run_id=script_data.get("run_id"),
    )
    script_fingerprint = script_provenance["script_fingerprint"]
    validate_artifact_provenance(
        metadata_package.get("provenance"),
        artifact_type="metadata_draft",
        run_id=run_id,
        payload=metadata_package.get("youtube_metadata") or {},
        label="metadata_creator",
    )
    require_parent_fingerprint(
        metadata_package.get("provenance"),
        parent_name="script",
        expected=script_fingerprint,
        label="metadata_creator",
    )
    validate_artifact_provenance(
        voiceover_package.get("provenance"),
        artifact_type="voiceover",
        run_id=run_id,
        payload=voiceover_artifact_payload(voiceover_package),
        label="voiceover",
    )
    require_parent_fingerprint(
        voiceover_package.get("provenance"),
        parent_name="script",
        expected=script_fingerprint,
        label="voiceover",
    )
    if voiceover_package.get("status") != "ready":
        raise ValueError("voiceover package status must be ready")

    sections = _ordered_sections(script_package)
    audio_units = _ordered_audio_units(voiceover_package)
    chapters = _chapters_from_audio_units(
        sections,
        audio_units,
        require_all=request.config.require_all_script_sections,
    )
    errors = _chapter_errors(
        sections,
        chapters,
        first_tolerance=request.config.first_chapter_tolerance_seconds,
    )

    youtube_metadata = deepcopy(metadata_package.get("youtube_metadata") or {})
    components = youtube_metadata.get("description_components")
    if not isinstance(components, dict):
        errors.append("metadata draft is missing description_components")
        components = {}
    youtube_metadata["chapters"] = chapters
    youtube_metadata["description_draft"] = _build_description(
        intro=clean_text(components.get("intro")),
        chapters=chapters,
        source_urls=list(youtube_metadata.get("source_urls") or []),
        footer=clean_text(components.get("channel_footer")),
        include_source_urls=bool(components.get("include_source_urls", True)),
    )
    metadata_basis = dict(youtube_metadata.get("metadata_basis") or {})
    metadata_basis.update(
        {
            "chapter_timing_source": "voiceover_audio_units",
            "chapters_finalized": not errors,
            "voiceover_duration_seconds": float((voiceover_package.get("audio") or {}).get("duration_seconds", 0) or 0),
        }
    )
    youtube_metadata["metadata_basis"] = metadata_basis

    status = "ok" if not errors else "failed"
    checks = {
        "passed": not errors,
        "errors": errors,
        "warnings": [],
    }
    final_package = {
        "package_type": PACKAGE_TYPE,
        "package_stage": "final",
        "selected_format": SUPPORTED_FORMAT,
        "youtube_metadata": youtube_metadata,
        "checks": checks,
    }
    voiceover_fingerprint = voiceover_package["provenance"]["voiceover_fingerprint"]
    final_package["provenance"] = build_artifact_provenance(
        artifact_type="metadata_final",
        run_id=run_id,
        parents={
            "script": script_fingerprint,
            "voiceover": voiceover_fingerprint,
            "metadata_draft": metadata_package["provenance"]["artifact_fingerprint"],
        },
        script_source=script_provenance.get("script_source", ""),
        payload=youtube_metadata,
    )
    response = MetadataFinalizerResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": SUPPORTED_FORMAT,
            "metadata_package": final_package,
        },
        summary={
            "chapter_count": len(chapters),
            "audio_unit_count": len(audio_units),
            "chapters_finalized": status == "ok",
            "timing_source": "voiceover_audio_units",
            "failure_reason": "; ".join(errors),
        },
        handoff={
            "ready_for_media_production": status == "ok",
            "ready_for_publish_review": status == "ok",
            "chapters_finalized": status == "ok",
        },
    )
    return response.model_dump(mode="json")


def _require_ok(envelope: dict[str, Any], label: str) -> None:
    if envelope.get("status") != "ok":
        raise ValueError(f"input.{label}.status must be ok")


def _voiceover_package(value: dict[str, Any]) -> dict[str, Any]:
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    if isinstance(data.get("voiceover_package"), dict):
        return data["voiceover_package"]
    if isinstance(value.get("voiceover_package"), dict):
        return value["voiceover_package"]
    return value


def _ordered_sections(script_package: dict[str, Any]) -> list[dict[str, Any]]:
    sections = script_package.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("script_package.sections is missing or empty")
    return sorted(
        (section for section in sections if isinstance(section, dict)),
        key=lambda section: int(section.get("section_order", 0) or 0),
    )


def _ordered_audio_units(voiceover_package: dict[str, Any]) -> list[dict[str, Any]]:
    units = voiceover_package.get("audio_units")
    if not isinstance(units, list) or not units:
        raise ValueError("voiceover.audio_units is missing or empty")
    return sorted(
        (unit for unit in units if isinstance(unit, dict)),
        key=lambda unit: int(unit.get("unit_order", 0) or 0),
    )


def _chapters_from_audio_units(
    sections: list[dict[str, Any]],
    audio_units: list[dict[str, Any]],
    *,
    require_all: bool,
) -> list[dict[str, Any]]:
    units_by_section = {clean_text(unit.get("section_id")): unit for unit in audio_units}
    chapters: list[dict[str, Any]] = []
    for section in sections:
        section_id = clean_text(section.get("section_id"))
        unit = units_by_section.get(section_id)
        if unit is None:
            if require_all:
                raise ValueError(f"voiceover is missing an audio unit for {section_id}")
            continue
        start = float(unit.get("start_seconds", 0) or 0)
        chapters.append(
            {
                "timestamp": format_timestamp(start),
                "start_seconds": round(start, 2),
                "section_id": section_id,
                "title": _chapter_title(section),
            }
        )
    return chapters


def _chapter_title(section: dict[str, Any]) -> str:
    section_type = clean_text(section.get("section_type"))
    if section_type == "intro":
        return "Intro"
    if section_type == "closing":
        return "Closing"
    title = clean_text(
        section.get("chapter_title")
        or section.get("story_title")
        or section.get("section_id")
    )
    if len(title) <= 64:
        return title
    words: list[str] = []
    for word in title.split():
        candidate = " ".join([*words, word])
        if len(candidate) > 63:
            break
        words.append(word)
    return f"{' '.join(words)}…" if words else title


def _chapter_errors(
    sections: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
    *,
    first_tolerance: float,
) -> list[str]:
    errors: list[str] = []
    if len(chapters) != len(sections):
        errors.append("chapter count does not match script section count")
    starts = [float(chapter.get("start_seconds", 0) or 0) for chapter in chapters]
    if starts and abs(starts[0]) > first_tolerance:
        errors.append(f"first chapter must start near 0 seconds, got {starts[0]:.2f}")
    if any(right <= left for left, right in zip(starts, starts[1:])):
        errors.append("chapter start times must be strictly increasing")
    return errors


def _build_description(
    *,
    intro: str,
    chapters: list[dict[str, Any]],
    source_urls: list[str],
    footer: str,
    include_source_urls: bool,
) -> str:
    if not intro:
        raise ValueError("metadata description intro is empty")
    lines = [intro, "", "Chapters:"]
    lines.extend(f"{chapter['timestamp']} {chapter['title']}" for chapter in chapters)
    if include_source_urls and source_urls:
        lines.extend(["", "Sources:"])
        lines.extend(clean_text(url) for url in source_urls if clean_text(url))
    if footer:
        lines.extend(["", footer])
    return "\n".join(lines).strip()
