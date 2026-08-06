"""labs/voices — generate the same representative line in each candidate voice, so
the production voice can be chosen by ear (and later previewed in the UI).

Run with the voiceover venv (it has the TTS SDKs):
    .venv-voiceover/bin/python labs/generate_voice_samples.py

Writes labs/voices/<id>.wav + manifest.json. Best-effort per voice — an unsupported
voice or a provider error is skipped, not fatal.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from src.pipeline.voiceover.providers.openai_tts import synthesize_chunks_to_wav  # noqa: E402

# A real channel-style line (hook + payoff) so each voice is judged on our content.
SAMPLE_LINE = (
    "A tool built to stop fraud just became the fraud, and nobody caught it for a year. "
    "That's the strangest thing in AI this week, and the one that should worry you most."
)
INSTRUCTIONS = (
    "Energetic, curious tech-explainer host with a skeptical eyebrow. Confident and warm, "
    "a little wry. Punch the hook, stay conversational, never a television-news cadence."
)
# Curated diverse set of gpt-4o-mini-tts voices (cedar is today's default).
OPENAI_VOICES = ["cedar", "marin", "coral", "ash", "ballad", "sage", "verse", "onyx"]

OUT = ROOT / "labs" / "voices"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for voice in OPENAI_VOICES:
        chunk_id = f"openai_{voice}"
        try:
            synthesize_chunks_to_wav(
                chunks=[{"chunk_id": chunk_id, "text": SAMPLE_LINE}],
                output_dir=OUT,
                model="gpt-4o-mini-tts",
                voice=voice,
                instructions=INSTRUCTIONS,
                speed=1.08,
                response_format="wav",
                api_key_envs=["OPENAI_API_KEY", "OPENAI_API_KEY_A_C_C"],
                request_timeout_seconds=60,
                max_retries=2,
                retry_initial_delay_seconds=1.0,
                retry_max_delay_seconds=8.0,
                worker_count=1,
                max_input_chars=2000,
                sample_rate_hz=24000,
            )
            # Also emit an MP3 for the browser preview (universal playback, small).
            if shutil.which("ffmpeg"):
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y", "-i", str(OUT / f"{chunk_id}.wav"),
                     "-codec:a", "libmp3lame", "-q:a", "3", str(OUT / f"{chunk_id}.mp3")],
                    check=False,
                )
            print(f"  ok  openai/{voice}")
            manifest.append({
                "id": chunk_id, "provider": "openai", "model": "gpt-4o-mini-tts",
                "voice": voice, "file": f"{chunk_id}.wav", "preview": f"{chunk_id}.mp3",
                "note": "current default" if voice == "cedar" else "",
            })
        except Exception as exc:  # noqa: BLE001 — one bad voice never stops the lab
            print(f"  skip openai/{voice}: {type(exc).__name__}: {str(exc)[:90]}")
    (OUT / "manifest.json").write_text(
        json.dumps({"line": SAMPLE_LINE, "instructions": INSTRUCTIONS, "voices": manifest}, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {len(manifest)} voice sample(s) + manifest → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
