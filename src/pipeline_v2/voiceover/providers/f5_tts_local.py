from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


INSTALL_HINT = (
    "F5-TTS local voiceover requires f5-tts, torch, torchaudio, and soundfile. "
    "Use the voiceover Python environment, then run: "
    "PIP_USER=false python -m pip install -r requirements-voiceover.txt. "
    f"Current Python is {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}. "
    "The first synthesis may download F5-TTS model and vocoder weights."
)

_MODELS: dict[tuple[str, str, str | None], Any] = {}


def synthesize_chunk_to_wav(
    *,
    text: str,
    output_path: Path,
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
) -> dict:
    resolved_ref_audio = _resolve_file(ref_audio_path, "F5-TTS reference audio")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    f5_model, resolved_device = _model(model_name, device, cache_dir)
    try:
        _wav, sample_rate_hz, _spec = f5_model.infer(
            ref_file=str(resolved_ref_audio),
            ref_text=ref_text,
            gen_text=text,
            show_info=_quiet,
            progress=None,
            target_rms=target_rms,
            cross_fade_duration=cross_fade_duration,
            sway_sampling_coef=sway_sampling_coef,
            cfg_strength=cfg_strength,
            nfe_step=nfe_step,
            speed=speed,
            remove_silence=remove_silence,
            file_wave=str(output_path),
            seed=seed,
        )
    except Exception as exc:
        raise RuntimeError(f"F5-TTS synthesis failed for {output_path.name}: {exc}") from exc

    duration_seconds = _audio_duration_seconds(output_path)
    return {
        "audio_path": str(output_path),
        "duration_seconds": duration_seconds,
        "sample_rate_hz": int(sample_rate_hz),
        "device": resolved_device,
        "model": model_name,
        "ref_audio_path": str(resolved_ref_audio),
        "nfe_step": nfe_step,
        "cfg_strength": cfg_strength,
        "sway_sampling_coef": sway_sampling_coef,
    }


def _model(model_name: str, device: str, cache_dir: str | None) -> tuple[Any, str]:
    resolved_device = _resolve_device(device)
    key = (model_name, resolved_device, cache_dir)
    if key in _MODELS:
        return _MODELS[key], resolved_device
    _configure_cache(cache_dir)

    try:
        from f5_tts.api import F5TTS
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc

    try:
        model = F5TTS(model=model_name, device=resolved_device, hf_cache_dir=cache_dir)
    except Exception as exc:
        raise RuntimeError(f"Could not initialize F5-TTS model. {INSTALL_HINT} Details: {exc}") from exc

    _MODELS[key] = model
    return model, resolved_device


def _configure_cache(cache_dir: str | None) -> None:
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    if cache_dir is None:
        return
    path = Path(cache_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(path))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(path / "hub"))
    os.environ.setdefault("MPLCONFIGDIR", str(path / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(path / "xdg"))


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
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _resolve_file(path_value: str, label: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _audio_duration_seconds(path: Path) -> float:
    try:
        import soundfile
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    info = soundfile.info(str(path))
    return float(info.frames) / float(info.samplerate)


def _quiet(_message: Any) -> None:
    return None
