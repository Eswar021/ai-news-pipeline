from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
import hashlib
import json
import logging
import os
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
from ..payload_validation import validate_scene_payload
from .config import (
    NEXT_MODULE,
    PACKAGE_TYPE,
    QUALITY_PRESETS,
    default_hyperframes_engine_dir,
    default_remotion_engine_dir,
)
from .contract import VisualRenderRequest, VisualRenderResponse


_RETRY_LOCK = Lock()
_LOGGER = logging.getLogger("ai_content_creation.runtime.visual_render")
_HYPERFRAMES_RENDER_KINDS = {
    "source_article_scene",
    "context_image_scene",
    "broll_video_scene",
    "logo_reveal_scene",
    "editorial_text_scene",
    "simple_explainer_scene",
    "story_transition_scene",
}


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
    all_render_scenes = manifest.get("render_scenes", [])
    render_scenes = _selected_render_scenes(all_render_scenes, request)
    if request.config.scene_limit:
        render_scenes = render_scenes[: request.config.scene_limit]
    duration_cap = _max_scene_duration_cap(manifest, request)
    if request.config.backend == "hyperframes":
        engine_dir = Path(
            request.config.hyperframes_engine_dir or default_hyperframes_engine_dir()
        )
    else:
        engine_dir = Path(
            request.config.remotion_engine_dir or default_remotion_engine_dir()
        )
    _LOGGER.info(
        "RENDER start scenes=%d backend=%s mode=%s preset=%s workers=%d cache=%s",
        len(render_scenes),
        request.config.backend,
        request.config.render_mode,
        request.config.quality_preset,
        request.config.worker_count,
        request.config.reuse_cached_scenes,
    )
    render_started = monotonic()
    renderer = (
        _render_scenes_hyperframes
        if request.config.backend == "hyperframes"
        else _render_scenes
    )
    rendered_scenes = renderer(
        render_scenes=render_scenes,
        engine_dir=engine_dir,
        specs_dir=specs_dir,
        scenes_dir=scenes_dir,
        request=request,
        render_settings=render_settings,
        duration_cap=duration_cap,
        visual_style=(manifest.get("visual_scene_plan") or {}).get("episode_style", {}),
    )
    render_elapsed_seconds = round(monotonic() - render_started, 2)
    _LOGGER.info(
        "RENDER complete scenes=%d rendered=%d failed=%d duration=%.2fs",
        len(render_scenes),
        sum(scene.get("status") == "rendered" for scene in rendered_scenes),
        sum(scene.get("status") != "rendered" for scene in rendered_scenes),
        render_elapsed_seconds,
    )

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
        total_scene_count=len(all_render_scenes),
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
            "ready_for_video_assembly": (
                status in {"ok", "partial"}
                and summary["failed_scene_count"] == 0
                and summary["render_scope_complete"]
            ),
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
    visual_style: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not render_scenes:
        return []
    logs_dir = specs_dir.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    rendered_by_index: dict[int, dict[str, Any]] = {}
    cache_dir = Path(request.config.cache_dir).resolve() if request.config.cache_dir else None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    engine_fingerprint = _engine_fingerprint(engine_dir)

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
                scene_for_spec = {**scene, "_visual_style": visual_style or {}}
                spec = _scene_render_spec(scene_for_spec, request, render_settings)
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
            cache_key = _scene_cache_key(spec, engine_fingerprint)
            cache_path = cache_dir / f"{cache_key}.mp4" if cache_dir else None
            if (
                request.config.reuse_cached_scenes
                and cache_path is not None
                and _is_valid_rendered_video(cache_path)
            ):
                _link_or_copy(cache_path, output_path)
                rendered_by_index[index] = _rendered_scene(
                    scene,
                    spec_path,
                    output_path,
                    spec,
                    "Restored unchanged scene from the persistent render cache.",
                    attempt_count=0,
                    cache_status="hit",
                    cache_key=cache_key,
                    render_elapsed_seconds=0.0,
                )
                continue
            jobs.append(
                {
                    "index": index,
                    "scene": scene,
                    "spec": spec,
                    "spec_path": spec_path,
                    "output_path": output_path,
                    "cache_key": cache_key,
                    "cache_path": cache_path,
                }
            )

        cache_hits = sum(
            scene.get("cache_status") == "hit" for scene in rendered_by_index.values()
        )
        preparation_failures = sum(
            scene.get("status") == "failed" for scene in rendered_by_index.values()
        )
        _LOGGER.info(
            "RENDER prepared requested=%d pending=%d cache_hits=%d preparation_failures=%d",
            len(render_scenes),
            len(jobs),
            cache_hits,
            preparation_failures,
        )
        if jobs:
            _LOGGER.info("RENDER bundle start pending_scenes=%d", len(jobs))
            bundle_error, bundle_log_path = _build_shared_bundle(
                engine_dir=engine_dir,
                public_dir=public_dir,
                bundle_dir=bundle_dir,
                logs_dir=logs_dir,
                request=request,
            )
            if bundle_error:
                _LOGGER.error("RENDER bundle failed error=%s", clean_text(bundle_error))
                for job in jobs:
                    rendered_by_index[job["index"]] = _failed_scene(
                        job["scene"],
                        job["spec_path"],
                        job["output_path"],
                        bundle_error,
                        log_paths=[str(bundle_log_path)] if bundle_log_path else [],
                    )
            else:
                _LOGGER.info("RENDER bundle complete pending_scenes=%d", len(jobs))
                new_results = _render_prepared_jobs(
                        jobs=jobs,
                        engine_dir=engine_dir,
                        bundle_dir=bundle_dir,
                        logs_dir=logs_dir,
                        request=request,
                    )
                for job in jobs:
                    result = new_results[job["index"]]
                    cache_path = job.get("cache_path")
                    if result.get("status") == "rendered" and isinstance(cache_path, Path):
                        _link_or_copy(job["output_path"], cache_path)
                        result["cache_status"] = "stored"
                        result["cache_key"] = job["cache_key"]
                    rendered_by_index[job["index"]] = result

    return [rendered_by_index[index] for index in range(len(render_scenes))]


