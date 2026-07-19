from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import time
from typing import Any, Callable, TypeVar
import wave


T = TypeVar("T")


def resolve_api_key(env_names: list[str], provider: str) -> str:
    for env_name in env_names:
        value = os.getenv(env_name)
        if value and value.strip():
            return value.strip()
    raise RuntimeError(
        f"{provider} voiceover requires an API key. Tried environment variables: {', '.join(env_names)}"
    )


def synthesize_in_parallel(
    *,
    chunks: list[dict[str, Any]],
    worker_count: int,
    worker: Callable[[dict[str, Any]], dict[str, Any]],
) -> list[dict[str, Any]]:
    if worker_count == 1:
        return [worker(chunk) for chunk in chunks]

    results: list[dict[str, Any] | None] = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="voiceover-tts") as executor:
        futures: dict[Future[dict[str, Any]], int] = {
            executor.submit(worker, chunk): index for index, chunk in enumerate(chunks)
        }
        try:
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        except Exception:
            for future in futures:
                future.cancel()
            raise

    if any(result is None for result in results):
        raise RuntimeError("API voiceover synthesis completed without returning every requested chunk")
    return [result for result in results if result is not None]


def run_with_retries(
    operation: Callable[[], T],
    *,
    max_retries: int,
    initial_delay_seconds: float,
    max_delay_seconds: float,
    label: str,
    metadata: dict[str, Any] | None = None,
) -> T:
    for attempt in range(max_retries + 1):
        if metadata is not None:
            metadata["attempt_count"] = attempt + 1
        try:
            return operation()
        except Exception as exc:
            if attempt >= max_retries:
                raise RuntimeError(f"{label} failed after {attempt + 1} attempt(s): {exc}") from exc
            delay = min(max_delay_seconds, initial_delay_seconds * (2**attempt))
            time.sleep(delay)
    raise AssertionError("unreachable retry state")


def require_text_within_limit(text: str, *, max_input_chars: int, label: str) -> None:
    if not text.strip():
        raise ValueError(f"{label} transcript is empty")
    if len(text) > max_input_chars:
        raise ValueError(
            f"{label} transcript contains {len(text)} characters; configured maximum is {max_input_chars}"
        )


def write_audio_bytes_to_wav(
    *,
    audio_bytes: bytes,
    output_path: Path,
    sample_rate_hz: int,
) -> dict[str, Any]:
    if not audio_bytes:
        raise RuntimeError(f"Speech provider returned empty audio for {output_path.name}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if audio_bytes[:4] == b"RIFF":
        output_path.write_bytes(audio_bytes)
    else:
        if len(audio_bytes) % 2:
            raise RuntimeError(f"Speech provider returned malformed 16-bit PCM for {output_path.name}")
        with wave.open(str(output_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate_hz)
            handle.writeframes(audio_bytes)
    return wav_metadata(output_path, expected_sample_rate_hz=sample_rate_hz)


def wav_metadata(path: Path, *, expected_sample_rate_hz: int) -> dict[str, Any]:
    try:
        import soundfile

        info = soundfile.info(str(path))
        frame_count = info.frames
        sample_rate_hz = info.samplerate
        channel_count = info.channels
        subtype = info.subtype
    except Exception as exc:
        raise RuntimeError(f"Speech provider did not create a valid PCM WAV at {path}: {exc}") from exc

    if sample_rate_hz != expected_sample_rate_hz:
        raise RuntimeError(
            f"Speech provider returned {sample_rate_hz}Hz audio; expected {expected_sample_rate_hz}Hz"
        )
    if channel_count != 1:
        raise RuntimeError(f"Speech provider returned {channel_count}-channel audio; mono audio is required")
    if subtype != "PCM_16":
        raise RuntimeError(f"Speech provider returned WAV subtype {subtype}; PCM_16 is required")
    return {
        "audio_path": str(path),
        "duration_seconds": frame_count / sample_rate_hz,
        "sample_rate_hz": sample_rate_hz,
    }
