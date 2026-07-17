from __future__ import annotations

from datetime import datetime, timezone
import json
import shutil
from pathlib import Path
from typing import Any

from src.pipeline.contracts import file_sha256

from .audio_manifest import build_summary, build_voiceover_package
from .audio_postprocess import master_audio
from .captions import write_caption_files
from .config import (
    PROVIDER_CHATTERBOX_LOCAL,
    PROVIDER_DIA_TRANSFORMERS,
    PROVIDER_F5_TTS_LOCAL,
    PROVIDER_KOKORO_LOCAL,
    VoiceoverStyle,
    resolve_style,
    validate_provider,
)
from .contract import VoiceoverRequest, VoiceoverResponse
from .providers.chatterbox_local import synthesize_chunk_to_wav as synthesize_chatterbox_chunk_to_wav
from .providers.dia_transformers import synthesize_chunk_to_wav as synthesize_dia_chunk_to_wav
from .providers.f5_tts_local import synthesize_chunk_to_wav as synthesize_f5_chunk_to_wav
from .providers.kokoro_local import concatenate_wav_files, synthesize_chunk_to_wav as synthesize_kokoro_chunk_to_wav
from .script_units import build_audio_units, resolve_script_input
from .text_chunks import estimated_seconds_from_words, split_narration_into_chunks, word_count


