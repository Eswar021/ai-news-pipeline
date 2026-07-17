from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import wave
from typing import Any


_LOUDNORM_JSON_RE = re.compile(r"\{\s*\"input_i\".*?\}", re.DOTALL)


def master_audio(
    *,
    input_path: Path,
    output_path: Path,
    sample_rate_hz: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    if not input_path.exists() or input_path.stat().st_size <= 0:
        raise FileNotFoundError(f"Raw voiceover audio is missing or empty: {input_path}")

    if not bool(config.get("enabled", False)):
        if input_path != output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(input_path), str(output_path))
        return {
            "enabled": False,
            "status": "bypassed",
            "input_path": str(output_path),
            "output_path": str(output_path),
            "duration_seconds": round(_wav_duration_seconds(output_path), 3),
        }

    ffmpeg_path = str(config.get("ffmpeg_path") or "ffmpeg")
    target_lufs = float(config.get("target_lufs", -16.0))
    true_peak_db = float(config.get("true_peak_db", -1.0))
    loudness_range_lu = float(config.get("loudness_range_lu", 7.0))
    duration_tolerance = float(config.get("duration_tolerance_seconds", 0.08))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        input_measurement = _measure_loudness(
            input_path,
            ffmpeg_path=ffmpeg_path,
            target_lufs=target_lufs,
            true_peak_db=true_peak_db,
            loudness_range_lu=loudness_range_lu,
        )
        loudnorm_filter = _loudnorm_filter(
            target_lufs=target_lufs,
            true_peak_db=true_peak_db,
            loudness_range_lu=loudness_range_lu,
            measurement=input_measurement if bool(config.get("two_pass", True)) else None,
        )
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-af",
            loudnorm_filter,
            "-ar",
            str(sample_rate_hz),
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "ffmpeg mastering failed")[-2000:])
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise RuntimeError("ffmpeg mastering completed without a usable WAV output")

        input_duration = _wav_duration_seconds(input_path)
        output_duration = _wav_duration_seconds(output_path)
        duration_delta = abs(output_duration - input_duration)
        if duration_delta > duration_tolerance:
            raise RuntimeError(
                "Mastered audio duration changed beyond tolerance: "
                f"input={input_duration:.3f}s output={output_duration:.3f}s "
                f"delta={duration_delta:.3f}s tolerance={duration_tolerance:.3f}s"
            )

        output_measurement = {}
        if bool(config.get("measure_output", True)):
            output_measurement = _measure_loudness(
                output_path,
                ffmpeg_path=ffmpeg_path,
                target_lufs=target_lufs,
                true_peak_db=true_peak_db,
                loudness_range_lu=loudness_range_lu,
            )

        if not bool(config.get("keep_raw_audio", False)) and input_path != output_path:
            input_path.unlink(missing_ok=True)

        return {
            "enabled": True,
            "status": "mastered",
            "input_path": str(input_path) if input_path.exists() else "",
            "output_path": str(output_path),
            "target_lufs": target_lufs,
            "true_peak_db": true_peak_db,
            "loudness_range_lu": loudness_range_lu,
            "two_pass": bool(config.get("two_pass", True)),
            "input_measurement": input_measurement,
            "output_measurement": output_measurement,
            "duration_seconds": round(output_duration, 3),
            "duration_delta_seconds": round(duration_delta, 4),
        }
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        if str(config.get("failure_mode") or "fail") != "use_unmastered":
            raise
        shutil.copy2(input_path, output_path)
        return {
            "enabled": True,
            "status": "unmastered_fallback",
            "input_path": str(input_path),
            "output_path": str(output_path),
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(_wav_duration_seconds(output_path), 3),
        }


def _measure_loudness(
    path: Path,
    *,
    ffmpeg_path: str,
    target_lufs: float,
    true_peak_db: float,
    loudness_range_lu: float,
) -> dict[str, float]:
    filter_value = (
        f"loudnorm=I={target_lufs}:TP={true_peak_db}:"
        f"LRA={loudness_range_lu}:print_format=json"
    )
    completed = subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            filter_value,
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "ffmpeg loudness analysis failed")[-2000:])
    matches = _LOUDNORM_JSON_RE.findall(completed.stderr or "")
    if not matches:
        raise RuntimeError("ffmpeg loudness analysis did not return loudnorm JSON")
    raw = json.loads(matches[-1])
    return {
        "integrated_lufs": _float_value(raw.get("input_i")),
        "true_peak_db": _float_value(raw.get("input_tp")),
        "loudness_range_lu": _float_value(raw.get("input_lra")),
        "threshold_lufs": _float_value(raw.get("input_thresh")),
        "target_offset_lu": _float_value(raw.get("target_offset")),
    }


def _loudnorm_filter(
    *,
    target_lufs: float,
    true_peak_db: float,
    loudness_range_lu: float,
    measurement: dict[str, float] | None,
) -> str:
    parts = [
        f"I={target_lufs}",
        f"TP={true_peak_db}",
        f"LRA={loudness_range_lu}",
    ]
    if measurement:
        parts.extend(
            [
                f"measured_I={measurement['integrated_lufs']}",
                f"measured_TP={measurement['true_peak_db']}",
                f"measured_LRA={measurement['loudness_range_lu']}",
                f"measured_thresh={measurement['threshold_lufs']}",
                f"offset={measurement['target_offset_lu']}",
                "linear=true",
            ]
        )
    parts.append("print_format=summary")
    return f"loudnorm={':'.join(parts)}"


def _wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        frame_rate = handle.getframerate()
        return handle.getnframes() / frame_rate if frame_rate else 0.0


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid loudness measurement value: {value!r}") from exc
