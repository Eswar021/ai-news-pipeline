from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.voiceover.audio_manifest import build_summary, build_voiceover_package
from src.voiceover.config import (
    DEFAULT_KEEP_CHUNKS,
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_PROVIDER,
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_STYLE,
    PROVIDER_KOKORO_LOCAL,
    VoiceoverStyle,
    resolve_style,
    validate_provider,
)
from src.voiceover.providers.kokoro_local import concatenate_wav_files, synthesize_chunk_to_wav
from src.voiceover.text_chunks import estimated_seconds_from_words, split_narration_into_chunks, word_count


def generate_voiceover(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    voice: str | None = None,
    speed: float | None = None,
    *,
    style: str = DEFAULT_STYLE,
    keep_chunks: bool = DEFAULT_KEEP_CHUNKS,
    force: bool = False,
    chunk_max_chars: int | None = None,
) -> dict:
    validate_provider(provider)
    style_profile = resolve_style(style)
    resolved_run_id = _resolve_run_id(run_id)
    manifest = _load_manifest(resolved_run_id)
    verification_package = _load_verification_package(resolved_run_id)
    narration_text = _approved_narration_text(verification_package)

    output_dir = OUTPUT_DIR / resolved_run_id / "voiceover"
    audio_dir = output_dir / "audio"
    chunk_dir = audio_dir / "chunks"
    package_path = output_dir / "voiceover_package.json"
    summary_path = output_dir / "summary.json"
    full_audio_path = audio_dir / "full_voiceover.wav"

    if package_path.exists() and not force:
        raise FileExistsError(f"Voiceover already exists for {resolved_run_id}. Rerun with --force to replace it.")
    if force and output_dir.exists():
        shutil.rmtree(output_dir)

    resolved_chunk_max_chars = chunk_max_chars or style_profile.chunk_max_chars
    chunks = split_narration_into_chunks(
        narration_text,
        max_chars=resolved_chunk_max_chars,
        max_sentences_per_chunk=style_profile.max_sentences_per_chunk,
        chunk_pause_seconds=style_profile.chunk_pause_seconds,
        paragraph_pause_seconds=style_profile.paragraph_pause_seconds,
    )
    if not chunks:
        raise ValueError("Approved L8 narration is empty after cleanup.")

    voice_name = voice or style_profile.default_voice
    speed_value = speed if speed is not None else style_profile.speed
    if provider == PROVIDER_KOKORO_LOCAL:
        synthesized_chunks = _synthesize_kokoro_chunks(
            chunks=chunks,
            chunk_dir=chunk_dir,
            voice=voice_name,
            speed=speed_value,
        )
        duration_seconds = concatenate_wav_files(
            input_paths=[Path(chunk["audio_path"]) for chunk in synthesized_chunks],
            output_path=full_audio_path,
            sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ,
            pauses_after_seconds=[float(chunk.get("pause_after_seconds", 0.0)) for chunk in synthesized_chunks],
        )
    else:
        raise NotImplementedError(f"Voiceover provider '{provider}' is not implemented yet.")

    if not keep_chunks:
        _discard_chunk_files(synthesized_chunks, chunk_dir)

    script_words = word_count(narration_text)
    package = build_voiceover_package(
        run_id=resolved_run_id,
        provider=provider,
        voice=voice_name,
        style=_style_manifest(style_profile, voice_name, speed_value, resolved_chunk_max_chars),
        sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ,
        full_audio_path=full_audio_path,
        duration_seconds=duration_seconds,
        script_word_count=script_words,
        estimated_script_seconds=_estimated_script_seconds(verification_package, script_words),
        chunks=synthesized_chunks,
    )
    package["source_manifest"] = {
        "run_profile": manifest.get("layer_0", {}).get("run_profile", ""),
        "channel_name": manifest.get("layer_0", {}).get("channel_scope", {}).get("channel_name", ""),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(build_summary(package), indent=2, ensure_ascii=False), encoding="utf-8")
    return package


def _synthesize_kokoro_chunks(*, chunks: list[dict[str, Any]], chunk_dir: Path, voice: str, speed: float) -> list[dict]:
    enriched_chunks = []
    cursor_seconds = 0.0
    for chunk in chunks:
        audio_path = chunk_dir / f"{chunk['chunk_id']}.wav"
        audio = synthesize_chunk_to_wav(
            text=chunk["text"],
            output_path=audio_path,
            voice=voice,
            speed=speed,
            language_code=DEFAULT_LANGUAGE_CODE,
            sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ,
        )
        duration_seconds = float(audio["duration_seconds"])
        start_seconds = cursor_seconds
        end_seconds = start_seconds + duration_seconds
        cursor_seconds = end_seconds + float(chunk.get("pause_after_seconds", 0.0))
        enriched_chunks.append(
            {
                **chunk,
                "audio_path": audio["audio_path"],
                "duration_seconds": round(duration_seconds, 2),
                "start_seconds": round(start_seconds, 2),
                "end_seconds": round(end_seconds, 2),
            }
        )
    return enriched_chunks


def _discard_chunk_files(chunks: list[dict], chunk_dir: Path) -> None:
    for chunk in chunks:
        audio_path = chunk.get("audio_path")
        if audio_path and Path(audio_path).exists():
            Path(audio_path).unlink()
            chunk["audio_path"] = ""
    if chunk_dir.exists() and not any(chunk_dir.iterdir()):
        chunk_dir.rmdir()


def _style_manifest(style: VoiceoverStyle, voice: str, speed: float, chunk_max_chars: int) -> dict:
    return {
        "name": style.name,
        "description": style.description,
        "voice": voice,
        "speed": speed,
        "chunk_max_chars": chunk_max_chars,
        "max_sentences_per_chunk": style.max_sentences_per_chunk,
        "chunk_pause_seconds": style.chunk_pause_seconds,
        "paragraph_pause_seconds": style.paragraph_pause_seconds,
    }


def _approved_narration_text(verification_package: dict) -> str:
    if verification_package.get("status") != "approved":
        raise ValueError(f"Voiceover requires L8 status='approved', got: {verification_package.get('status')}")
    final_publish_package = verification_package.get("final_publish_package")
    if not final_publish_package:
        raise KeyError("L8 verification package is missing final_publish_package")
    narration_text = final_publish_package.get("narration_text", "")
    if not narration_text:
        raise KeyError("final_publish_package is missing narration_text")
    return narration_text


def _estimated_script_seconds(verification_package: dict, script_words: int) -> float:
    script_package = verification_package.get("verified_script_package", {})
    estimated = script_package.get("full_script", {}).get("estimated_duration_seconds")
    if estimated:
        return round(float(estimated), 1)
    return estimated_seconds_from_words(script_words)


def _load_verification_package(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L8" / "verification_package.json"
    if not path.exists():
        raise FileNotFoundError(f"L8 verification package not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_manifest(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "run_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Run manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_run_id(run_ref: str) -> str:
    if run_ref != "current":
        return run_ref
    if not CURRENT_MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Current manifest not found: {CURRENT_MANIFEST_PATH}")
    manifest = json.loads(CURRENT_MANIFEST_PATH.read_text(encoding="utf-8"))
    run_id = manifest.get("run_id")
    if not run_id:
        raise KeyError("output/current_manifest.json is missing run_id")
    return run_id
