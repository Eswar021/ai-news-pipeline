from __future__ import annotations

from pathlib import Path
from threading import local
from typing import Any

from .api_utils import (
    require_text_within_limit,
    resolve_api_key,
    run_with_retries,
    synthesize_in_parallel,
    write_audio_bytes_to_wav,
)
from ..delivery import compose_delivery_instructions


INSTALL_HINT = (
    "Gemini voiceover requires the google-genai Python package. Install the voiceover runtime with "
    "PIP_USER=false .venv-voiceover/bin/python -m pip install -r requirements-voiceover.txt."
)


def synthesize_chunks_to_wav(
    *,
    chunks: list[dict[str, Any]],
    output_dir: Path,
    model: str,
    voice: str,
    instructions: str,
    speed: float,
    language_code: str,
    api_key_envs: list[str],
    request_timeout_seconds: float,
    max_retries: int,
    retry_initial_delay_seconds: float,
    retry_max_delay_seconds: float,
    worker_count: int,
    max_input_chars: int,
    sample_rate_hz: int,
    delivery_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    api_key = resolve_api_key(api_key_envs, "Gemini")
    output_dir.mkdir(parents=True, exist_ok=True)
    clients = local()

    def client_bundle() -> tuple[Any, Any]:
        if not hasattr(clients, "value"):
            clients.value = _make_client(api_key=api_key, timeout=request_timeout_seconds)
        return clients.value

    def worker(chunk: dict[str, Any]) -> dict[str, Any]:
        text = str(chunk.get("text") or "")
        chunk_id = str(chunk.get("chunk_id") or "chunk")
        require_text_within_limit(text, max_input_chars=max_input_chars, label=f"Gemini {chunk_id}")
        output_path = output_dir / f"{chunk_id}.wav"
        chunk_instructions = compose_delivery_instructions(
            base_instructions=instructions,
            chunk=chunk,
            provider="gemini",
            config=delivery_config or {},
        )

        def request_audio() -> tuple[bytes, str]:
            output_path.unlink(missing_ok=True)
            client, types = client_bundle()
            response = client.models.generate_content(
                model=model,
                contents=_speech_prompt(text=text, instructions=chunk_instructions, speed=speed),
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        language_code=language_code,
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                        ),
                    ),
                ),
            )
            return _extract_audio(response)

        audio_bytes, mime_type = run_with_retries(
            request_audio,
            max_retries=max_retries,
            initial_delay_seconds=retry_initial_delay_seconds,
            max_delay_seconds=retry_max_delay_seconds,
            label=f"Gemini TTS {chunk_id}",
        )
        return {
            **write_audio_bytes_to_wav(
                audio_bytes=audio_bytes,
                output_path=output_path,
                sample_rate_hz=sample_rate_hz,
            ),
            "model": model,
            "voice": voice,
            "mime_type": mime_type,
        }

    return synthesize_in_parallel(chunks=chunks, worker_count=worker_count, worker=worker)


def _make_client(*, api_key: str, timeout: float) -> tuple[Any, Any]:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=int(timeout * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    return client, types


def _speech_prompt(*, text: str, instructions: str, speed: float) -> str:
    return (
        "Synthesize a single-speaker narration performance.\n\n"
        "# AUDIO PROFILE\n"
        f"{instructions.strip()}\n\n"
        "## DIRECTOR'S NOTES\n"
        f"Pace target: approximately {speed:.2f}x a natural conversational delivery. "
        "Keep every word intelligible and avoid dead air.\n"
        "Output rule: speak only the transcript below, exactly once. Never read these directions aloud.\n\n"
        "### TRANSCRIPT\n"
        f"{text}"
    )


def _extract_audio(response: Any) -> tuple[bytes, str]:
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline_data = getattr(part, "inline_data", None)
            data = getattr(inline_data, "data", None)
            if data:
                return bytes(data), str(getattr(inline_data, "mime_type", "") or "audio/pcm")
    raise RuntimeError("Gemini returned no audio data")
