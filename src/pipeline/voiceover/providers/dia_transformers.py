from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


INSTALL_HINT = (
    "Dia Transformers voiceover requires torch, transformers with Dia support, and soundfile. "
    "Use the voiceover Python environment, then run: "
    "PIP_USER=false python -m pip install -r requirements-voiceover.txt. "
    f"Current Python is {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}. "
    "Dia is a large GPU-first model, so CPU synthesis may be slow or unavailable."
)

_MODELS: dict[tuple[str, str, str | None], tuple[Any, Any]] = {}


def synthesize_chunk_to_wav(
    *,
    text: str,
    output_path: Path,
    model_checkpoint: str,
    device: str,
    cache_dir: str | None,
    max_new_tokens: int,
    guidance_scale: float,
    temperature: float,
    top_p: float,
    top_k: int,
    speaker_tag: str,
) -> dict:
    processor, model, resolved_device = _model(model_checkpoint, device, cache_dir)
    torch = _torch()

    prepared_text = _prepare_text(text, speaker_tag)
    try:
        inputs = processor(text=[prepared_text], padding=True, return_tensors="pt").to(resolved_device)
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                guidance_scale=guidance_scale,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
            )
        audio = processor.batch_decode(outputs)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        processor.save_audio(audio, str(output_path))
    except Exception as exc:
        raise RuntimeError(f"Dia synthesis failed for {output_path.name}: {exc}") from exc

    sample_rate_hz = _sample_rate_hz(processor)
    duration_seconds = _audio_duration_seconds(output_path)
    return {
        "audio_path": str(output_path),
        "duration_seconds": duration_seconds,
        "sample_rate_hz": sample_rate_hz,
        "device": resolved_device,
        "model_checkpoint": model_checkpoint,
        "max_new_tokens": max_new_tokens,
        "guidance_scale": guidance_scale,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "speaker_tag": speaker_tag,
    }


def _model(model_checkpoint: str, device: str, cache_dir: str | None) -> tuple[Any, Any, str]:
    resolved_device = _resolve_device(device)
    key = (model_checkpoint, resolved_device, cache_dir)
    if key in _MODELS:
        processor, model = _MODELS[key]
        return processor, model, resolved_device
    _configure_cache(cache_dir)

    try:
        from transformers import AutoProcessor, DiaForConditionalGeneration
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc

    try:
        processor = AutoProcessor.from_pretrained(model_checkpoint, cache_dir=cache_dir)
        model = DiaForConditionalGeneration.from_pretrained(model_checkpoint, cache_dir=cache_dir).to(resolved_device)
        model.eval()
    except Exception as exc:
        raise RuntimeError(f"Could not initialize Dia model. {INSTALL_HINT} Details: {exc}") from exc

    _MODELS[key] = (processor, model)
    return processor, model, resolved_device


def _configure_cache(cache_dir: str | None) -> None:
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    if cache_dir is None:
        return
    path = Path(cache_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(path))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(path / "hub"))


def _resolve_device(device: str) -> str:
    cleaned = device.strip().lower()
    if cleaned != "auto":
        return cleaned

    torch = _torch()
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _torch() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    return torch


def _prepare_text(text: str, speaker_tag: str) -> str:
    cleaned_tag = speaker_tag.strip().strip("[]")
    cleaned_text = text.strip()
    if cleaned_text.startswith("[S"):
        return cleaned_text
    return f"[{cleaned_tag}] {cleaned_text} [{cleaned_tag}]"


def _sample_rate_hz(processor: Any) -> int:
    feature_extractor = getattr(processor, "feature_extractor", None)
    if feature_extractor is not None and getattr(feature_extractor, "sampling_rate", None):
        return int(feature_extractor.sampling_rate)
    return 44100


def _audio_duration_seconds(path: Path) -> float:
    try:
        import soundfile
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    info = soundfile.info(str(path))
    return float(info.frames) / float(info.samplerate)
