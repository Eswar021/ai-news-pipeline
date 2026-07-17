from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.pipeline.contracts import build_artifact_provenance, voiceover_artifact_payload


def build_voiceover_package(
    *,
    run_id: str,
    provider: str,
    voice: str,
    style: dict,
    sample_rate_hz: int,
    full_audio_path: Path,
    duration_seconds: float,
    script_source: str,
    script_word_count: int,
    estimated_script_seconds: float,
    chunks: list[dict[str, Any]],
    audio_units: list[dict[str, Any]],
    alignment_strategy: str,
    script_provenance: dict[str, Any],
    audio_sha256: str,
    mastering: dict[str, Any] | None = None,
    captions: dict[str, Any] | None = None,
) -> dict:
    mastering = _portable_mastering_paths(dict(mastering or {}))
    captions = _portable_caption_paths(dict(captions or {}))
    identity_package = {
        "provider": provider,
        "voice": voice,
        "style": style,
        "audio": {
            "sample_rate_hz": sample_rate_hz,
            "duration_seconds": round(duration_seconds, 2),
            "mastering": mastering,
        },
        "captions": captions,
        "audio_units": [_identity_audio_unit(unit) for unit in audio_units],
        "provenance": {"audio_sha256": audio_sha256},
    }
    provenance = build_artifact_provenance(
        artifact_type="voiceover",
        run_id=run_id,
        parents={"script": script_provenance["script_fingerprint"]},
        script_source=str(script_provenance.get("script_source", "")),
        payload=voiceover_artifact_payload(identity_package),
    )
    provenance["audio_sha256"] = audio_sha256
    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_type": "voiceover_package",
        "status": "ready",
        "provenance": provenance,
        "provider": provider,
        "voice": voice,
        "style": style,
        "audio": {
            "format": "wav",
            "sample_rate_hz": sample_rate_hz,
            "full_audio_path": _portable_path(full_audio_path),
            "duration_seconds": round(duration_seconds, 2),
            "mastering": mastering,
        },
        "captions": captions,
        "input_script": {
            "source": script_source,
            "word_count": script_word_count,
            "estimated_script_seconds": estimated_script_seconds,
            "script_source": script_provenance.get("script_source", script_source),
            "script_fingerprint": script_provenance["script_fingerprint"],
            "contract_version": script_provenance.get("contract_version", ""),
        },
        "alignment": {
            "strategy": alignment_strategy,
            "section_aware": alignment_strategy == "script_beats",
            "beat_aware": alignment_strategy == "script_beats",
        },
        "audio_units": [_portable_audio_unit_paths(unit) for unit in audio_units],
        "chunks": [_portable_chunk_paths(chunk) for chunk in chunks],
        "handoff": {
            "ready_for_video_assembly": True,
            "requires_manual_audio_review": True,
        },
    }


def build_summary(package: dict) -> dict:
    return {
        "run_id": package["run_id"],
        "status": package["status"],
        "provider": package["provider"],
        "voice": package["voice"],
        "style": package.get("style", {}).get("name", ""),
        "audio_path": package["audio"]["full_audio_path"],
        "duration_seconds": package["audio"]["duration_seconds"],
        "chunk_count": len(package.get("chunks", [])),
        "audio_unit_count": len(package.get("audio_units", [])),
        "aligned_beat_count": sum(len(unit.get("aligned_beats", [])) for unit in package.get("audio_units", [])),
        "word_count": package["input_script"]["word_count"],
        "script_source": package["input_script"].get("script_source", package["input_script"].get("source", "")),
        "script_fingerprint": package.get("provenance", {}).get("script_fingerprint", ""),
        "voiceover_fingerprint": package.get("provenance", {}).get("voiceover_fingerprint", ""),
        "ready_for_video_assembly": package["handoff"]["ready_for_video_assembly"],
        "requires_manual_audio_review": package["handoff"]["requires_manual_audio_review"],
        "mastering_status": (package.get("audio", {}).get("mastering") or {}).get("status", ""),
        "caption_file_count": len((package.get("captions") or {}).get("files", [])),
        "caption_cue_count": int((package.get("captions") or {}).get("cue_count", 0) or 0),
    }


def _portable_chunk_paths(chunk: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(chunk)
    audio_path = normalized.get("audio_path")
    if audio_path:
        normalized["audio_path"] = _portable_path(Path(audio_path))
    return normalized


def _portable_audio_unit_paths(unit: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(unit)
    audio_path = normalized.get("audio_path")
    if audio_path:
        normalized["audio_path"] = _portable_path(Path(audio_path))
    return normalized


def _portable_caption_paths(captions: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(captions)
    files = []
    for item in normalized.get("files", []):
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        if next_item.get("path"):
            next_item["path"] = _portable_path(Path(next_item["path"]))
        files.append(next_item)
    normalized["files"] = files
    return normalized


def _portable_mastering_paths(mastering: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(mastering)
    for key in ("input_path", "output_path"):
        if normalized.get(key):
            normalized[key] = _portable_path(Path(normalized[key]))
    return normalized


def _identity_audio_unit(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "audio_unit_id": unit.get("audio_unit_id", ""),
        "unit_order": unit.get("unit_order", 0),
        "section_id": unit.get("section_id", ""),
        "story_id": unit.get("story_id", ""),
        "start_seconds": unit.get("start_seconds", 0),
        "end_seconds": unit.get("end_seconds", 0),
        "aligned_beats": [
            {
                "beat_id": beat.get("beat_id", ""),
                "beat_order": beat.get("beat_order", 0),
                "text": beat.get("text", ""),
                "start_seconds": beat.get("start_seconds", 0),
                "end_seconds": beat.get("end_seconds", 0),
            }
            for beat in unit.get("aligned_beats", [])
            if isinstance(beat, dict)
        ],
    }


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)
