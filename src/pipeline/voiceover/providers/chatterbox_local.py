from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


INSTALL_HINT = (
    "Chatterbox local voiceover requires chatterbox-tts and torchaudio. "
    "Use the voiceover Python environment, then run: "
    "PIP_USER=false python -m pip install -r requirements-voiceover.txt. "
    f"Current Python is {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}. "
    "The first synthesis may also download Chatterbox model weights."
)

_MODELS: dict[str, Any] = {}


def synthesize_chunk_to_wav(
    *,
    text: str,
    output_path: Path,
    device: str,
    exaggeration: float,
    cfg_weight: float,
    audio_prompt_path: str | None,
    cache_dir: str | None,
) -> dict:
    model, resolved_device = _model(device, cache_dir)
    torchaudio, torch = _audio_dependencies()
    prompt_path = _resolve_audio_prompt(audio_prompt_path)

    generate_kwargs: dict[str, Any] = {
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
    }
    if prompt_path is not None:
        generate_kwargs["audio_prompt_path"] = str(prompt_path)

    try:
        wav = model.generate(text, **generate_kwargs)
    except Exception as exc:
        raise RuntimeError(f"Chatterbox synthesis failed for {output_path.name}: {exc}") from exc

    sample_rate_hz = int(getattr(model, "sr", 24000))
    wav = _prepare_wav_tensor(wav, torch)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(output_path), wav, sample_rate_hz)

    duration_seconds = int(wav.shape[-1]) / sample_rate_hz
    return {
        "audio_path": str(output_path),
        "duration_seconds": duration_seconds,
        "sample_rate_hz": sample_rate_hz,
        "device": resolved_device,
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "audio_prompt_path": str(prompt_path) if prompt_path else None,
    }


def _model(device: str, cache_dir: str | None) -> tuple[Any, str]:
    resolved_device = _resolve_device(device)
    if resolved_device in _MODELS:
        return _MODELS[resolved_device], resolved_device
    _configure_cache(cache_dir)

    try:
        from chatterbox.tts import ChatterboxTTS
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc

    try:
        model = ChatterboxTTS.from_pretrained(device=resolved_device)
    except Exception as exc:
        raise RuntimeError(f"Could not initialize Chatterbox model. {INSTALL_HINT} Details: {exc}") from exc

    _MODELS[resolved_device] = model
    return model, resolved_device


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

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _audio_dependencies() -> tuple[Any, Any]:
    try:
        import torch
        import torchaudio
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    return torchaudio, torch


def _resolve_audio_prompt(audio_prompt_path: str | None) -> Path | None:
    if audio_prompt_path is None:
        return None
    path = Path(audio_prompt_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Chatterbox audio prompt not found: {path}")
    return path


def _prepare_wav_tensor(wav: Any, torch: Any) -> Any:
    if not hasattr(wav, "detach"):
        wav = torch.as_tensor(wav)
    wav = wav.detach().cpu().float()
    if wav.ndim == 1:
        wav = wav.unsqueeze(0)
    return wav
