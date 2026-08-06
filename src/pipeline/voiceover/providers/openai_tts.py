from __future__ import annotations

from pathlib import Path
from threading import local
from time import monotonic
from typing import Any

from .api_utils import (
    require_text_within_limit,
    resolve_api_key,
    run_with_retries,
    synthesize_in_parallel,
    wav_metadata,
    write_audio_bytes_to_wav,
)
from ..delivery import compose_delivery_instructions
from ..tts_logging import build_request_record


INSTALL_HINT = (
    "OpenAI voiceover requires the openai Python package. Install the voiceover runtime with "
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
    response_format: str,
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
    if response_format != "wav":
        raise ValueError("OpenAI voiceover currently supports response_format=wav only")
    api_key = resolve_api_key(api_key_envs, "OpenAI")
    output_dir.mkdir(parents=True, exist_ok=True)
    clients = local()

    def client() -> Any:
        if not hasattr(clients, "value"):
            clients.value = _make_client(api_key=api_key, timeout=request_timeout_seconds)
        return clients.value

    def worker(chunk: dict[str, Any]) -> dict[str, Any]:
        text = str(chunk.get("text") or "")
        chunk_id = str(chunk.get("chunk_id") or "chunk")
        require_text_within_limit(text, max_input_chars=max_input_chars, label=f"OpenAI {chunk_id}")
        output_path = output_dir / f"{chunk_id}.wav"
        chunk_instructions = compose_delivery_instructions(
            base_instructions=instructions,
            chunk=chunk,
            provider="openai",
            config=delivery_config or {},
        )
        retry_metadata: dict[str, Any] = {}
        started_at = monotonic()

        def request_audio() -> None:
            output_path.unlink(missing_ok=True)
            try:
                # Request raw PCM (not wav): OpenAI's STREAMED wav writes a placeholder
                # max-length data-chunk header, which strict players (browsers, some
                # muxers) read as ~89000s and render as noise. Wrapping raw PCM into a
                # wav ourselves gives a correct header — same path Gemini uses.
                with client().audio.speech.with_streaming_response.create(
                    model=model,
                    voice=voice,
                    input=text,
                    instructions=chunk_instructions,
                    response_format="pcm",
                    speed=speed,
                ) as response:
                    pcm_bytes = response.read()
                write_audio_bytes_to_wav(
                    audio_bytes=pcm_bytes,
                    output_path=output_path,
                    sample_rate_hz=sample_rate_hz,
                )
            except Exception:
                output_path.unlink(missing_ok=True)
                raise

        run_with_retries(
            request_audio,
            max_retries=max_retries,
            initial_delay_seconds=retry_initial_delay_seconds,
            max_delay_seconds=retry_max_delay_seconds,
            label=f"OpenAI TTS {chunk_id}",
            metadata=retry_metadata,
        )
        return {
            **wav_metadata(output_path, expected_sample_rate_hz=sample_rate_hz),
            "model": model,
            "voice": voice,
            "_tts_request": build_request_record(
                provider="openai",
                model=model,
                voice=voice,
                chunk=chunk,
                effective_instructions=chunk_instructions,
                direction_applied=bool(chunk.get("delivery_direction"))
                and chunk_instructions.strip() != instructions.strip(),
                attempt_count=int(retry_metadata.get("attempt_count", 1)),
                latency_seconds=monotonic() - started_at,
                audio_path=output_path,
            ),
        }

    return synthesize_in_parallel(chunks=chunks, worker_count=worker_count, worker=worker)


def _make_client(*, api_key: str, timeout: float) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    return OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
