from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def build_request_record(
    *,
    provider: str,
    model: str,
    voice: str,
    chunk: dict[str, Any],
    effective_instructions: str,
    direction_applied: bool,
    attempt_count: int,
    latency_seconds: float,
    audio_path: Path,
) -> dict[str, Any]:
    transcript = str(chunk.get("text") or "")
    instructions = effective_instructions.strip()
    chunk_id = str(chunk.get("chunk_id") or "chunk")
    identity = "\n".join((provider, model, voice, chunk_id, transcript, instructions))
    return {
        "request_id": f"tts_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
        "chunk_id": chunk_id,
        "audio_unit_id": str(chunk.get("audio_unit_id") or ""),
        "section_id": str(chunk.get("section_id") or ""),
        "story_id": str(chunk.get("story_id") or ""),
        "beat_id": str(chunk.get("beat_id") or ""),
        "beat_order": int(chunk.get("beat_order") or 0),
        "beat_type": str(chunk.get("beat_type") or ""),
        "beat_function": str(chunk.get("beat_function") or ""),
        "provider": provider,
        "model": model,
        "voice": voice,
        "transcript": transcript,
        "transcript_sha256": _text_sha256(transcript),
        "effective_instructions": instructions,
        "instructions_sha256": _text_sha256(instructions),
        "delivery_direction": dict(chunk.get("delivery_direction") or {}),
        "direction_applied": bool(direction_applied),
        "attempt_count": max(1, int(attempt_count)),
        "latency_seconds": round(max(0.0, float(latency_seconds)), 3),
        "audio_sha256": _file_sha256(audio_path),
        "status": "succeeded",
    }


def extract_request_ledger(
    chunks: list[dict[str, Any]],
    *,
    provider: str,
    model: str,
    voice: str,
    enabled: bool,
    include_transcript: bool,
    include_effective_instructions: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    sanitized_chunks: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    coverage_records: list[dict[str, Any]] = []
    for chunk in chunks:
        sanitized = dict(chunk)
        raw_request = sanitized.pop("_tts_request", None)
        if isinstance(raw_request, dict):
            request = dict(raw_request)
        else:
            request = _local_request_record(
                chunk=sanitized,
                provider=provider,
                model=model,
                voice=voice,
            )
        sanitized["tts_request_id"] = request["request_id"]
        sanitized_chunks.append(sanitized)
        if not include_transcript:
            request.pop("transcript", None)
        if not include_effective_instructions:
            request.pop("effective_instructions", None)
        coverage_records.append(request)
        if enabled:
            ledger.append(request)
    return sanitized_chunks, ledger, direction_coverage(sanitized_chunks, coverage_records)


def direction_coverage(
    chunks: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    by_chunk = {str(item.get("chunk_id") or ""): item for item in ledger}
    directed = [chunk for chunk in chunks if isinstance(chunk.get("delivery_direction"), dict) and chunk.get("delivery_direction")]
    applied = [
        chunk
        for chunk in directed
        if bool((by_chunk.get(str(chunk.get("chunk_id") or "")) or {}).get("direction_applied"))
    ]
    fields = (
        "performance_intent",
        "emotional_color",
        "pace",
        "energy",
        "emphasis_phrases",
        "pause_after",
    )
    field_counts = {
        field: sum(bool((chunk.get("delivery_direction") or {}).get(field)) for chunk in chunks)
        for field in fields
    }
    return {
        "chunk_count": len(chunks),
        "directed_chunk_count": len(directed),
        "direction_applied_chunk_count": len(applied),
        "direction_coverage_ratio": round(len(applied) / len(directed), 4) if directed else 0.0,
        "field_counts": field_counts,
        "section_count": len({str(chunk.get("section_id") or "") for chunk in chunks if chunk.get("section_id")}),
        "story_count": len({str(chunk.get("story_id") or "") for chunk in chunks if chunk.get("story_id")}),
    }


def _local_request_record(
    *,
    chunk: dict[str, Any],
    provider: str,
    model: str,
    voice: str,
) -> dict[str, Any]:
    transcript = str(chunk.get("text") or "")
    chunk_id = str(chunk.get("chunk_id") or "chunk")
    identity = "\n".join((provider, model, voice, chunk_id, transcript))
    audio_path = Path(str(chunk.get("audio_path") or ""))
    return {
        "request_id": f"tts_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
        "chunk_id": chunk_id,
        "audio_unit_id": str(chunk.get("audio_unit_id") or ""),
        "section_id": str(chunk.get("section_id") or ""),
        "story_id": str(chunk.get("story_id") or ""),
        "beat_id": str(chunk.get("beat_id") or ""),
        "beat_order": int(chunk.get("beat_order") or 0),
        "beat_type": str(chunk.get("beat_type") or ""),
        "beat_function": str(chunk.get("beat_function") or ""),
        "provider": provider,
        "model": model,
        "voice": voice,
        "transcript": transcript,
        "transcript_sha256": _text_sha256(transcript),
        "effective_instructions": "",
        "instructions_sha256": _text_sha256(""),
        "delivery_direction": dict(chunk.get("delivery_direction") or {}),
        "direction_applied": False,
        "attempt_count": 1,
        "latency_seconds": None,
        "audio_sha256": _file_sha256(audio_path),
        "status": "succeeded",
    }


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