def run(input_json: dict) -> dict:
    request = VoiceoverRequest.model_validate(input_json)
    validate_provider(request.config.provider)

    style_profile = resolve_style(request.config.style)
    voice_name = _resolved_voice_name(request, style_profile)
    speed_value = request.config.speed if request.config.speed is not None else style_profile.speed
    chunking = _resolved_chunking(request, style_profile)
    script_input = resolve_script_input(request, chunking)
    script_text = script_input["text"]
    script_source = script_input["source"]

    output_dir = Path(request.config.output_dir)
    audio_dir = output_dir / "audio"
    chunk_dir = audio_dir / "chunks"
    audio_unit_dir = audio_dir / "units"
    package_path = output_dir / "voiceover_package.json"
    summary_path = output_dir / "summary.json"
    full_audio_path = audio_dir / "full_voiceover.wav"
    raw_audio_path = audio_dir / "raw_voiceover.wav"

    if package_path.exists() and not request.config.force:
        raise FileExistsError(f"Voiceover already exists at {package_path}. Set config.force=true to replace it.")
    if request.config.force and output_dir.exists():
        shutil.rmtree(output_dir)

    chunks = list(script_input["chunks"])
    if not chunks:
        raise ValueError("Voiceover input script is empty after cleanup.")

    actual_sample_rate_hz = request.config.sample_rate_hz
    if request.config.provider == PROVIDER_KOKORO_LOCAL:
        synthesized_chunks = _synthesize_kokoro_chunks(
            chunks=chunks,
            chunk_dir=chunk_dir,
            voice=voice_name,
            speed=speed_value,
            language_code=request.config.language_code,
            sample_rate_hz=request.config.sample_rate_hz,
        )
        duration_seconds = concatenate_wav_files(
            input_paths=[Path(chunk["audio_path"]) for chunk in synthesized_chunks],
            output_path=raw_audio_path,
            sample_rate_hz=actual_sample_rate_hz,
            pauses_after_seconds=[float(chunk.get("pause_after_seconds", 0.0)) for chunk in synthesized_chunks],
        )
    elif request.config.provider == PROVIDER_CHATTERBOX_LOCAL:
        synthesized_chunks = _synthesize_chatterbox_chunks(
            chunks=chunks,
            chunk_dir=chunk_dir,
            device=request.config.chatterbox.device,
            exaggeration=request.config.chatterbox.exaggeration,
            cfg_weight=request.config.chatterbox.cfg_weight,
            audio_prompt_path=request.config.chatterbox.audio_prompt_path,
            cache_dir=request.config.chatterbox.cache_dir,
        )
        actual_sample_rate_hz = int(synthesized_chunks[0].get("sample_rate_hz", request.config.sample_rate_hz))
        duration_seconds = concatenate_wav_files(
            input_paths=[Path(chunk["audio_path"]) for chunk in synthesized_chunks],
            output_path=raw_audio_path,
            sample_rate_hz=actual_sample_rate_hz,
            pauses_after_seconds=[float(chunk.get("pause_after_seconds", 0.0)) for chunk in synthesized_chunks],
        )
    elif request.config.provider == PROVIDER_F5_TTS_LOCAL:
        synthesized_chunks = _synthesize_f5_chunks(
            chunks=chunks,
            chunk_dir=chunk_dir,
            model_name=request.config.f5_tts.model,
            device=request.config.f5_tts.device,
            ref_audio_path=request.config.f5_tts.ref_audio_path or "",
            ref_text=request.config.f5_tts.ref_text or "",
            cache_dir=request.config.f5_tts.cache_dir,
            speed=speed_value,
            nfe_step=request.config.f5_tts.nfe_step,
            cfg_strength=request.config.f5_tts.cfg_strength,
            sway_sampling_coef=request.config.f5_tts.sway_sampling_coef,
            target_rms=request.config.f5_tts.target_rms,
            cross_fade_duration=request.config.f5_tts.cross_fade_duration,
            remove_silence=request.config.f5_tts.remove_silence,
            seed=request.config.f5_tts.seed,
        )
        actual_sample_rate_hz = int(synthesized_chunks[0].get("sample_rate_hz", request.config.sample_rate_hz))
        duration_seconds = concatenate_wav_files(
            input_paths=[Path(chunk["audio_path"]) for chunk in synthesized_chunks],
            output_path=raw_audio_path,
            sample_rate_hz=actual_sample_rate_hz,
            pauses_after_seconds=[float(chunk.get("pause_after_seconds", 0.0)) for chunk in synthesized_chunks],
        )
    elif request.config.provider == PROVIDER_DIA_TRANSFORMERS:
        synthesized_chunks = _synthesize_dia_chunks(
            chunks=chunks,
            chunk_dir=chunk_dir,
            model_checkpoint=request.config.dia.model_checkpoint,
            device=request.config.dia.device,
            cache_dir=request.config.dia.cache_dir,
            max_new_tokens=request.config.dia.max_new_tokens,
            guidance_scale=request.config.dia.guidance_scale,
            temperature=request.config.dia.temperature,
            top_p=request.config.dia.top_p,
            top_k=request.config.dia.top_k,
            speaker_tag=request.config.dia.speaker_tag,
        )
        actual_sample_rate_hz = int(synthesized_chunks[0].get("sample_rate_hz", request.config.sample_rate_hz))
        duration_seconds = concatenate_wav_files(
            input_paths=[Path(chunk["audio_path"]) for chunk in synthesized_chunks],
            output_path=raw_audio_path,
            sample_rate_hz=actual_sample_rate_hz,
            pauses_after_seconds=[float(chunk.get("pause_after_seconds", 0.0)) for chunk in synthesized_chunks],
        )
    else:
        raise NotImplementedError(f"Voiceover provider '{request.config.provider}' is not implemented yet.")

    audio_units = build_audio_units(
        synthesized_chunks=synthesized_chunks,
        output_dir=audio_unit_dir,
        sample_rate_hz=actual_sample_rate_hz,
    )
    mastering = master_audio(
        input_path=raw_audio_path,
        output_path=full_audio_path,
        sample_rate_hz=actual_sample_rate_hz,
        config=request.config.mastering.model_dump(mode="json"),
    )
    duration_seconds = float(mastering.get("duration_seconds", duration_seconds))
    captions = write_caption_files(
        audio_units=audio_units,
        output_dir=output_dir / "captions",
        config=request.config.captions.model_dump(mode="json"),
    )

    if not request.config.keep_chunks:
        _discard_chunk_files(synthesized_chunks, chunk_dir)

    script_words = word_count(script_text)
    package = build_voiceover_package(
        run_id=request.run.run_id,
        provider=request.config.provider,
        voice=voice_name,
        style=_style_manifest(style_profile, voice_name, speed_value, chunking, _provider_settings(request)),
        sample_rate_hz=actual_sample_rate_hz,
        full_audio_path=full_audio_path,
        duration_seconds=duration_seconds,
        script_source=script_source,
        script_word_count=script_words,
        estimated_script_seconds=_estimated_script_seconds(request, script_words),
        chunks=synthesized_chunks,
        audio_units=audio_units,
        alignment_strategy=script_input["alignment_strategy"],
        script_provenance=script_input["provenance"],
        audio_sha256=file_sha256(full_audio_path),
        mastering=mastering,
        captions=captions,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = build_summary(package)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    response = VoiceoverResponse(
        status="ok",
        data={
            "run_id": request.run.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "voiceover_package": package,
        },
        summary=summary,
        handoff=package["handoff"],
    )
    return response.model_dump(mode="json")


def _resolved_chunking(request: VoiceoverRequest, style_profile: VoiceoverStyle) -> dict[str, Any]:
    chunking = request.config.chunking
    return {
        "max_chars": chunking.chunk_max_chars or style_profile.chunk_max_chars,
        "max_sentences_per_chunk": chunking.max_sentences_per_chunk or style_profile.max_sentences_per_chunk,
        "chunk_pause_seconds": (
            chunking.chunk_pause_seconds
            if chunking.chunk_pause_seconds is not None
            else style_profile.chunk_pause_seconds
        ),
        "paragraph_pause_seconds": (
            chunking.paragraph_pause_seconds
            if chunking.paragraph_pause_seconds is not None
            else style_profile.paragraph_pause_seconds
        ),
    }


def _resolved_voice_name(request: VoiceoverRequest, style_profile: VoiceoverStyle) -> str:
    if request.config.provider == PROVIDER_CHATTERBOX_LOCAL:
        if request.config.voice:
            return request.config.voice
        if request.config.chatterbox.audio_prompt_path:
            return "chatterbox_reference_audio"
        return "chatterbox_default"
    if request.config.provider == PROVIDER_F5_TTS_LOCAL:
        return request.config.voice or "f5_reference_voice"
    if request.config.provider == PROVIDER_DIA_TRANSFORMERS:
        return request.config.voice or "dia_dialogue_voice"
    return request.config.voice or style_profile.default_voice


def _synthesize_kokoro_chunks(
    *,
    chunks: list[dict[str, Any]],
    chunk_dir: Path,
    voice: str,
    speed: float,
    language_code: str,
    sample_rate_hz: int,
) -> list[dict]:
    enriched_chunks = []
    cursor_seconds = 0.0
    for chunk in chunks:
        audio_path = chunk_dir / f"{chunk['chunk_id']}.wav"
        audio = synthesize_kokoro_chunk_to_wav(
            text=chunk["text"],
            output_path=audio_path,
            voice=voice,
            speed=speed,
            language_code=language_code,
            sample_rate_hz=sample_rate_hz,
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


def _synthesize_chatterbox_chunks(
    *,
    chunks: list[dict[str, Any]],
    chunk_dir: Path,
    device: str,
    exaggeration: float,
    cfg_weight: float,
    audio_prompt_path: str | None,
    cache_dir: str | None,
) -> list[dict]:
    enriched_chunks = []
    cursor_seconds = 0.0
    for chunk in chunks:
        audio_path = chunk_dir / f"{chunk['chunk_id']}.wav"
        audio = synthesize_chatterbox_chunk_to_wav(
            text=chunk["text"],
            output_path=audio_path,
            device=device,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            audio_prompt_path=audio_prompt_path,
            cache_dir=cache_dir,
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
                "sample_rate_hz": audio["sample_rate_hz"],
                "device": audio["device"],
            }
        )
    return enriched_chunks


def _synthesize_f5_chunks(
    *,
    chunks: list[dict[str, Any]],
    chunk_dir: Path,
    model_name: str,
    device: str,
    ref_audio_path: str,
    ref_text: str,
    cache_dir: str | None,
    speed: float,
    nfe_step: int,
    cfg_strength: float,
    sway_sampling_coef: float,
    target_rms: float,
    cross_fade_duration: float,
    remove_silence: bool,
    seed: int | None,
) -> list[dict]:
    enriched_chunks = []
    cursor_seconds = 0.0
    for chunk in chunks:
        audio_path = chunk_dir / f"{chunk['chunk_id']}.wav"
        audio = synthesize_f5_chunk_to_wav(
            text=chunk["text"],
            output_path=audio_path,
            model_name=model_name,
            device=device,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            cache_dir=cache_dir,
            speed=speed,
            nfe_step=nfe_step,
            cfg_strength=cfg_strength,
            sway_sampling_coef=sway_sampling_coef,
            target_rms=target_rms,
            cross_fade_duration=cross_fade_duration,
            remove_silence=remove_silence,
            seed=seed,
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
                "sample_rate_hz": audio["sample_rate_hz"],
                "device": audio["device"],
                "model": audio["model"],
            }
        )
    return enriched_chunks


