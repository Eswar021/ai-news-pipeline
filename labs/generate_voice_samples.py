"""labs/voices — a full voice comparison: every OpenAI TTS model, its voices, and a
speed sweep, so the production voice + speed can be chosen by ear. Each sample is
labeled with the exact setting to copy into voiceover.yaml.

Run with the voiceover venv (it has the SDK):
    .venv-voiceover/bin/python labs/generate_voice_samples.py

Writes labs/voices/<id>.wav + .mp3 (preview) + samples.js (the gallery data the
page reads). Best-effort per sample; a failure is skipped, not fatal.

Key finding: speed > 1.0 time-compresses and adds a "tape warble" artifact — speed
1.0 is clean. The speed sweep lets you judge how much speed-up (if any) is tolerable.
"""
from __future__ import annotations

import json
import os
import subprocess
import wave
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
from openai import OpenAI  # noqa: E402

LINE = (
    "A tool built to stop fraud just became the fraud, and nobody caught it for a year. "
    "That's the strangest thing in AI this week, and the one that should worry you most."
)
OUT = ROOT / "labs" / "voices"

# Voice galleries, each at the clean speed (1.0), no style instructions — a fair
# voice-to-voice comparison across models.
GALLERIES = [
    ("gpt-4o-mini-tts", "mini", "expressive & steerable (supports style instructions)",
     ["cedar", "marin", "coral", "ash", "ballad", "sage", "verse", "onyx"]),
    ("tts-1-hd", "hd", "the HD quality model",
     ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]),
    ("tts-1", "tts1", "the fast model (lower fidelity)",
     ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]),
]
# Speed sweeps — one voice per model — to find the fastest speed that still sounds clean.
SWEEPS = [
    ("gpt-4o-mini-tts", "mini", "cedar", [1.0, 1.05, 1.1, 1.15, 1.25]),
    ("tts-1-hd", "hd", "nova", [1.0, 1.1, 1.25]),
]


def _client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY_A_C_C")
    return OpenAI(api_key=key)


def _synth(client: OpenAI, *, model: str, voice: str, speed: float, stem: str) -> bool:
    kwargs: dict = {"model": model, "voice": voice, "input": LINE, "response_format": "pcm"}
    if speed != 1.0:
        kwargs["speed"] = speed
    try:
        pcm = client.audio.speech.create(**kwargs).content
        wav = OUT / f"{stem}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(pcm)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-codec:a", "libmp3lame",
             "-q:a", "3", str(OUT / f"{stem}.mp3")],
            check=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  skip {stem}: {type(exc).__name__}: {str(exc)[:80]}")
        return False


def _slug(speed: float) -> str:
    return f"s{int(round(speed * 100)):03d}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    client = _client()
    sections: list[dict] = []

    # Speed sweeps first (the headline finding).
    for model, mslug, voice, speeds in SWEEPS:
        items = []
        for sp in speeds:
            stem = f"{mslug}_{voice}_{_slug(sp)}"
            if _synth(client, model=model, voice=voice, speed=sp, stem=stem):
                items.append({
                    "label": f"speed {sp:g}",
                    "file": stem,
                    "setting": f"model: {model} · voice: {voice} · speed: {sp:g}",
                })
                print(f"  ok   {stem}")
        sections.append({
            "title": f"Speed sweep — {model} / {voice}",
            "note": "find the fastest speed that still sounds clean (>1.0 adds a tape warble)",
            "items": items,
        })

    # Voice galleries at speed 1.0.
    for model, mslug, note, voices in GALLERIES:
        items = []
        for voice in voices:
            stem = f"{mslug}_{voice}_s100"
            if (OUT / f"{stem}.mp3").exists() or _synth(client, model=model, voice=voice, speed=1.0, stem=stem):
                items.append({
                    "label": voice,
                    "file": stem,
                    "setting": f"model: {model} · voice: {voice} · speed: 1.0",
                })
                print(f"  ok   {stem}")
        sections.append({"title": f"{model} voices — speed 1.0", "note": note, "items": items})

    (OUT / "samples.js").write_text(
        "window.LAB_SAMPLES = " + json.dumps({"line": LINE, "sections": sections}, indent=2) + ";\n",
        encoding="utf-8",
    )
    total = sum(len(s["items"]) for s in sections)
    print(f"wrote {total} samples across {len(sections)} sections + samples.js → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
