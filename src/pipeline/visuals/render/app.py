from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic
from typing import Any

from src.pipeline.contracts import (
    build_artifact_provenance,
    require_matching_run_id,
    validate_artifact_provenance,
)

from ..common import clean_text, counter_dict, iso_now, safe_float
from .config import NEXT_MODULE, PACKAGE_TYPE, QUALITY_PRESETS, default_remotion_engine_dir
from .contract import VisualRenderRequest, VisualRenderResponse


_RETRY_LOCK = Lock()


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
    require_matching_run_id(
        request.run.run_id,
        request.input.visual_asset_resolution.data.run_id,
        "visual_asset_resolution",
    )
    require_matching_run_id(request.run.run_id, manifest.get("run_id"), "visual_asset_manifest")
    asset_provenance = _required_asset_provenance(manifest, request.run.run_id)
    render_settings = _resolved_render_settings(request)
    render_scenes = manifest.get("render_scenes", [])
    if request.config.scene_limit:
        render_scenes = render_scenes[: request.config.scene_limit]
    duration_cap = _max_scene_duration_cap(manifest, request)
    engine_dir = Path(request.config.remotion_engine_dir or default_remotion_engine_dir())
    render_started = monotonic()
    rendered_scenes = _render_scenes(
        render_scenes=render_scenes,
        engine_dir=engine_dir,
        specs_dir=specs_dir,
        scenes_dir=scenes_dir,
        request=request,
        render_settings=render_settings,
        duration_cap=duration_cap,
    )
    render_elapsed_seconds = round(monotonic() - render_started, 2)

    failure_reason = _failure_reason(rendered_scenes)
    package = _build_package(
        run_id=request.run.run_id,
        generated_at=generated_at,
        output_dir=output_dir,
        manifest=manifest,
        rendered_scenes=rendered_scenes,
        render_settings=render_settings,
        asset_provenance=asset_provenance,
    )
    summary = _build_summary(
        rendered_scenes,
        len(render_scenes),
        str(output_dir),
        failure_reason,
        render_settings,
        render_elapsed_seconds,
    )
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
    logs_dir = specs_dir.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    rendered_by_index: dict[int, dict[str, Any]] = {}

    with TemporaryDirectory(prefix="pipeline-remotion-render-") as runtime_dir_value:
        runtime_dir = Path(runtime_dir_value)
        public_dir = runtime_dir / "public"
        bundle_dir = runtime_dir / "bundle"
        public_dir.mkdir(parents=True, exist_ok=True)
        jobs: list[dict[str, Any]] = []

        for index, scene in enumerate(render_scenes):
            scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
            spec_path = specs_dir / f"{scene_id}.json"
            output_path = scenes_dir / f"{scene_id}.mp4"
            scene_duration = safe_float(scene.get("duration_seconds"), 0.0)
            if duration_cap is not None and scene_duration > duration_cap + 0.01:
                rendered_by_index[index] = _failed_scene(
                    scene,
                    spec_path,
                    output_path,
                    f"scene duration {scene_duration:.2f}s exceeds render cap {duration_cap:.2f}s",
                )
                continue
            try:
                spec = _scene_render_spec(scene, request, render_settings)
                _prepare_shared_runtime_asset(spec, public_dir)
                spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as exc:
                rendered_by_index[index] = _failed_scene(
                    scene,
                    spec_path,
                    output_path,
                    f"could not prepare scene render spec: {exc}",
                )
                continue
            jobs.append(
                {
                    "index": index,
                    "scene": scene,
                    "spec": spec,
                    "spec_path": spec_path,
                    "output_path": output_path,
                }
            )

        if jobs:
            bundle_error, bundle_log_path = _build_shared_bundle(
                engine_dir=engine_dir,
                public_dir=public_dir,
                bundle_dir=bundle_dir,
                logs_dir=logs_dir,
                request=request,
            )
            if bundle_error:
                for job in jobs:
                    rendered_by_index[job["index"]] = _failed_scene(
                        job["scene"],
                        job["spec_path"],
                        job["output_path"],
                        bundle_error,
                        log_paths=[str(bundle_log_path)] if bundle_log_path else [],
                    )
            else:
                rendered_by_index.update(
                    _render_prepared_jobs(
                        jobs=jobs,
                        engine_dir=engine_dir,
                        bundle_dir=bundle_dir,
                        logs_dir=logs_dir,
                        request=request,
                    )
                )

    return [rendered_by_index[index] for index in range(len(render_scenes))]


