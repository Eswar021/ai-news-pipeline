from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ..common import clean_text, counter_dict, iso_now, safe_float
from .config import NEXT_MODULE, PACKAGE_TYPE, QUALITY_PRESETS, default_remotion_engine_dir
from .contract import VisualRenderRequest, VisualRenderResponse


def run(input_json: dict) -> dict:
    request = VisualRenderRequest.model_validate(input_json)
    generated_at = iso_now()
    output_dir = Path(request.config.output_dir).resolve()
    result_path = output_dir / "visual_render_result.json"
    package_path = output_dir / "visual_render_package.json"
    summary_path = output_dir / "render_summary.json"

    if package_path.exists() and not request.config.force:
        raise FileExistsError(f"Visual render output already exists at {package_path}. Set config.force=true to replace it.")
    if request.config.force and output_dir.exists():
        shutil.rmtree(output_dir)

    scenes_dir = output_dir / "scenes"
    specs_dir = output_dir / "scene_specs"
    output_dir.mkdir(parents=True, exist_ok=True)
    scenes_dir.mkdir(parents=True, exist_ok=True)
    specs_dir.mkdir(parents=True, exist_ok=True)

    manifest = request.input.visual_asset_resolution.data.visual_asset_manifest
    render_settings = _resolved_render_settings(request)
    render_scenes = manifest.get("render_scenes", [])
    if request.config.scene_limit:
        render_scenes = render_scenes[: request.config.scene_limit]
    duration_cap = _max_scene_duration_cap(manifest, request)
    engine_dir = Path(request.config.remotion_engine_dir or default_remotion_engine_dir())
    rendered_scenes = _render_scenes(
        render_scenes=render_scenes,
        engine_dir=engine_dir,
        specs_dir=specs_dir,
        scenes_dir=scenes_dir,
        request=request,
        render_settings=render_settings,
        duration_cap=duration_cap,
    )

    failure_reason = _failure_reason(rendered_scenes)
    package = _build_package(
        run_id=request.run.run_id,
        generated_at=generated_at,
        output_dir=output_dir,
        manifest=manifest,
        rendered_scenes=rendered_scenes,
        render_settings=render_settings,
    )
    summary = _build_summary(rendered_scenes, len(render_scenes), str(output_dir), failure_reason, render_settings)
    status = _status_from_summary(summary)
    response = VisualRenderResponse(
        status=status,
        data={
            "run_id": request.run.run_id,
            "generated_at": generated_at,
            "visual_render_package": package,
        },
        summary=summary,
        handoff={
            "ready_for_video_assembly": status in {"ok", "partial"} and summary["failed_scene_count"] == 0,
            "next_module": NEXT_MODULE,
        },
    )
    result = response.model_dump(mode="json")
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _render_scenes(
    *,
    render_scenes: list[dict[str, Any]],
    engine_dir: Path,
    specs_dir: Path,
    scenes_dir: Path,
    request: VisualRenderRequest,
    render_settings: dict[str, Any],
    duration_cap: float | None,
) -> list[dict[str, Any]]:
    if not render_scenes:
        return []
    worker_count = max(1, min(int(request.config.worker_count), len(render_scenes)))
    if worker_count == 1:
        return [
            _render_one_scene(
                scene=scene,
                engine_dir=engine_dir,
                specs_dir=specs_dir,
                scenes_dir=scenes_dir,
                request=request,
                render_settings=render_settings,
                duration_cap=duration_cap,
            )
            for scene in render_scenes
        ]

    rendered_by_index: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _render_one_scene,
                scene=scene,
                engine_dir=engine_dir,
                specs_dir=specs_dir,
                scenes_dir=scenes_dir,
                request=request,
                render_settings=render_settings,
                duration_cap=duration_cap,
            ): index
            for index, scene in enumerate(render_scenes)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                rendered_by_index[index] = future.result()
            except Exception as exc:  # Defensive: one worker failure should be reported as one scene failure.
                scene = render_scenes[index]
                scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
                rendered_by_index[index] = _failed_scene(
                    scene,
                    specs_dir / f"{scene_id}.json",
                    scenes_dir / f"{scene_id}.mp4",
                    f"render worker failed: {exc}",
                )
    return [rendered_by_index[index] for index in range(len(render_scenes))]


