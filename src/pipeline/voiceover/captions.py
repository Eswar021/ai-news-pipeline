from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from src.pipeline.contracts import file_sha256


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def write_caption_files(
    *,
    audio_units: list[dict[str, Any]],
    output_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    if not bool(config.get("enabled", False)):
        return {"enabled": False, "status": "bypassed", "files": [], "cue_count": 0}

    cues = _caption_cues(
        audio_units,
        max_chars=int(config.get("max_chars_per_cue", 48)),
        max_words=int(config.get("max_words_per_cue", 12)),
        min_seconds=float(config.get("min_cue_seconds", 0.8)),
    )
    if not cues:
        raise ValueError("Caption generation requires aligned voiceover beats")

    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for caption_format in config.get("formats", ["srt", "vtt"]):
        if caption_format == "srt":
            path = output_dir / "captions.srt"
            path.write_text(_srt_text(cues), encoding="utf-8")
        elif caption_format == "vtt":
            path = output_dir / "captions.vtt"
            path.write_text(_vtt_text(cues), encoding="utf-8")
        else:
            raise ValueError(f"Unsupported caption format: {caption_format}")
        files.append(
            {
                "format": caption_format,
                "path": str(path),
                "sha256": file_sha256(path),
            }
        )
    return {
        "enabled": True,
        "status": "ready",
        "cue_count": len(cues),
        "files": files,
    }


def _caption_cues(
    audio_units: list[dict[str, Any]],
    *,
    max_chars: int,
    max_words: int,
    min_seconds: float,
) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    for unit in audio_units:
        for beat in unit.get("aligned_beats", []):
            if not isinstance(beat, dict):
                continue
            text = _clean_text(beat.get("text"))
            start = float(beat.get("start_seconds", 0.0) or 0.0)
            end = float(beat.get("end_seconds", start) or start)
            if not text or end <= start:
                continue
            parts = _split_caption_text(text, max_chars=max_chars, max_words=max_words)
            weights = [max(1, len(part.split())) for part in parts]
            total_weight = sum(weights)
            duration = end - start
            cursor = start
            accumulated_weight = 0
            can_enforce_minimum = duration >= len(parts) * min_seconds
            for index, part in enumerate(parts):
                accumulated_weight += weights[index]
                if index == len(parts) - 1:
                    cue_end = end
                else:
                    cue_end = start + duration * (accumulated_weight / total_weight)
                    if can_enforce_minimum:
                        remaining_parts = len(parts) - index - 1
                        cue_end = min(
                            end - remaining_parts * min_seconds,
                            max(cursor + min_seconds, cue_end),
                        )
                cues.append(
                    {
                        "start_seconds": round(cursor, 3),
                        "end_seconds": round(max(cursor + 0.05, cue_end), 3),
                        "text": part,
                        "section_id": str(beat.get("section_id") or unit.get("section_id") or ""),
                        "story_id": str(beat.get("story_id") or unit.get("story_id") or ""),
                        "beat_id": str(beat.get("beat_id") or ""),
                    }
                )
                cursor = cue_end
    return cues


def _split_caption_text(text: str, *, max_chars: int, max_words: int) -> list[str]:
    sentences = [item.strip() for item in _SENTENCE_RE.split(text) if item.strip()]
    pieces: list[str] = []
    for sentence in sentences or [text]:
        words = sentence.split()
        current: list[str] = []
        for word in words:
            candidate = " ".join([*current, word])
            if current and (len(candidate) > max_chars or len(current) >= max_words):
                pieces.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            pieces.append(" ".join(current))
    return pieces or [text]


def _srt_text(cues: list[dict[str, Any]]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_timestamp(cue['start_seconds'], decimal=',')} --> "
                    f"{_timestamp(cue['end_seconds'], decimal=',')}",
                    cue["text"],
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def _vtt_text(cues: list[dict[str, Any]]) -> str:
    blocks = ["WEBVTT"]
    for cue in cues:
        blocks.append(
            "\n".join(
                [
                    f"{_timestamp(cue['start_seconds'], decimal='.')} --> "
                    f"{_timestamp(cue['end_seconds'], decimal='.')}",
                    cue["text"],
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def _timestamp(seconds: float, *, decimal: str) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{decimal}{millis:03d}"


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
