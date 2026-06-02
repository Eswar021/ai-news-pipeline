from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.config.paths import OUTPUT_DIR
from src.voiceover.config import (
    DEFAULT_AUDITION_TEXT,
    DEFAULT_AUDITION_VOICES,
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_STYLE,
    resolve_style,
)
from src.voiceover.providers.kokoro_local import synthesize_chunk_to_wav
from src.voiceover.text_chunks import word_count


def audition_voices(
    *,
    style: str = DEFAULT_STYLE,
    voices: list[str] | None = None,
    text: str = DEFAULT_AUDITION_TEXT,
    force: bool = False,
) -> dict:
    style_profile = resolve_style(style)
    voices = voices or DEFAULT_AUDITION_VOICES
    output_dir = OUTPUT_DIR / "voiceover_auditions" / style
    manifest_path = output_dir / "audition_manifest.json"
    if output_dir.exists() and not force:
        raise FileExistsError(f"Audition output already exists: {output_dir}. Rerun with --force to replace it.")
    if force and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = []
    failures = []
    for voice in voices:
        output_path = output_dir / f"{voice}.wav"
        try:
            audio = synthesize_chunk_to_wav(
                text=text,
                output_path=output_path,
                voice=voice,
                speed=style_profile.speed,
                language_code=DEFAULT_LANGUAGE_CODE,
                sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ,
            )
        except Exception as exc:
            failures.append({"voice": voice, "error": str(exc)})
            continue
        samples.append(
            {
                "voice": voice,
                "audio_path": _portable_path(output_path),
                "duration_seconds": round(float(audio["duration_seconds"]), 2),
            }
        )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_type": "voiceover_audition",
        "status": "ready" if samples else "failed",
        "style": {
            "name": style_profile.name,
            "description": style_profile.description,
            "speed": style_profile.speed,
        },
        "sample_text": text,
        "word_count": word_count(text),
        "samples": samples,
        "failures": failures,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if not samples:
        raise RuntimeError(f"All voice auditions failed. Details: {failures}")
    return manifest


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(OUTPUT_DIR.parent))
    except ValueError:
        return str(path)