def _synthesize_dia_chunks(
    *,
    chunks: list[dict[str, Any]],
    chunk_dir: Path,
    model_checkpoint: str,
    device: str,
    cache_dir: str | None,
    max_new_tokens: int,
    guidance_scale: float,
    temperature: float,
    top_p: float,
    top_k: int,
    speaker_tag: str,
) -> list[dict]:
    enriched_chunks = []
    cursor_seconds = 0.0
    for chunk in chunks:
        audio_path = chunk_dir / f"{chunk['chunk_id']}.wav"
        audio = synthesize_dia_chunk_to_wav(
            text=chunk["text"],
            output_path=audio_path,
            model_checkpoint=model_checkpoint,
            device=device,
            cache_dir=cache_dir,
            max_new_tokens=max_new_tokens,
            guidance_scale=guidance_scale,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            speaker_tag=speaker_tag,
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
                "sample_rate_hz": audio["sample_rate_hz"],
                "device": audio["device"],
                "model_checkpoint": audio["model_checkpoint"],
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


def _style_manifest(
    style: VoiceoverStyle,
    voice: str,
    speed: float,
    chunking: dict[str, Any],
    provider_settings: dict[str, Any],
) -> dict:
    manifest = {
        "name": style.name,
        "description": style.description,
        "voice": voice,
        "speed": speed,
        "chunk_max_chars": chunking["max_chars"],
        "max_sentences_per_chunk": chunking["max_sentences_per_chunk"],
        "chunk_pause_seconds": chunking["chunk_pause_seconds"],
        "paragraph_pause_seconds": chunking["paragraph_pause_seconds"],
    }
    if provider_settings:
        manifest["provider_settings"] = provider_settings
    return manifest


def _provider_settings(request: VoiceoverRequest) -> dict[str, Any]:
    if request.config.provider == PROVIDER_CHATTERBOX_LOCAL:
        return {
            "device": request.config.chatterbox.device,
            "exaggeration": request.config.chatterbox.exaggeration,
            "cfg_weight": request.config.chatterbox.cfg_weight,
            "audio_prompt_path": request.config.chatterbox.audio_prompt_path,
            "cache_dir": request.config.chatterbox.cache_dir,
        }
    if request.config.provider == PROVIDER_F5_TTS_LOCAL:
        return {
            "model": request.config.f5_tts.model,
            "device": request.config.f5_tts.device,
            "ref_audio_path": request.config.f5_tts.ref_audio_path,
            "ref_text": request.config.f5_tts.ref_text,
            "cache_dir": request.config.f5_tts.cache_dir,
            "nfe_step": request.config.f5_tts.nfe_step,
            "cfg_strength": request.config.f5_tts.cfg_strength,
            "sway_sampling_coef": request.config.f5_tts.sway_sampling_coef,
            "target_rms": request.config.f5_tts.target_rms,
            "cross_fade_duration": request.config.f5_tts.cross_fade_duration,
            "remove_silence": request.config.f5_tts.remove_silence,
            "seed": request.config.f5_tts.seed,
        }
    if request.config.provider == PROVIDER_DIA_TRANSFORMERS:
        return {
            "model_checkpoint": request.config.dia.model_checkpoint,
            "device": request.config.dia.device,
            "cache_dir": request.config.dia.cache_dir,
            "max_new_tokens": request.config.dia.max_new_tokens,
            "guidance_scale": request.config.dia.guidance_scale,
            "temperature": request.config.dia.temperature,
            "top_p": request.config.dia.top_p,
            "top_k": request.config.dia.top_k,
            "speaker_tag": request.config.dia.speaker_tag,
        }
    return {}


def _estimated_script_seconds(request: VoiceoverRequest, script_words: int) -> float:
    script_generation = request.input.script_generation
    if script_generation is not None:
        stats = script_generation.data.script_package.get("full_script_stats") or {}
        estimated = stats.get("estimated_duration_seconds")
        if estimated:
            return round(float(estimated), 1)
    return estimated_seconds_from_words(script_words)
