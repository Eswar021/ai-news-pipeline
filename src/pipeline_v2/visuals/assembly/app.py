from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ..common import clean_text, iso_now, safe_float
from .config import PACKAGE_TYPE
from .contract import VideoAssemblyRequest, VideoAssemblyResponse


def run(input_json: dict) -> dict:
    request = VideoAssemblyRequest.model_validate(input_json)
    generated_at = iso_now()
    output_dir = Path(request.config.output_dir).resolve()
    result_path = output_dir / "video_assembly_result.json"
    package_path = output_dir / "final_video_package.json"
    summary_path = output_dir / "assembly_summary.json"
    concat_list_path = output_dir / "scene_concat_list.txt"
    final_video_path = output_dir / request.config.final_video_filename

    if final_video_path.exists() and not request.config.force:
        raise FileExistsError(f"Final video already exists at {final_video_path}. Set config.force=true to replace it.")
    if request.config.force and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    visual_package = request.input.visual_render.data.visual_render_package
    voiceover_package = _normalize_voiceover_package(request.input.voiceover)
    rendered_scenes = _rendered_scenes(visual_package)
    audio_path = _voiceover_audio_path(voiceover_package)
    failure_reason = _preflight_failure_reason(rendered_scenes, audio_path)

    command: list[str] = []
    fallback_command: list[str] = []
    ffmpeg_stderr = ""
    fallback_used = False
    if not failure_reason:
        _write_concat_list(concat_list_path, rendered_scenes)
        command = _ffmpeg_command(request, concat_list_path, audio_path, final_video_path, reencode=False)
        run_result = _run_command(command, output_dir)
        ffmpeg_stderr = run_result["stderr"]
        if run_result["returncode"] != 0 and request.config.allow_reencode_fallback:
            if final_video_path.exists():
                final_video_path.unlink()
            fallback_used = True
            fallback_command = _ffmpeg_command(request, concat_list_path, audio_path, final_video_path, reencode=True)
            run_result = _run_command(fallback_command, output_dir)
            ffmpeg_stderr = run_result["stderr"]
        if run_result["returncode"] != 0:
            failure_reason = (ffmpeg_stderr or run_result["stdout"] or "ffmpeg failed")[-2000:]
        elif not final_video_path.exists():
            failure_reason = "ffmpeg completed but final video was not created"

    visual_duration = round(sum(safe_float(scene.get("duration_seconds"), 0.0) for scene in rendered_scenes), 2)
    audio_duration = safe_float((voiceover_package.get("audio") or {}).get("duration_seconds"), 0.0)
    if audio_duration <= 0 and audio_path:
        audio_duration = _probe_duration(request.config.ffprobe_path, audio_path)
    final_duration = _probe_duration(request.config.ffprobe_path, final_video_path) if final_video_path.exists() else 0.0
    delta = abs(final_duration - audio_duration) if final_duration and audio_duration else 0.0
    if not failure_reason and delta > request.config.duration_tolerance_seconds:
        failure_reason = (
            f"Final video duration differs from voiceover by {delta:.2f}s "
            f"(tolerance {request.config.duration_tolerance_seconds:.2f}s)"
        )

    status = "failed" if failure_reason else "ok"
    package = _build_package(
        run_id=request.run.run_id,
        generated_at=generated_at,
        output_dir=output_dir,
        final_video_path=final_video_path,
        concat_list_path=concat_list_path,
        rendered_scenes=rendered_scenes,
        voiceover_package=voiceover_package,
        command=command,
        fallback_command=fallback_command,
        fallback_used=fallback_used,
        audio_encoding={
            "codec": request.config.audio_codec,
            "bitrate": request.config.audio_bitrate,
            "sample_rate_hz": request.config.audio_sample_rate_hz,
            "channels": request.config.audio_channels,
        },
    )
    summary = {
        "assembled_scene_count": len(rendered_scenes),
        "audio_duration_seconds": round(audio_duration, 2),
        "visual_duration_seconds": visual_duration,
        "final_duration_seconds": round(final_duration, 2),
        "duration_delta_seconds": round(delta, 2),
        "output_dir": str(output_dir),
        "final_video_path": str(final_video_path) if final_video_path.exists() else "",
        "failure_reason": failure_reason,
    }
    response = VideoAssemblyResponse(
        status=status,
        data={
            "run_id": request.run.run_id,
            "generated_at": generated_at,
            "final_video_package": package,
        },
        summary=summary,
        handoff={
            "ready_for_manual_review": status == "ok",
            "final_video_path": summary["final_video_path"],
        },
    )
    result = response.model_dump(mode="json")
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _normalize_voiceover_package(value: dict[str, Any]) -> dict[str, Any]:
    if "data" in value and isinstance(value.get("data"), dict):
        package = value["data"].get("voiceover_package")
        if isinstance(package, dict):
            return package
    if value.get("package_type") == "voiceover_package":
        return value
    package = value.get("voiceover_package")
    if isinstance(package, dict):
        return package
    return value


