from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from src.pipeline.contracts import (
    build_text_script_provenance,
    require_matching_run_id,
    validate_script_provenance,
)

from .providers.kokoro_local import concatenate_wav_files
from .text_chunks import split_narration_into_chunks, word_count


def resolve_script_input(request, chunking: dict[str, Any]) -> dict[str, Any]:
    if request.input.script_text is not None and request.input.script_text.strip():
        text = request.input.script_text.strip()
        return {
            "text": text,
            "source": request.input.script_source or "input.script_text",
            "sections": [],
            "chunks": split_narration_into_chunks(text, **chunking),
            "alignment_strategy": "manual_text_chunks",
            "provenance": build_text_script_provenance(
                text,
                run_id=request.run.run_id,
                script_source=request.input.script_source or "input.script_text",
            ),
        }

    script_generation = request.input.script_generation
    if script_generation is None:
        raise ValueError("input.script_generation or input.script_text is required")
    if script_generation.status != "ok":
        raise ValueError("input.script_generation.status must be ok before voiceover generation")
    package = script_generation.data.script_package
    require_matching_run_id(request.run.run_id, script_generation.data.run_id, "script_generation")
    provenance = validate_script_provenance(
        package,
        run_id=request.run.run_id,
        upstream_run_id=script_generation.data.run_id,
    )
    sections = package.get("sections")
    if not isinstance(sections, list) or not sections:
        raise KeyError("script_generation.data.script_package.sections is missing or empty")
    section_texts = []
    for section in sections:
        beats = section.get("beats") if isinstance(section, dict) else None
        if isinstance(beats, list) and beats:
            section_text = " ".join(str(beat.get("narration_text", "")).strip() for beat in beats).strip()
        else:
            section_text = str(section.get("narration_text", "")).strip() if isinstance(section, dict) else ""
        if not section_text:
            raise KeyError(f"{section.get('section_id', '<unknown>')} has no usable narration beats")
        section_texts.append(section_text)
    full_script = "\n\n".join(section_texts).strip()
    projected_full_script = str(package.get("full_script", "")).strip()
    if projected_full_script and projected_full_script != full_script:
        raise ValueError("script_package.full_script does not match the deterministic section/beat projection")
    chunks = _beat_chunks(
        sections=sections,
        chunking=chunking,
        beat_pause_seconds=float(request.config.alignment.beat_pause_seconds),
        section_pause_seconds=float(request.config.alignment.section_pause_seconds),
        require_script_beats=bool(request.config.alignment.require_script_beats),
    )
    return {
        "text": full_script,
        "source": "script_generation.data.script_package.sections[].beats",
        "sections": sections,
        "chunks": chunks,
        "alignment_strategy": "script_beats",
        "provenance": provenance,
    }