def _render_prepared_jobs(
    *,
    jobs: list[dict[str, Any]],
    engine_dir: Path,
    bundle_dir: Path,
    logs_dir: Path,
    request: VisualRenderRequest,
) -> dict[int, dict[str, Any]]:
    worker_count = max(1, min(int(request.config.worker_count), len(jobs)))
    if worker_count == 1:
        return {
            job["index"]: _render_prepared_scene(
                job=job,
                engine_dir=engine_dir,
                bundle_dir=bundle_dir,
                logs_dir=logs_dir,
                request=request,
            )
            for job in jobs
        }

    rendered_by_index: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_job = {
            executor.submit(
                _render_prepared_scene,
                job=job,
                engine_dir=engine_dir,
                bundle_dir=bundle_dir,
                logs_dir=logs_dir,
                request=request,
            ): job
            for job in jobs
        }
        for future in as_completed(future_to_job):
            job = future_to_job[future]
            try:
                rendered_by_index[job["index"]] = future.result()
            except Exception as exc:  # One worker failure should not hide other scene results.
                rendered_by_index[job["index"]] = _failed_scene(
                    job["scene"],
                    job["spec_path"],
                    job["output_path"],
                    f"render worker failed: {exc}",
                )
    return rendered_by_index


def _render_prepared_scene(
    *,
    job: dict[str, Any],
    engine_dir: Path,
    bundle_dir: Path,
    logs_dir: Path,
    request: VisualRenderRequest,
) -> dict[str, Any]:
    scene = job["scene"]
    spec = job["spec"]
    spec_path = job["spec_path"]
    output_path = job["output_path"]
    scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
    log_paths: list[str] = []
    last_error = "Remotion did not render the scene."

    for attempt in range(1, int(request.config.max_render_attempts) + 1):
        retry_context = _RETRY_LOCK if attempt > 1 else nullcontext()
        with retry_context:
            output_path.unlink(missing_ok=True)
            command = [
                "npm",
                "run",
                "render-scene",
                "--",
                "--spec",
                str(spec_path),
                "--out",
                str(output_path),
                "--serve-url",
                str(bundle_dir),
            ]
            completed: subprocess.CompletedProcess[str] | None = None
            process_error = ""
            try:
                completed = subprocess.run(
                    command,
                    cwd=engine_dir,
                    check=True,
                    timeout=request.config.render_timeout_seconds,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                process_error = _process_error_text(exc)
            except subprocess.TimeoutExpired as exc:
                process_error = f"render timeout after {exc.timeout} seconds\n{_process_error_text(exc)}".strip()

            log_path = _write_attempt_log(
                logs_dir=logs_dir,
                scene_id=scene_id,
                attempt=attempt,
                command=command,
                completed=completed,
                error=process_error,
                enabled=request.config.keep_render_logs,
            )
            if log_path:
                log_paths.append(str(log_path))

            if _is_valid_rendered_video(output_path):
                warning = ""
                if process_error:
                    warning = f"Remotion reported an error but the output validated: {clean_text(process_error[-500:])}"
                elif attempt > 1:
                    warning = f"Rendered successfully on retry attempt {attempt}."
                return _rendered_scene(
                    scene,
                    spec_path,
                    output_path,
                    spec,
                    warning,
                    attempt_count=attempt,
                    log_paths=log_paths,
                )

            last_error = process_error or "Remotion completed but output video was not created or is invalid."

    return _failed_scene(
        scene,
        spec_path,
        output_path,
        last_error,
        attempt_count=int(request.config.max_render_attempts),
        log_paths=log_paths,
    )


def _build_shared_bundle(
    *,
    engine_dir: Path,
    public_dir: Path,
    bundle_dir: Path,
    logs_dir: Path,
    request: VisualRenderRequest,
) -> tuple[str, Path | None]:
    if not engine_dir.exists():
        return f"Remotion engine dir does not exist: {engine_dir}", None
    command = [
        "npm",
        "run",
        "bundle-engine",
        "--",
        "--public-dir",
        str(public_dir),
        "--out",
        str(bundle_dir),
    ]
    completed: subprocess.CompletedProcess[str] | None = None
    process_error = ""
    try:
        completed = subprocess.run(
            command,
            cwd=engine_dir,
            check=True,
            timeout=request.config.bundle_timeout_seconds,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        process_error = _process_error_text(exc)
    except subprocess.TimeoutExpired as exc:
        process_error = f"bundle timeout after {exc.timeout} seconds\n{_process_error_text(exc)}".strip()

    log_path = _write_attempt_log(
        logs_dir=logs_dir,
        scene_id="remotion_bundle",
        attempt=1,
        command=command,
        completed=completed,
        error=process_error,
        enabled=request.config.keep_render_logs,
    )
    if process_error:
        return f"Remotion shared bundle failed: {clean_text(process_error[-1000:])}", log_path
    if not (bundle_dir / "index.html").exists():
        return "Remotion shared bundle completed without creating index.html", log_path
    return "", log_path


def _prepare_shared_runtime_asset(spec: dict[str, Any], public_dir: Path) -> None:
    scene = spec.get("scene") if isinstance(spec.get("scene"), dict) else {}
    asset = scene.get("resolved_asset") if isinstance(scene.get("resolved_asset"), dict) else {}
    if clean_text(asset.get("asset_type", "")) != "broll_video":
        return
    asset_path = clean_text(asset.get("asset_path", ""))
    source_path = Path(asset_path).resolve() if asset_path else None
    if source_path is None or not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"B-roll asset does not exist: {asset_path}")
    raw_scene_id = clean_text(scene.get("scene_id", "scene")) or "scene"
    scene_id = "".join(character if character.isalnum() or character in "_-" else "_" for character in raw_scene_id)
    filename = f"{scene_id}{source_path.suffix or '.mp4'}"
    shutil.copy2(source_path, public_dir / filename)
    asset["asset_public_path"] = filename


def _write_attempt_log(
    *,
    logs_dir: Path,
    scene_id: str,
    attempt: int,
    command: list[str],
    completed: subprocess.CompletedProcess[str] | None,
    error: str,
    enabled: bool,
) -> Path | None:
    if not enabled:
        return None
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{scene_id}.attempt_{attempt}.log"
    stdout = completed.stdout if completed is not None else ""
    stderr = completed.stderr if completed is not None else ""
    path.write_text(
        "\n".join(
            [
                f"command: {json.dumps(command, ensure_ascii=False)}",
                f"returncode: {completed.returncode if completed is not None else 'exception'}",
                "",
                "stdout:",
                _coerce_process_text(stdout),
                "",
                "stderr:",
                _coerce_process_text(stderr),
                "",
                "error:",
                error,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _process_error_text(exc: Any) -> str:
    parts = [
        _coerce_process_text(getattr(exc, "stdout", "")),
        _coerce_process_text(getattr(exc, "stderr", "")),
    ]
    output = "\n".join(part for part in parts if part.strip()).strip()
    return output or str(exc)


def _coerce_process_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _rendered_scene(
    scene: dict[str, Any],
    spec_path: Path,
    output_path: Path,
    spec: dict[str, Any],
    warning: str = "",
    *,
    attempt_count: int = 1,
    log_paths: list[str] | None = None,
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
        "attempt_count": attempt_count,
        "log_paths": list(log_paths or []),
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
        "render_concurrency": int(request.config.frame_concurrency),
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
        "frame_concurrency": int(request.config.frame_concurrency),
        "max_render_attempts": int(request.config.max_render_attempts),
        "bundle_strategy": "shared_once_per_run",
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


def _failed_scene(
    scene: dict[str, Any],
    spec_path: Path,
    output_path: Path,
    error: str,
    *,
    attempt_count: int = 0,
    log_paths: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "scene_id": clean_text(scene.get("scene_id", "scene_unknown")),
        "scene_order": scene.get("scene_order"),
        "render_kind": scene.get("render_kind"),
        "status": "failed",
        "spec_path": str(spec_path),
        "output_path": str(output_path),
        "duration_seconds": safe_float(scene.get("duration_seconds"), 0.0),
        "error": clean_text(error),
        "warning": "",
        "attempt_count": attempt_count,
        "log_paths": list(log_paths or []),
    }


def _build_package(
    *,
    run_id: str,
    generated_at: str,
    output_dir: Path,
    manifest: dict[str, Any],
    rendered_scenes: list[dict[str, Any]],
    render_settings: dict[str, Any],
    asset_provenance: dict[str, Any],
) -> dict[str, Any]:
    package = {
        "package_type": PACKAGE_TYPE,
        "run_id": run_id,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "render_settings": render_settings,
        "visual_asset_manifest": manifest,
        "rendered_scenes": rendered_scenes,
    }
    parents = {
        "visual_assets": asset_provenance["artifact_fingerprint"],
        "visual_plan": asset_provenance["visual_plan_fingerprint"],
        "script": asset_provenance["script_fingerprint"],
    }
    if asset_provenance.get("voiceover_fingerprint"):
        parents["voiceover"] = asset_provenance["voiceover_fingerprint"]
    package["provenance"] = build_artifact_provenance(
        artifact_type="visual_render",
        run_id=run_id,
        parents=parents,
        script_source=asset_provenance.get("script_source", ""),
        payload=_render_identity_payload(package),
    )
    return package


def _required_asset_provenance(manifest: dict[str, Any], run_id: str) -> dict[str, Any]:
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("visual_asset_manifest.provenance is required")
    validate_artifact_provenance(
        provenance,
        artifact_type="visual_assets",
        run_id=run_id,
        payload=_asset_identity_payload(manifest),
        label="visual_asset_manifest",
    )
    for field in ("artifact_fingerprint", "visual_plan_fingerprint", "script_fingerprint"):
        if not clean_text(provenance.get(field)):
            raise ValueError(f"visual_asset_manifest.provenance.{field} is required")
    return provenance


def _asset_identity_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "resolved_assets": [
            {
                "scene_id": asset.get("scene_id", ""),
                "asset_type": asset.get("asset_type", ""),
                "status": asset.get("status", ""),
                "asset_path": asset.get("asset_path", ""),
            }
            for asset in manifest.get("resolved_assets", [])
            if isinstance(asset, dict)
        ],
        "scene_ids": [
            scene.get("scene_id", "")
            for scene in manifest.get("render_scenes", [])
            if isinstance(scene, dict)
        ],
    }


def _render_identity_payload(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "render_settings": package.get("render_settings", {}),
        "rendered_scenes": [
            {
                "scene_id": scene.get("scene_id", ""),
                "scene_order": scene.get("scene_order"),
                "render_kind": scene.get("render_kind", ""),
                "duration_seconds": scene.get("duration_seconds", 0),
                "status": scene.get("status", ""),
                "output_path": scene.get("output_path", ""),
            }
            for scene in package.get("rendered_scenes", [])
            if isinstance(scene, dict)
        ],
    }


def _build_summary(
    rendered_scenes: list[dict[str, Any]],
    requested_scene_count: int,
    output_dir: str,
    failure_reason: str,
    render_settings: dict[str, Any],
    render_elapsed_seconds: float,
) -> dict[str, Any]:
    failed = [scene for scene in rendered_scenes if scene.get("status") == "failed"]
    return {
        "requested_scene_count": requested_scene_count,
        "rendered_scene_count": len([scene for scene in rendered_scenes if scene.get("status") == "rendered"]),
        "failed_scene_count": len(failed),
        "retried_scene_count": len(
            [scene for scene in rendered_scenes if int(scene.get("attempt_count", 0) or 0) > 1]
        ),
        "warning_count": len([scene for scene in rendered_scenes if clean_text(scene.get("warning", ""))]),
        "render_kind_counts": counter_dict([clean_text(scene.get("render_kind", "")) for scene in rendered_scenes]),
        "status_counts": counter_dict([clean_text(scene.get("status", "")) for scene in rendered_scenes]),
        "render_elapsed_seconds": render_elapsed_seconds,
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
