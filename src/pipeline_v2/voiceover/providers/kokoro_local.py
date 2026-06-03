from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


INSTALL_HINT = (
    "Kokoro local voiceover requires kokoro and soundfile. "
    "Kokoro 0.9.x requires Python >=3.10,<3.13. "
    f"Current Python is {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}. "
    "Install with a compatible Python environment, then run: "
    "PIP_USER=false python -m pip install -r requirements-voiceover.txt. "
    "The first synthesis may also download Kokoro model weights."
)

_PIPELINES: dict[str, Any] = {}


def synthesize_chunk_to_wav(
    *,
    text: str,
    output_path: Path,
    voice: str,
    speed: float,
    language_code: str,
    sample_rate_hz: int,
) -> dict:
    pipeline = _pipeline(language_code)
    soundfile, numpy = _audio_dependencies()
    audio_parts = []

    try:
        generator = pipeline(text, voice=voice, speed=speed)
        for _graphemes, _phonemes, audio in generator:
            audio_parts.append(_audio_to_numpy(audio, numpy))
    except Exception as exc:
        raise RuntimeError(f"Kokoro synthesis failed for {output_path.name}: {exc}") from exc

    if not audio_parts:
        raise RuntimeError(f"Kokoro returned no audio for {output_path.name}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_data = numpy.concatenate(audio_parts)
    soundfile.write(str(output_path), audio_data, sample_rate_hz)
    duration_seconds = len(audio_data) / sample_rate_hz
    return {
        "audio_path": str(output_path),
        "duration_seconds": duration_seconds,
        "sample_rate_hz": sample_rate_hz,
    }


def concatenate_wav_files(
    *,
    input_paths: list[Path],
    output_path: Path,
    sample_rate_hz: int,
    pauses_after_seconds: list[float] | None = None,
) -> float:
    soundfile, numpy = _audio_dependencies()
    audio_parts = []
    pauses_after_seconds = pauses_after_seconds or [0.0] * len(input_paths)
    if len(pauses_after_seconds) != len(input_paths):
        raise ValueError("pauses_after_seconds must match input_paths length")

    for index, input_path in enumerate(input_paths):
        audio_data, observed_sample_rate = soundfile.read(str(input_path), dtype="float32")
        if observed_sample_rate != sample_rate_hz:
            raise RuntimeError(
                f"Cannot concatenate {input_path}: expected {sample_rate_hz}Hz, got {observed_sample_rate}Hz"
            )
        audio_parts.append(audio_data)
        pause_seconds = pauses_after_seconds[index]
        if index < len(input_paths) - 1 and pause_seconds > 0:
            audio_parts.append(numpy.zeros(int(sample_rate_hz * pause_seconds), dtype="float32"))

    if not audio_parts:
        raise RuntimeError("No chunk audio files were produced.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    full_audio = numpy.concatenate(audio_parts)
    soundfile.write(str(output_path), full_audio, sample_rate_hz)
    return len(full_audio) / sample_rate_hz


def _pipeline(language_code: str) -> Any:
    if language_code in _PIPELINES:
        return _PIPELINES[language_code]
    try:
        from kokoro import KPipeline
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc

    try:
        pipeline = KPipeline(lang_code=language_code)
    except Exception as exc:
        raise RuntimeError(f"Could not initialize Kokoro pipeline. {INSTALL_HINT} Details: {exc}") from exc

    _PIPELINES[language_code] = pipeline
    return pipeline


def _audio_dependencies() -> tuple[Any, Any]:
    try:
        import numpy
        import soundfile
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    return soundfile, numpy


def _audio_to_numpy(audio: Any, numpy: Any) -> Any:
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    return numpy.asarray(audio, dtype="float32")