def build_audio_units(
    *,
    synthesized_chunks: list[dict[str, Any]],
    output_dir: Path,
    sample_rate_hz: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for chunk in synthesized_chunks:
        unit_id = str(chunk.get("audio_unit_id") or "audio_manual_script")
        if unit_id not in grouped:
            order.append(unit_id)
        grouped[unit_id].append(chunk)

    units: list[dict[str, Any]] = []
    for unit_order, unit_id in enumerate(order, start=1):
        chunks = grouped[unit_id]
        unit_path = output_dir / f"{unit_id}.wav"
        duration = concatenate_wav_files(
            input_paths=[Path(chunk["audio_path"]) for chunk in chunks],
            output_path=unit_path,
            sample_rate_hz=sample_rate_hz,
            pauses_after_seconds=[
                float(chunk.get("pause_after_seconds", 0.0)) if index < len(chunks) - 1 else 0.0
                for index, chunk in enumerate(chunks)
            ],
        )
        units.append(
            {
                "audio_unit_id": unit_id,
                "unit_order": unit_order,
                "section_id": str(chunks[0].get("section_id", "")),
                "section_type": str(chunks[0].get("section_type", "")),
                "story_id": str(chunks[0].get("story_id", "")),
                "story_title": str(chunks[0].get("story_title", "")),
                "audio_path": str(unit_path),
                "start_seconds": float(chunks[0].get("start_seconds", 0.0)),
                "speech_end_seconds": float(chunks[-1].get("end_seconds", 0.0)),
                "duration_seconds": round(duration, 2),
                "word_count": sum(int(chunk.get("word_count", 0) or 0) for chunk in chunks),
                "aligned_beats": _aligned_beats(chunks),
            }
        )

    for index, unit in enumerate(units):
        if index + 1 < len(units):
            timeline_end = float(units[index + 1]["start_seconds"])
        else:
            timeline_end = float(unit["speech_end_seconds"])
        unit["end_seconds"] = round(timeline_end, 2)
        unit["timeline_duration_seconds"] = round(timeline_end - float(unit["start_seconds"]), 2)
        beats = unit["aligned_beats"]
        for beat_index, beat in enumerate(beats):
            beat_end = (
                float(beats[beat_index + 1]["start_seconds"])
                if beat_index + 1 < len(beats)
                else timeline_end
            )
            beat["end_seconds"] = round(beat_end, 2)
            beat["duration_seconds"] = round(beat_end - float(beat["start_seconds"]), 2)
    return units


def _beat_chunks(
    *,
    sections: list[dict[str, Any]],
    chunking: dict[str, Any],
    beat_pause_seconds: float,
    section_pause_seconds: float,
    require_script_beats: bool,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections):
        beats = section.get("beats")
        if not isinstance(beats, list) or not beats:
            if require_script_beats:
                raise KeyError(f"{section.get('section_id', '<unknown>')} is missing canonical script beats")
            beats = [
                {
                    "beat_id": f"{section.get('section_id', 'section')}_beat_01",
                    "beat_order": 1,
                    "beat_type": section.get("section_type", "story"),
                    "narration_text": section.get("narration_text", ""),
                }
            ]
        for beat_index, beat in enumerate(beats):
            beat_text = str(beat.get("narration_text", "")).strip()
            if not beat_text:
                raise ValueError(f"{beat.get('beat_id', '<unknown>')} narration is empty")
            provider_parts = split_narration_into_chunks(beat_text, **chunking)
            if not provider_parts:
                raise ValueError(f"{beat.get('beat_id', '<unknown>')} produced no provider chunks")
            for part_index, part in enumerate(provider_parts, start=1):
                is_last_part = part_index == len(provider_parts)
                is_last_beat = beat_index == len(beats) - 1
                is_last_section = section_index == len(sections) - 1
                if not is_last_part:
                    pause = float(chunking["chunk_pause_seconds"])
                elif not is_last_beat:
                    pause = beat_pause_seconds
                elif not is_last_section:
                    pause = section_pause_seconds
                else:
                    pause = 0.0
                chunks.append(
                    {
                        **part,
                        "chunk_id": f"chunk_{len(chunks) + 1:03d}",
                        "order": len(chunks) + 1,
                        "audio_unit_id": f"audio_{section['section_id']}",
                        "section_id": section["section_id"],
                        "section_type": section.get("section_type", ""),
                        "story_id": section.get("story_id", ""),
                        "story_title": section.get("story_title", ""),
                        "beat_id": beat.get("beat_id", ""),
                        "beat_order": int(beat.get("beat_order", beat_index + 1)),
                        "beat_type": beat.get("beat_type", ""),
                        "provider_part_order": part_index,
                        "pause_after_seconds": round(pause, 2),
                        "prosody_reason": (
                            "provider_split" if not is_last_part else "beat_boundary" if not is_last_beat else "section_boundary"
                        ),
                    }
                )
    return chunks


def _aligned_beats(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for chunk in chunks:
        beat_id = str(chunk.get("beat_id") or chunk.get("chunk_id"))
        if beat_id not in grouped:
            order.append(beat_id)
        grouped[beat_id].append(chunk)
    output: list[dict[str, Any]] = []
    for beat_id in order:
        parts = grouped[beat_id]
        text = " ".join(str(part.get("text", "")).strip() for part in parts).strip()
        output.append(
            {
                "beat_id": beat_id,
                "beat_order": int(parts[0].get("beat_order", len(output) + 1)),
                "beat_type": str(parts[0].get("beat_type", "")),
                "section_id": str(parts[0].get("section_id", "")),
                "story_id": str(parts[0].get("story_id", "")),
                "text": text,
                "word_count": word_count(text),
                "start_seconds": round(float(parts[0].get("start_seconds", 0.0)), 2),
                "speech_end_seconds": round(float(parts[-1].get("end_seconds", 0.0)), 2),
                "provider_chunk_ids": [str(part.get("chunk_id", "")) for part in parts],
            }
        )
    return output
