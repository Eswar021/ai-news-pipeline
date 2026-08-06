"""Diagnostic: isolate why the OpenAI voices sound rough — is it the speed param,
the instructions, or the model? Generates a small labeled comparison set.

    .venv-voiceover/bin/python labs/generate_voice_experiment.py
"""
from __future__ import annotations

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
INSTR = "Energetic, curious tech-explainer host with a skeptical eyebrow. Confident, warm, a little wry."
OUT = ROOT / "labs" / "voices"

# (model, voice, speed, use_instructions, label) — isolates each variable.
VARIANTS = [
    ("gpt-4o-mini-tts", "cedar", 1.0, False, "mini_cedar_s100_plain"),   # baseline
    ("gpt-4o-mini-tts", "cedar", 1.08, False, "mini_cedar_s108_plain"),  # + speed (the suspect)
    ("gpt-4o-mini-tts", "cedar", 1.0, True, "mini_cedar_s100_instr"),    # + instructions
    ("tts-1-hd", "nova", 1.0, False, "hd_nova"),                          # quality model
    ("tts-1-hd", "shimmer", 1.0, False, "hd_shimmer"),
    ("tts-1", "alloy", 1.0, False, "tts1_alloy"),                         # fast/reference model
]


def wrap_pcm(pcm: bytes, path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)


def main() -> None:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY_A_C_C")
    client = OpenAI(api_key=key)
    OUT.mkdir(parents=True, exist_ok=True)
    for model, voice, speed, use_instr, label in VARIANTS:
        kwargs: dict = {"model": model, "voice": voice, "input": LINE, "response_format": "pcm"}
        if use_instr and model == "gpt-4o-mini-tts":
            kwargs["instructions"] = INSTR
        if speed != 1.0:
            kwargs["speed"] = speed
        try:
            pcm = client.audio.speech.create(**kwargs).content
            wav = OUT / f"exp_{label}.wav"
            wrap_pcm(pcm, wav)
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-codec:a", "libmp3lame",
                 "-q:a", "3", str(OUT / f"exp_{label}.mp3")],
                check=False,
            )
            print(f"  ok   {label:26s} {model} / {voice} / speed={speed} / instr={use_instr}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {label:26s} {type(exc).__name__}: {str(exc)[:90]}")


if __name__ == "__main__":
    main()