def _render_scenes_hyperframes(
    *,
    render_scenes: list[dict[str, Any]],
    engine_dir: Path,
    specs_dir: Path,
    scenes_dir: Path,
    request: VisualRenderRequest,
    render_settings: dict[str, Any],
    duration_cap: float | None,
    visual_style: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Render isolated scene compositions through the pinned HyperFrames CLI."""

    if not render_scenes:
        return []
    logs_dir = specs_dir.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(request.config.cache_dir).resolve() if request.config.cache_dir else None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    template_path = engine_dir / "index.template.html"
    binary_path = engine_dir / "node_modules" / ".bin" / "hyperframes"
    missing = [
        str(path)
        for path in (template_path, binary_path, engine_dir / "hyperframes.json")
        if not path.exists()
    ]
    engine_error = ""
    if missing:
        engine_error = (
            "HyperFrames engine is not installed or incomplete. Missing: "
            + ", ".join(missing)
            + f". Run `npm install` in {engine_dir}."
        )

    engine_fingerprint = _engine_fingerprint(engine_dir)
    rendered_by_index: dict[int, dict[str, Any]] = {}
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
        render_kind = clean_text(scene.get("render_kind"))
        if render_kind not in _HYPERFRAMES_RENDER_KINDS:
            rendered_by_index[index] = _failed_scene(
                scene,
                spec_path,
                output_path,
                f"HyperFrames backend does not support render_kind {render_kind!r}",
            )
            continue
        if engine_error:
            rendered_by_index[index] = _failed_scene(
                scene,
                spec_path,
                output_path,
                engine_error,
            )
            continue
        try:
            scene_for_spec = {**scene, "_visual_style": visual_style or {}}
            spec = _scene_render_spec(scene_for_spec, request, render_settings)
            spec_path.write_text(
                json.dumps(spec, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            rendered_by_index[index] = _failed_scene(
                scene,
                spec_path,
                output_path,
                f"could not prepare scene render spec: {exc}",
            )
            continue

        cache_key = _scene_cache_key(spec, engine_fingerprint)
        cache_path = cache_dir / f"{cache_key}.mp4" if cache_dir else None
        if (
            request.config.reuse_cached_scenes
            and cache_path is not None
            and _is_valid_rendered_video(cache_path)
        ):
            _link_or_copy(cache_path, output_path)
            rendered_by_index[index] = _rendered_scene(
                scene,
                spec_path,
                output_path,
                spec,
                "Restored unchanged scene from the persistent render cache.",
                attempt_count=0,
                cache_status="hit",
                cache_key=cache_key,
                render_elapsed_seconds=0.0,
            )
            continue
        jobs.append(
            {
                "index": index,
                "scene": scene,
                "spec": spec,
                "spec_path": spec_path,
                "output_path": output_path,
                "cache_key": cache_key,
                "cache_path": cache_path,
            }
        )

    _LOGGER.info(
        "RENDER prepared backend=hyperframes requested=%d pending=%d cache_hits=%d preparation_failures=%d",
        len(render_scenes),
        len(jobs),
        sum(item.get("cache_status") == "hit" for item in rendered_by_index.values()),
        sum(item.get("status") == "failed" for item in rendered_by_index.values()),
    )
    if jobs:
        with TemporaryDirectory(prefix="pipeline-hyperframes-render-") as runtime_value:
            runtime_root = Path(runtime_value)
            worker_count = max(1, min(int(request.config.worker_count), len(jobs)))
            frame_workers = _hyperframes_frame_workers(request)
            _LOGGER.info(
                "RENDER jobs start backend=hyperframes scenes=%d workers=%d frame_workers=%d",
                len(jobs),
                worker_count,
                frame_workers,
            )
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(
                        _render_hyperframes_scene,
                        job=job,
                        engine_dir=engine_dir,
                        runtime_root=runtime_root,
                        logs_dir=logs_dir,
                        request=request,
                    ): job
                    for job in jobs
                }
                completed_count = 0
                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = _failed_scene(
                            job["scene"],
                            job["spec_path"],
                            job["output_path"],
                            f"HyperFrames render worker failed: {type(exc).__name__}: {exc}",
                        )
                    cache_path = job.get("cache_path")
                    if result.get("status") == "rendered" and isinstance(cache_path, Path):
                        _link_or_copy(job["output_path"], cache_path)
                        result["cache_status"] = "stored"
                        result["cache_key"] = job["cache_key"]
                    rendered_by_index[job["index"]] = result
                    completed_count += 1
                    _LOGGER.info(
                        "RENDER progress backend=hyperframes completed=%d/%d scene=%s status=%s",
                        completed_count,
                        len(jobs),
                        clean_text(job["scene"].get("scene_id")),
                        result.get("status", "unknown"),
                    )

    return [rendered_by_index[index] for index in range(len(render_scenes))]


def _render_hyperframes_scene(
    *,
    job: dict[str, Any],
    engine_dir: Path,
    runtime_root: Path,
    logs_dir: Path,
    request: VisualRenderRequest,
) -> dict[str, Any]:
    scene = job["scene"]
    spec = json.loads(json.dumps(job["spec"]))
    scene_id = clean_text(scene.get("scene_id")) or "scene_unknown"
    project_dir = runtime_root / _safe_filename(scene_id)
    _write_hyperframes_project(
        project_dir=project_dir,
        engine_dir=engine_dir,
        spec=spec,
    )
    output_path: Path = job["output_path"]
    log_paths: list[str] = []
    scene_started = monotonic()
    last_error = "HyperFrames did not render the scene."
    binary = engine_dir / "node_modules" / ".bin" / "hyperframes"

    for attempt in range(1, int(request.config.max_render_attempts) + 1):
        retry_context = _RETRY_LOCK if attempt > 1 else nullcontext()
        with retry_context:
            output_path.unlink(missing_ok=True)
            command = [
                str(binary),
                "render",
                str(project_dir),
                "--output",
                str(output_path),
                "--fps",
                str(spec["fps"]),
                "--quality",
                request.config.hyperframes_quality,
                "--workers",
                str(_hyperframes_frame_workers(request)),
                "--no-best-effort",
                "--quiet",
            ]
            if request.config.hyperframes_strict:
                command.append("--strict")
            if spec.get("crf") is not None:
                command.extend(["--crf", str(spec["crf"])])
            elif clean_text(spec.get("video_bitrate")):
                command.extend(["--video-bitrate", clean_text(spec["video_bitrate"])])

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
                process_error = (
                    f"HyperFrames render timeout after {exc.timeout} seconds\n"
                    f"{_process_error_text(exc)}"
                ).strip()
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
                    warning = (
                        "HyperFrames reported an error but the output validated: "
                        + clean_text(process_error[-500:])
                    )
                elif attempt > 1:
                    warning = f"Rendered successfully on retry attempt {attempt}."
                return _rendered_scene(
                    scene,
                    job["spec_path"],
                    output_path,
                    spec,
                    warning,
                    attempt_count=attempt,
                    log_paths=log_paths,
                    cache_status="miss",
                    cache_key=clean_text(job.get("cache_key")),
                    render_elapsed_seconds=round(monotonic() - scene_started, 2),
                )
            last_error = process_error or "HyperFrames completed but output video was not created or is invalid."

    return _failed_scene(
        scene,
        job["spec_path"],
        output_path,
        last_error,
        attempt_count=int(request.config.max_render_attempts),
        log_paths=log_paths,
    )


def _write_hyperframes_project(
    *,
    project_dir: Path,
    engine_dir: Path,
    spec: dict[str, Any],
) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = project_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    node_modules = project_dir / "node_modules"
    if not node_modules.exists():
        node_modules.symlink_to(engine_dir / "node_modules", target_is_directory=True)
    shutil.copy2(engine_dir / "hyperframes.json", project_dir / "hyperframes.json")

    scene = spec.get("scene") if isinstance(spec.get("scene"), dict) else {}
    asset = scene.get("resolved_asset") if isinstance(scene.get("resolved_asset"), dict) else {}
    source_path_text = clean_text(asset.get("asset_path"))
    if source_path_text:
        source_path = Path(source_path_text)
        if source_path.exists() and source_path.is_file():
            filename = f"{_safe_filename(clean_text(scene.get('scene_id')) or 'scene')}{source_path.suffix}"
            shutil.copy2(source_path, assets_dir / filename)
            asset["asset_render_url"] = f"assets/{filename}"

    serialized = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
    serialized = serialized.replace("</script", "<\\/script").replace("<!--", "<\\!--")
    template = (engine_dir / "index.template.html").read_text(encoding="utf-8")
    html = (
        template.replace("__WIDTH__", str(int(spec["width"])))
        .replace("__HEIGHT__", str(int(spec["height"])))
        .replace("__FPS__", str(int(spec["fps"])))
        .replace("__DURATION__", f"{float(spec['duration_seconds']):.2f}")
        .replace("__SCENE_SPEC_JSON__", serialized)
    )
    (project_dir / "index.html").write_text(html, encoding="utf-8")


def _safe_filename(value: str) -> str:
    return "".join(character if character.isalnum() or character in "_-" else "_" for character in value)


def _hyperframes_frame_workers(request: VisualRenderRequest) -> int:
    # Avoid nested process multiplication: scene-level concurrency is already
    # active whenever more than one scene worker is configured.
    if request.config.worker_count > 1:
        return 1
    return max(1, int(request.config.frame_concurrency))


def _render_prepared_jobs(
    *,
    jobs: list[dict[str, Any]],
    engine_dir: Path,
    bundle_dir: Path,
    logs_dir: Path,
    request: VisualRenderRequest,
) -> dict[int, dict[str, Any]]:
    worker_count = max(1, min(int(request.config.worker_count), len(jobs)))
    if request.config.batch_renderer_enabled and len(jobs) > 1:
        _LOGGER.info(
            "RENDER jobs start mode=batch scenes=%d workers=%d",
            len(jobs),
            worker_count,
        )
        return _render_prepared_jobs_in_batches(
            jobs=jobs,
            engine_dir=engine_dir,
            bundle_dir=bundle_dir,
            logs_dir=logs_dir,
            request=request,
            worker_count=worker_count,
        )
    if worker_count == 1:
        _LOGGER.info("RENDER jobs start mode=serial scenes=%d", len(jobs))
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
    _LOGGER.info(
        "RENDER jobs start mode=parallel scenes=%d workers=%d",
        len(jobs),
        worker_count,
    )
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
        completed_count = 0
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
            completed_count += 1
            result = rendered_by_index[job["index"]]
            _LOGGER.info(
                "RENDER progress completed=%d/%d scene=%s status=%s",
                completed_count,
                len(jobs),
                clean_text(job["scene"].get("scene_id")),
                result.get("status", "unknown"),
            )
    return rendered_by_index


def _render_prepared_jobs_in_batches(
    *,
    jobs: list[dict[str, Any]],
    engine_dir: Path,
    bundle_dir: Path,
    logs_dir: Path,
    request: VisualRenderRequest,
    worker_count: int,
) -> dict[int, dict[str, Any]]:
    batches = [jobs[index::worker_count] for index in range(worker_count)]
    batches = [batch for batch in batches if batch]
    rendered: dict[int, dict[str, Any]] = {}
    _LOGGER.info(
        "RENDER batch plan batches=%d scenes=%d",
        len(batches),
        len(jobs),
    )
    with ThreadPoolExecutor(max_workers=len(batches)) as executor:
        future_to_batch = {
            executor.submit(
                _render_batch,
                worker_index=index + 1,
                jobs=batch,
                engine_dir=engine_dir,
                bundle_dir=bundle_dir,
                logs_dir=logs_dir,
                request=request,
            ): batch
            for index, batch in enumerate(batches)
        }
        completed_count = 0
        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                batch_results = future.result()
            except Exception as exc:
                batch_results = {}
                batch_error = f"batch render worker failed: {type(exc).__name__}: {exc}"
                for job in batch:
                    batch_results[job["index"]] = _failed_scene(
                        job["scene"], job["spec_path"], job["output_path"], batch_error
                    )
            rendered.update(batch_results)
            completed_count += len(batch)
            failed_count = sum(
                result.get("status") != "rendered" for result in batch_results.values()
            )
            _LOGGER.info(
                "RENDER progress completed=%d/%d batch_scenes=%d batch_failed=%d",
                completed_count,
                len(jobs),
                len(batch),
                failed_count,
            )

    # A failed scene gets the existing bounded single-scene retry path. This is
    # intentionally serialized on retry to avoid compounding a worker failure.
    for job in jobs:
        result = rendered.get(job["index"])
        if result and result.get("status") == "rendered":
            continue
        _LOGGER.warning(
            "RENDER retry scene=%s reason=%s",
            clean_text(job["scene"].get("scene_id")),
            clean_text((result or {}).get("error")),
        )
        rendered[job["index"]] = _render_prepared_scene(
            job=job,
            engine_dir=engine_dir,
            bundle_dir=bundle_dir,
            logs_dir=logs_dir,
            request=request,
        )
        if rendered[job["index"]].get("status") == "rendered":
            rendered[job["index"]]["warning"] = clean_text(
                "Batch render failed for this scene; bounded single-scene retry succeeded."
            )
    return rendered


def _render_batch(
    *,
    worker_index: int,
    jobs: list[dict[str, Any]],
    engine_dir: Path,
    bundle_dir: Path,
    logs_dir: Path,
    request: VisualRenderRequest,
) -> dict[int, dict[str, Any]]:
    _LOGGER.info(
        "RENDER batch start worker=%d scenes=%d",
        worker_index,
        len(jobs),
    )
    batch_started = monotonic()
    manifest_path = logs_dir / f"batch_worker_{worker_index}.manifest.json"
    results_path = logs_dir / f"batch_worker_{worker_index}.results.json"
    manifest_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"spec": str(job["spec_path"]), "out": str(job["output_path"])}
                    for job in jobs
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    command = [
        "npm",
        "run",
        "render-batch",
        "--",
        "--manifest",
        str(manifest_path),
        "--serve-url",
        str(bundle_dir),
        "--results",
        str(results_path),
    ]
    completed: subprocess.CompletedProcess[str] | None = None
    process_error = ""
    try:
        completed = subprocess.run(
            command,
            cwd=engine_dir,
            check=True,
            timeout=max(
                request.config.render_timeout_seconds,
                request.config.render_timeout_seconds * len(jobs),
            ),
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        process_error = _process_error_text(exc)
    except subprocess.TimeoutExpired as exc:
        process_error = f"batch render timeout after {exc.timeout} seconds\n{_process_error_text(exc)}".strip()
    log_path = _write_attempt_log(
        logs_dir=logs_dir,
        scene_id=f"batch_worker_{worker_index}",
        attempt=1,
        command=command,
        completed=completed,
        error=process_error,
        enabled=request.config.keep_render_logs,
    )
    raw_results: dict[str, dict[str, Any]] = {}
    if not process_error and results_path.exists():
        parsed = json.loads(results_path.read_text(encoding="utf-8"))
        raw_results = {
            str(Path(clean_text(item.get("spec"))).resolve()): item
            for item in parsed.get("results", [])
            if isinstance(item, dict)
        }
    rendered: dict[int, dict[str, Any]] = {}
    for job in jobs:
        raw = raw_results.get(str(job["spec_path"].resolve()), {})
        if clean_text(raw.get("status")) == "rendered" and _is_valid_rendered_video(job["output_path"]):
            rendered[job["index"]] = _rendered_scene(
                job["scene"],
                job["spec_path"],
                job["output_path"],
                job["spec"],
                attempt_count=1,
                log_paths=[str(log_path)] if log_path else [],
                cache_status="miss",
                cache_key=clean_text(job.get("cache_key")),
                render_elapsed_seconds=safe_float(raw.get("elapsed_seconds"), None),
            )
        else:
            rendered[job["index"]] = _failed_scene(
                job["scene"],
                job["spec_path"],
                job["output_path"],
                clean_text(raw.get("error")) or process_error or "batch renderer did not create a valid output",
                attempt_count=1,
                log_paths=[str(log_path)] if log_path else [],
            )
    _LOGGER.info(
        "RENDER batch complete worker=%d scenes=%d failed=%d duration=%.2fs",
        worker_index,
        len(jobs),
        sum(result.get("status") != "rendered" for result in rendered.values()),
        monotonic() - batch_started,
    )
    return rendered


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
    scene_started = monotonic()

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
                    cache_status="miss",
                    cache_key=clean_text(job.get("cache_key")),
                    render_elapsed_seconds=round(monotonic() - scene_started, 2),
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
    cache_status: str = "miss",
    cache_key: str = "",
    render_elapsed_seconds: float | None = None,
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
        "cache_status": clean_text(cache_status),
        "cache_key": clean_text(cache_key),
        "render_elapsed_seconds": render_elapsed_seconds,
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
                "-show_entries",
                "stream=codec_type,duration,width,height",
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
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    if not video_streams or any(stream.get("codec_type") == "audio" for stream in streams):
        return False
    stream = video_streams[0]
    return safe_float(stream.get("duration"), 0.0) > 0 and safe_float(stream.get("width"), 0.0) > 0 and safe_float(stream.get("height"), 0.0) > 0


def _scene_render_spec(scene: dict[str, Any], request: VisualRenderRequest, render_settings: dict[str, Any]) -> dict[str, Any]:
    enriched = json.loads(json.dumps(scene))
    visual_style = enriched.pop("_visual_style", {})
    render_kind = clean_text(enriched.get("render_kind", ""))
    payload = enriched.get("payload") if isinstance(enriched.get("payload"), dict) else {}
    payload_errors = validate_scene_payload(render_kind, payload)
    if payload_errors:
        raise ValueError("; ".join(payload_errors))
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
        "hardware_acceleration": request.config.hardware_acceleration,
        "render_concurrency": int(request.config.frame_concurrency),
        "duration_seconds": round(duration, 2),
        "visual_style": visual_style or {},
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
        "backend": request.config.backend,
        "render_mode": request.config.render_mode,
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
        "batch_renderer_enabled": bool(request.config.batch_renderer_enabled),
        "hyperframes_quality": request.config.hyperframes_quality,
        "hyperframes_strict": bool(request.config.hyperframes_strict),
        "cache_enabled": bool(request.config.reuse_cached_scenes),
    }


def _max_scene_duration_cap(manifest: dict[str, Any], request: VisualRenderRequest) -> float | None:
    if request.config.max_scene_duration_seconds is not None:
        return safe_float(request.config.max_scene_duration_seconds, None)
    plan = manifest.get("visual_scene_plan") if isinstance(manifest.get("visual_scene_plan"), dict) else {}
    policy = plan.get("scene_policy") if isinstance(plan.get("scene_policy"), dict) else {}
    cap = safe_float(
        policy.get("hard_max_scene_seconds", policy.get("max_scene_seconds")),
        0.0,
    )
    if cap <= 0:
        return None
    tolerance = max(
        0.0,
        safe_float(policy.get("hard_cap_tolerance_seconds"), 0.0),
    )
    return cap + tolerance


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
        "cache_status": "miss",
        "cache_key": "",
        "render_elapsed_seconds": None,
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
    *,
    total_scene_count: int,
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
        "render_scope_complete": requested_scene_count == total_scene_count,
        "total_manifest_scene_count": total_scene_count,
        "cached_scene_count": len(
            [scene for scene in rendered_scenes if scene.get("cache_status") == "hit"]
        ),
        "newly_rendered_scene_count": len(
            [scene for scene in rendered_scenes if scene.get("cache_status") == "stored"]
        ),
        "rendered_scenes_per_minute": round(
            60.0 * len([scene for scene in rendered_scenes if scene.get("status") == "rendered"])
            / max(render_elapsed_seconds, 0.01),
            2,
        ),
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


def _selected_render_scenes(
    render_scenes: list[dict[str, Any]],
    request: VisualRenderRequest,
) -> list[dict[str, Any]]:
    scene_ids = set(request.config.selected_scene_ids)
    story_ids = set(request.config.selected_story_ids)
    if not scene_ids and not story_ids:
        return list(render_scenes)
    selected = [
        scene
        for scene in render_scenes
        if clean_text(scene.get("scene_id")) in scene_ids
        or clean_text(scene.get("story_id")) in story_ids
    ]
    if not selected:
        raise ValueError(
            "config.selected_scene_ids/selected_story_ids did not match any manifest scenes"
        )
    return selected


def _engine_fingerprint(engine_dir: Path) -> str:
    if not engine_dir.exists():
        return "missing-engine"
    files = [
        engine_dir / "package.json",
        engine_dir / "package-lock.json",
        engine_dir / "tsconfig.json",
        engine_dir / "hyperframes.json",
        engine_dir / "index.template.html",
    ]
    files.extend(sorted((engine_dir / "src").rglob("*")))
    files.extend(sorted((engine_dir / "scripts").rglob("*")))
    digest = hashlib.sha256()
    for path in files:
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(engine_dir)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _scene_cache_key(spec: dict[str, Any], engine_fingerprint: str) -> str:
    identity = json.loads(json.dumps(spec))
    scene = identity.get("scene") if isinstance(identity.get("scene"), dict) else {}
    asset = scene.get("resolved_asset") if isinstance(scene.get("resolved_asset"), dict) else {}
    asset_path = clean_text(asset.get("asset_path"))
    if asset_path:
        path = Path(asset_path)
        if path.exists() and path.is_file():
            asset["asset_content_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        asset.pop("asset_path", None)
        asset.pop("asset_public_path", None)
    payload = json.dumps(
        {"engine": engine_fingerprint, "spec": identity},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
