from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
) -> dict:
    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_type": "voiceover_package",
        "status": "ready",
        "provider": provider,
        "voice": voice,
        "style": style,
        "audio": {
            "format": "wav",
            "sample_rate_hz": sample_rate_hz,
            "full_audio_path": _portable_path(full_audio_path),
            "duration_seconds": round(duration_seconds, 2),
        },
        "input_script": {
            "source": script_source,
            "word_count": script_word_count,
            "estimated_script_seconds": estimated_script_seconds,
        },
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
        "word_count": package["input_script"]["word_count"],
        "ready_for_video_assembly": package["handoff"]["ready_for_video_assembly"],
        "requires_manual_audio_review": package["handoff"]["requires_manual_audio_review"],
    }


def _portable_chunk_paths(chunk: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(chunk)
    audio_path = normalized.get("audio_path")
    if audio_path:
        normalized["audio_path"] = _portable_path(Path(audio_path))
    return normalized


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)
