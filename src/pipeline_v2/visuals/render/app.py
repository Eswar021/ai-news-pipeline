from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ..common import clean_text, counter_dict, iso_now, safe_float
from .config import NEXT_MODULE, PACKAGE_TYPE, default_remotion_engine_dir
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
    render_scenes = manifest.get("render_scenes", [])
    if request.config.scene_limit:
        render_scenes = render_scenes[: request.config.scene_limit]
    duration_cap = _max_scene_duration_cap(manifest, request)
    engine_dir = Path(request.config.remotion_engine_dir or default_remotion_engine_dir())
    rendered_scenes: list[dict[str, Any]] = []
    for scene in render_scenes:
        rendered_scenes.append(
            _render_one_scene(
                scene=scene,
                engine_dir=engine_dir,
                specs_dir=specs_dir,
                scenes_dir=scenes_dir,
                request=request,
                duration_cap=duration_cap,
            )
        )

    failure_reason = _failure_reason(rendered_scenes)
    package = _build_package(
        run_id=request.run.run_id,
        generated_at=generated_at,
        output_dir=output_dir,
        manifest=manifest,
        rendered_scenes=rendered_scenes,
    )
    summary = _build_summary(rendered_scenes, len(render_scenes), str(output_dir), failure_reason)
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


def _render_one_scene(
    *,
    scene: dict[str, Any],
    engine_dir: Path,
    specs_dir: Path,
    scenes_dir: Path,
    request: VisualRenderRequest,
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
    spec = _scene_render_spec(scene, request)
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
        return _failed_scene(scene, spec_path, output_path, (exc.stderr or exc.stdout or str(exc))[-2000:])
    except subprocess.TimeoutExpired as exc:
        return _failed_scene(scene, spec_path, output_path, f"render timeout after {exc.timeout} seconds")
    return {
        "scene_id": scene_id,
        "scene_order": scene.get("scene_order"),
        "render_kind": scene.get("render_kind"),
        "status": "rendered" if output_path.exists() else "failed",
        "spec_path": str(spec_path),
        "output_path": str(output_path),
        "duration_seconds": spec["duration_seconds"],
        "error": "" if output_path.exists() else "Remotion completed but output file was not created.",
    }


def _scene_render_spec(scene: dict[str, Any], request: VisualRenderRequest) -> dict[str, Any]:
    enriched = json.loads(json.dumps(scene))
    asset = enriched.get("resolved_asset") if isinstance(enriched.get("resolved_asset"), dict) else {}
    asset_path = clean_text(asset.get("asset_path", ""))
    if asset_path:
        asset["asset_data_uri"] = _data_uri_for_path(Path(asset_path))
    duration = max(1.0, safe_float(enriched.get("duration_seconds"), 6.0))
    return {
        "width": request.config.width,
        "height": request.config.height,
        "fps": request.config.fps,
        "codec": request.config.codec,
        "duration_seconds": round(duration, 2),
        "scene": enriched,
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
) -> dict[str, Any]:
    return {
        "package_type": PACKAGE_TYPE,
        "run_id": run_id,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "visual_asset_manifest": manifest,
        "rendered_scenes": rendered_scenes,
    }


def _build_summary(
    rendered_scenes: list[dict[str, Any]],
    requested_scene_count: int,
    output_dir: str,
    failure_reason: str,
) -> dict[str, Any]:
    failed = [scene for scene in rendered_scenes if scene.get("status") == "failed"]
    return {
        "requested_scene_count": requested_scene_count,
        "rendered_scene_count": len([scene for scene in rendered_scenes if scene.get("status") == "rendered"]),
        "failed_scene_count": len(failed),
        "render_kind_counts": counter_dict([clean_text(scene.get("render_kind", "")) for scene in rendered_scenes]),
        "status_counts": counter_dict([clean_text(scene.get("status", "")) for scene in rendered_scenes]),
        "output_dir": output_dir,
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