def _rendered_scenes(visual_package: dict[str, Any]) -> list[dict[str, Any]]:
    scenes = [
        scene
        for scene in visual_package.get("rendered_scenes", [])
        if isinstance(scene, dict)
    ]
    return sorted(scenes, key=lambda scene: int(scene.get("scene_order") or 999999))


def _voiceover_audio_path(voiceover_package: dict[str, Any]) -> Path:
    audio = voiceover_package.get("audio") if isinstance(voiceover_package.get("audio"), dict) else {}
    path = clean_text(audio.get("full_audio_path") or audio.get("audio_path") or "")
    return Path(path).resolve() if path else Path("__missing_voiceover_audio__").resolve()


def _preflight_failure_reason(rendered_scenes: list[dict[str, Any]], audio_path: Path) -> str:
    if not rendered_scenes:
        return "No rendered scenes were provided."
    failed = [scene for scene in rendered_scenes if scene.get("status") != "rendered"]
    if failed:
        return f"Rendered scenes include failed/non-rendered entries: {[scene.get('scene_id') for scene in failed[:10]]}"
    missing = [
        clean_text(scene.get("output_path", ""))
        for scene in rendered_scenes
        if not Path(clean_text(scene.get("output_path", ""))).exists()
    ]
    if missing:
        return f"Rendered scene files are missing: {missing[:5]}"
    if not audio_path.exists():
        return f"Voiceover audio file does not exist: {audio_path}"
    return ""


def _write_concat_list(path: Path, rendered_scenes: list[dict[str, Any]]) -> None:
    lines = []
    for scene in rendered_scenes:
        scene_path = Path(clean_text(scene.get("output_path", ""))).resolve()
        escaped = str(scene_path).replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"file '{escaped}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ffmpeg_command(
    request: VideoAssemblyRequest,
    concat_list_path: Path,
    audio_path: Path,
    final_video_path: Path,
    *,
    reencode: bool,
) -> list[str]:
    command = [
        request.config.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
    ]
    if reencode:
        command += [
            "-c:v",
            request.config.reencode_video_codec,
            "-preset",
            request.config.reencode_preset,
            "-crf",
            str(request.config.reencode_crf),
            "-pix_fmt",
            request.config.pixel_format,
        ]
    else:
        command += ["-c:v", request.config.video_codec]
    command += [
        "-c:a",
        request.config.audio_codec,
        "-b:a",
        request.config.audio_bitrate,
        "-ar",
        str(request.config.audio_sample_rate_hz),
        "-ac",
        str(request.config.audio_channels),
    ]
    if request.config.shortest:
        command.append("-shortest")
    if request.config.movflags_faststart:
        command += ["-movflags", "+faststart"]
    command.append(str(final_video_path))
    return command


def _run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _probe_duration(ffprobe_path: str, path: Path) -> float:
    if not path.exists():
        return 0.0
    completed = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return 0.0
    return safe_float(completed.stdout.strip(), 0.0)


def _build_package(
    *,
    run_id: str,
    generated_at: str,
    output_dir: Path,
    final_video_path: Path,
    concat_list_path: Path,
    rendered_scenes: list[dict[str, Any]],
    voiceover_package: dict[str, Any],
    command: list[str],
    fallback_command: list[str],
    fallback_used: bool,
    audio_encoding: dict[str, Any],
) -> dict[str, Any]:
    return {
        "package_type": PACKAGE_TYPE,
        "run_id": run_id,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "final_video_path": str(final_video_path) if final_video_path.exists() else "",
        "concat_list_path": str(concat_list_path),
        "scene_count": len(rendered_scenes),
        "scene_paths": [clean_text(scene.get("output_path", "")) for scene in rendered_scenes],
        "voiceover_audio_path": clean_text(
            (voiceover_package.get("audio") or {}).get("full_audio_path")
            or (voiceover_package.get("audio") or {}).get("audio_path")
            or ""
        ),
        "ffmpeg_command": command,
        "fallback_ffmpeg_command": fallback_command,
        "fallback_used": fallback_used,
        "audio_encoding": audio_encoding,
    }