def _render_one_scene(
    *,
    scene: dict[str, Any],
    engine_dir: Path,
    specs_dir: Path,
    scenes_dir: Path,
    request: VisualRenderRequest,
    render_settings: dict[str, Any],
    duration_cap: float | None,
) -> dict[str, Any]:
    scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
    spec_path = specs_dir / f"{scene_id}.json"
    output_path = scenes_dir / f"{scene_id}.mp4"
    scene_duration = safe_float(scene.get("duration_seconds"), 0.0)
    if duration_cap is not None and scene_duration > duration_cap + 0.01:
        return _failed_scene(
            scene,
            spec_path,
            output_path,
            f"scene duration {scene_duration:.2f}s exceeds render cap {duration_cap:.2f}s",
        )
    spec = _scene_render_spec(scene, request, render_settings)
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

    if not engine_dir.exists():
        return _failed_scene(scene, spec_path, output_path, f"Remotion engine dir does not exist: {engine_dir}")
    try:
        subprocess.run(
            [
                "npm",
                "run",
                "render-scene",
                "--",
                "--spec",
                str(spec_path),
                "--out",
                str(output_path),
            ],
            cwd=engine_dir,
            check=True,
            timeout=request.config.render_timeout_seconds,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        if _is_valid_rendered_video(output_path):
            return _rendered_scene(scene, spec_path, output_path, spec, f"Remotion returned an error but output video validated: {clean_text((exc.stderr or exc.stdout or str(exc))[-500:])}")
        return _failed_scene(scene, spec_path, output_path, (exc.stderr or exc.stdout or str(exc))[-2000:])
    except subprocess.TimeoutExpired as exc:
        if _is_valid_rendered_video(output_path):
            return _rendered_scene(scene, spec_path, output_path, spec, f"Render exceeded timeout after {exc.timeout} seconds, but output video validated.")
        return _failed_scene(scene, spec_path, output_path, f"render timeout after {exc.timeout} seconds")
    if not _is_valid_rendered_video(output_path):
        return _failed_scene(scene, spec_path, output_path, "Remotion completed but output video was not created or is invalid.")
    return _rendered_scene(scene, spec_path, output_path, spec)


def _rendered_scene(
    scene: dict[str, Any],
    spec_path: Path,
    output_path: Path,
    spec: dict[str, Any],
    warning: str = "",
) -> dict[str, Any]:
    return {
        "scene_id": clean_text(scene.get("scene_id", "scene_unknown")),
        "scene_order": scene.get("scene_order"),
        "render_kind": scene.get("render_kind"),
        "status": "rendered",
        "spec_path": str(spec_path),
        "output_path": str(output_path),
        "duration_seconds": spec["duration_seconds"],
        "error": "",
        "warning": clean_text(warning),
    }


def _is_valid_rendered_video(output_path: Path) -> bool:
    if not output_path.exists() or not output_path.is_file() or output_path.stat().st_size <= 0:
        return False
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration,width,height",
                "-of",
                "json",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(probe.stdout or "{}")
    except Exception:
        return False
    streams = data.get("streams") if isinstance(data, dict) else []
    if not streams:
        return False
    stream = streams[0]
    return safe_float(stream.get("duration"), 0.0) > 0 and safe_float(stream.get("width"), 0.0) > 0 and safe_float(stream.get("height"), 0.0) > 0


def _scene_render_spec(scene: dict[str, Any], request: VisualRenderRequest, render_settings: dict[str, Any]) -> dict[str, Any]:
    enriched = json.loads(json.dumps(scene))
    asset = enriched.get("resolved_asset") if isinstance(enriched.get("resolved_asset"), dict) else {}
    asset_path = clean_text(asset.get("asset_path", ""))
    if asset_path and clean_text(asset.get("asset_type", "")) != "broll_video":
        asset["asset_data_uri"] = _data_uri_for_path(Path(asset_path))
    duration = max(1.0, safe_float(enriched.get("duration_seconds"), 6.0))
    return {
        "width": render_settings["width"],
        "height": render_settings["height"],
        "fps": render_settings["fps"],
        "codec": request.config.codec,
        "crf": render_settings.get("crf"),
        "video_bitrate": render_settings.get("video_bitrate"),
        "x264_preset": render_settings.get("x264_preset"),
        "pixel_format": render_settings.get("pixel_format"),
        "duration_seconds": round(duration, 2),
        "scene": enriched,
    }


def _resolved_render_settings(request: VisualRenderRequest) -> dict[str, Any]:
    preset = QUALITY_PRESETS.get(request.config.quality_preset, {}) if request.config.quality_preset != "custom" else {}
    if request.config.quality_preset != "custom":
        width = int(preset.get("width", request.config.width))
        height = int(preset.get("height", request.config.height))
    else:
        width = request.config.width
        height = request.config.height
    return {
        "quality_preset": request.config.quality_preset,
        "width": int(width),
        "height": int(height),
        "fps": int(request.config.fps),
        "crf": request.config.crf if request.config.crf is not None else preset.get("crf"),
        "video_bitrate": request.config.video_bitrate,
        "x264_preset": request.config.x264_preset or preset.get("x264_preset"),
        "pixel_format": request.config.pixel_format or preset.get("pixel_format"),
        "worker_count": int(request.config.worker_count),
    }


def _max_scene_duration_cap(manifest: dict[str, Any], request: VisualRenderRequest) -> float | None:
    if request.config.max_scene_duration_seconds is not None:
        return safe_float(request.config.max_scene_duration_seconds, None)
    plan = manifest.get("visual_scene_plan") if isinstance(manifest.get("visual_scene_plan"), dict) else {}
    policy = plan.get("scene_policy") if isinstance(plan.get("scene_policy"), dict) else {}
    cap = safe_float(policy.get("max_scene_seconds"), 0.0)
    if cap <= 0:
        return None
    return cap


def _data_uri_for_path(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _failed_scene(scene: dict[str, Any], spec_path: Path, output_path: Path, error: str) -> dict[str, Any]:
    return {
        "scene_id": clean_text(scene.get("scene_id", "scene_unknown")),
        "scene_order": scene.get("scene_order"),
        "render_kind": scene.get("render_kind"),
        "status": "failed",
        "spec_path": str(spec_path),
        "output_path": str(output_path),
        "duration_seconds": safe_float(scene.get("duration_seconds"), 0.0),
        "error": clean_text(error),
    }


def _build_package(
    *,
    run_id: str,
    generated_at: str,
    output_dir: Path,
    manifest: dict[str, Any],
    rendered_scenes: list[dict[str, Any]],
    render_settings: dict[str, Any],
) -> dict[str, Any]:
    return {
        "package_type": PACKAGE_TYPE,
        "run_id": run_id,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "render_settings": render_settings,
        "visual_asset_manifest": manifest,
        "rendered_scenes": rendered_scenes,
    }


def _build_summary(
    rendered_scenes: list[dict[str, Any]],
    requested_scene_count: int,
    output_dir: str,
    failure_reason: str,
    render_settings: dict[str, Any],
) -> dict[str, Any]:
    failed = [scene for scene in rendered_scenes if scene.get("status") == "failed"]
    return {
        "requested_scene_count": requested_scene_count,
        "rendered_scene_count": len([scene for scene in rendered_scenes if scene.get("status") == "rendered"]),
        "failed_scene_count": len(failed),
        "warning_count": len([scene for scene in rendered_scenes if clean_text(scene.get("warning", ""))]),
        "render_kind_counts": counter_dict([clean_text(scene.get("render_kind", "")) for scene in rendered_scenes]),
        "status_counts": counter_dict([clean_text(scene.get("status", "")) for scene in rendered_scenes]),
        "output_dir": output_dir,
        "render_settings": render_settings,
        "failure_reason": failure_reason,
    }


def _failure_reason(rendered_scenes: list[dict[str, Any]]) -> str:
    failures = [scene for scene in rendered_scenes if scene.get("status") == "failed"]
    if not failures:
        return ""
    return "; ".join(f"{scene.get('scene_id')}: {scene.get('error')}" for scene in failures[:3])


def _status_from_summary(summary: dict[str, Any]) -> str:
    requested = summary["requested_scene_count"]
    failed = summary["failed_scene_count"]
    if requested == 0 or failed == requested:
        return "failed"
    if failed:
        return "partial"
    return "ok"
