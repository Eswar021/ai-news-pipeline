from __future__ import annotations

import math
from pathlib import Path
import shutil
import struct
import wave

import pytest

from src.pipeline.contracts import voiceover_artifact_payload
from src.pipeline.voiceover.audio_postprocess import master_audio
from src.pipeline.voiceover.captions import write_caption_files


def test_caption_files_preserve_aligned_beat_timing(tmp_path: Path) -> None:
    result = write_caption_files(
        audio_units=[
            {
                "audio_unit_id": "unit_01",
                "section_id": "section_01",
                "story_id": "story_01",
                "aligned_beats": [
                    {
                        "beat_id": "beat_01",
                        "section_id": "section_01",
                        "story_id": "story_01",
                        "text": (
                            "OpenAI introduced a smaller model for teams that need faster, "
                            "lower-cost inference without changing their entire workflow."
                        ),
                        "start_seconds": 1.25,
                        "end_seconds": 6.75,
                    }
                ],
            }
        ],
        output_dir=tmp_path / "captions",
        config={
            "enabled": True,
            "formats": ["srt", "vtt"],
            "max_chars_per_cue": 42,
            "max_words_per_cue": 9,
            "min_cue_seconds": 0.8,
        },
    )

    assert result["status"] == "ready"
    assert result["cue_count"] >= 2
    srt = (tmp_path / "captions" / "captions.srt").read_text(encoding="utf-8")
    vtt = (tmp_path / "captions" / "captions.vtt").read_text(encoding="utf-8")
    assert "00:00:01,250 -->" in srt
    assert "--> 00:00:06,750" in srt
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:01.250 -->" in vtt
    assert "--> 00:00:06.750" in vtt
    assert all(Path(item["path"]).exists() for item in result["files"])


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_audio_mastering_hits_target_without_timing_drift(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.wav"
    mastered_path = tmp_path / "mastered.wav"
    _write_sine_wave(raw_path, duration_seconds=2.0, amplitude=0.035)

    result = master_audio(
        input_path=raw_path,
        output_path=mastered_path,
        sample_rate_hz=24_000,
        config={
            "enabled": True,
            "ffmpeg_path": "ffmpeg",
            "target_lufs": -16.0,
            "true_peak_db": -1.0,
            "loudness_range_lu": 7.0,
            "two_pass": True,
            "measure_output": True,
            "keep_raw_audio": True,
            "duration_tolerance_seconds": 0.08,
            "failure_mode": "fail",
        },
    )

    assert result["status"] == "mastered"
    assert mastered_path.exists()
    assert result["duration_delta_seconds"] <= 0.08
    assert result["output_measurement"]["integrated_lufs"] == pytest.approx(-16.0, abs=1.0)
    assert result["output_measurement"]["true_peak_db"] <= -0.5


def test_voiceover_identity_excludes_machine_specific_caption_and_audio_paths() -> None:
    base = {
        "provider": "kokoro_local",
        "voice": "af_heart",
        "style": {"name": "general_youtube"},
        "audio": {
            "sample_rate_hz": 24_000,
            "duration_seconds": 12.0,
            "mastering": {
                "status": "mastered",
                "target_lufs": -16.0,
                "input_path": "/machine-a/raw.wav",
                "output_path": "/machine-a/full.wav",
            },
        },
        "captions": {
            "enabled": True,
            "status": "ready",
            "cue_count": 3,
            "files": [
                {
                    "format": "srt",
                    "path": "/machine-a/captions.srt",
                    "sha256": "caption-hash",
                }
            ],
        },
        "audio_units": [],
        "provenance": {"audio_sha256": "audio-hash"},
    }
    moved = {
        **base,
        "audio": {
            **base["audio"],
            "mastering": {
                **base["audio"]["mastering"],
                "input_path": "/machine-b/raw.wav",
                "output_path": "/machine-b/full.wav",
            },
        },
        "captions": {
            **base["captions"],
            "files": [
                {
                    **base["captions"]["files"][0],
                    "path": "/machine-b/captions.srt",
                }
            ],
        },
    }

    assert voiceover_artifact_payload(base) == voiceover_artifact_payload(moved)


def _write_sine_wave(path: Path, *, duration_seconds: float, amplitude: float) -> None:
    sample_rate = 24_000
    frame_count = round(duration_seconds * sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for frame_index in range(frame_count):
            sample = amplitude * math.sin(2 * math.pi * 220 * frame_index / sample_rate)
            frames.extend(struct.pack("<h", round(sample * 32_767)))
        handle.writeframes(bytes(frames))
