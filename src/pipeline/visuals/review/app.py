from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw

from src.pipeline.contracts import file_sha256

from ..common import iso_now
from .contract import VisualReviewRequest


def run(input_json: dict) -> dict:
    request = VisualReviewRequest.model_validate(input_json)
    output_dir = Path(request.config.output_dir).resolve()
    frames_dir = output_dir / "frames"
    contact_sheet_path = output_dir / "contact_sheet.jpg"

    if output_dir.exists() and request.config.force:
        shutil.rmtree(output_dir)
    if contact_sheet_path.exists() and not request.config.force:
        raise FileExistsError(
            f"Visual review already exists at {contact_sheet_path}. Set config.force=true to replace it."
        )
    frames_dir.mkdir(parents=True, exist_ok=True)

    assembly = request.input.video_assembly
    package = assembly.data.final_video_package
    video_path = Path(
        str(
            package.get("final_video_path")
            or assembly.handoff.get("final_video_path")
            or assembly.summary.get("final_video_path")
        )
    ).resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Final video does not exist: {video_path}")
    declared_video_hash = str(package.get("final_video_sha256") or "").strip()
    if not declared_video_hash:
        raise ValueError("Final video package is missing final_video_sha256")
    actual_video_hash = file_sha256(video_path)
    if actual_video_hash != declared_video_hash:
        raise ValueError("Final video does not match final_video_sha256")

    duration = _probe_duration(request.config.ffprobe_path, video_path)
    interval = max(0.1, duration / float(request.config.sample_count))
    frame_pattern = frames_dir / "frame_%03d.jpg"
    subprocess.run(
        [
            request.config.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{interval:.6f},scale={request.config.thumbnail_width}:-2",
            "-frames:v",
            str(request.config.sample_count),
            str(frame_pattern),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    frame_paths = sorted(frames_dir.glob("frame_*.jpg"))
    if not frame_paths:
        raise RuntimeError("ffmpeg did not produce contact-sheet frames")
    _compose_contact_sheet(
        frame_paths=frame_paths,
        output_path=contact_sheet_path,
        columns=request.config.columns,
        duration=duration,
        jpeg_quality=request.config.jpeg_quality,
    )
    if not request.config.keep_frames:
        shutil.rmtree(frames_dir)

    generated_at = iso_now()
    review_package = {
        "package_type": "visual_review_package",
        "run_id": request.run.run_id,
        "generated_at": generated_at,
        "final_video_path": str(video_path),
        "final_video_sha256": actual_video_hash,
        "contact_sheet_path": str(contact_sheet_path),
        "sample_count": len(frame_paths),
        "duration_seconds": round(duration, 3),
        "review_checklist": [
            "Does each frame represent the active narration beat?",
            "Are named people, products, and events visually correct?",
            "Are text and diagram labels readable at normal playback size?",
            "Are repeated visuals or long static stretches obvious?",
            "Does any source, logo, chart, or media asset look misleading?",
        ],
    }
    summary = {
        "sample_count": len(frame_paths),
        "duration_seconds": round(duration, 3),
        "contact_sheet_path": str(contact_sheet_path),
        "requires_manual_review": True,
    }
    result = {
        "status": "ok",
        "data": {
            "run_id": request.run.run_id,
            "generated_at": generated_at,
            "visual_review_package": review_package,
        },
        "summary": summary,
        "handoff": {
            "ready_for_human_visual_review": True,
            "contact_sheet_path": str(contact_sheet_path),
        },
    }
    (output_dir / "visual_review_package.json").write_text(
        json.dumps(review_package, indent=2), encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (output_dir / "visual_review_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def _probe_duration(ffprobe_path: str, video_path: Path) -> float:
    probe = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout or "{}")
    duration = float((payload.get("format") or {}).get("duration") or 0.0)
    if duration <= 0:
        raise ValueError("Final video duration could not be determined")
    return duration


def _compose_contact_sheet(
    *,
    frame_paths: list[Path],
    output_path: Path,
    columns: int,
    duration: float,
    jpeg_quality: int,
) -> None:
    frames = [Image.open(path).convert("RGB") for path in frame_paths]
    frame_width = max(frame.width for frame in frames)
    frame_height = max(frame.height for frame in frames)
    label_height = 36
    gutter = 10
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new(
        "RGB",
        (
            columns * frame_width + (columns + 1) * gutter,
            rows * (frame_height + label_height) + (rows + 1) * gutter,
        ),
        (10, 16, 27),
    )
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        row, column = divmod(index, columns)
        x = gutter + column * (frame_width + gutter)
        y = gutter + row * (frame_height + label_height + gutter)
        sheet.paste(frame, (x, y))
        timestamp = min(duration, (index + 0.5) * duration / len(frames))
        draw.text(
            (x + 8, y + frame_height + 8),
            f"{index + 1:02d}  {_format_timestamp(timestamp)}",
            fill=(235, 241, 248),
        )
        frame.close()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, format="JPEG", quality=jpeg_quality, optimize=True)


def _format_timestamp(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60:02d}:{whole % 60:02d}"
