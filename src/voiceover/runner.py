from __future__ import annotations

import argparse
import sys

from src.voiceover.audition import audition_voices
from src.voiceover.config import DEFAULT_AUDITION_TEXT, DEFAULT_PROVIDER, DEFAULT_STYLE, KNOWN_PROVIDERS, VOICEOVER_STYLES
from src.voiceover.synthesizer import generate_voiceover


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local voiceover audio from an approved L8 script.")
    parser.add_argument("--run-id", default="current", help="Run id to synthesize, or 'current'.")
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        choices=sorted(KNOWN_PROVIDERS),
        help="Voiceover provider. Only kokoro_local is implemented in v1.",
    )
    parser.add_argument(
        "--style",
        default=DEFAULT_STYLE,
        choices=sorted(VOICEOVER_STYLES),
        help="Voiceover style profile.",
    )
    parser.add_argument("--voice", default=None, help="Provider voice id. Defaults to the selected style voice.")
    parser.add_argument("--speed", type=float, default=None, help="Speech speed multiplier. Defaults to the style speed.")
    parser.add_argument(
        "--keep-chunks",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep per-chunk WAV files after building the full voiceover.",
    )
    parser.add_argument("--audition", action="store_true", help="Generate short voice samples instead of a full run voiceover.")
    parser.add_argument(
        "--voices",
        default="",
        help="Comma-separated voice ids for --audition. Defaults to the built-in audition voice list.",
    )
    parser.add_argument("--audition-text", default=DEFAULT_AUDITION_TEXT, help="Text to use for --audition samples.")
    parser.add_argument("--force", action="store_true", help="Replace an existing voiceover package for this run.")
    args = parser.parse_args()

    try:
        if args.audition:
            voices = [voice.strip() for voice in args.voices.split(",") if voice.strip()] or None
            print(f"[voiceover] Audition: style={args.style}", flush=True)
            manifest = audition_voices(
                style=args.style,
                voices=voices,
                text=args.audition_text,
                force=args.force,
            )
            print(
                "[voiceover] Audition ready: "
                f"samples={len(manifest['samples'])}  "
                f"failures={len(manifest['failures'])}"
            )
            return

        print(f"[voiceover] Run: {args.run_id}", flush=True)
        print(
            "[voiceover] "
            f"Provider: {args.provider}  style={args.style}  "
            f"voice={args.voice or 'style_default'}  speed={args.speed or 'style_default'}",
            flush=True,
        )
        package = generate_voiceover(
            run_id=args.run_id,
            provider=args.provider,
            voice=args.voice,
            speed=args.speed,
            style=args.style,
            keep_chunks=args.keep_chunks,
            force=args.force,
        )
    except (FileExistsError, FileNotFoundError, KeyError, NotImplementedError, RuntimeError, ValueError) as exc:
        print(f"[voiceover] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    print(
        "[voiceover] Ready: "
        f"{package['audio']['full_audio_path']}  "
        f"duration={package['audio']['duration_seconds']}s  "
        f"chunks={len(package['chunks'])}"
    )


if __name__ == "__main__":
    main()
