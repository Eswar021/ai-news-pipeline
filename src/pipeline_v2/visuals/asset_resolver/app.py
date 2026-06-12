from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from ..common import clean_text, counter_dict, iso_now
from ..generators.logo_reveal import resolve_logo_asset
from ..generators.source_screenshot import capture_source_viewport
from .config import NEXT_MODULE, PACKAGE_TYPE
from .contract import AssetResolverRequest, AssetResolverResponse


def run(input_json: dict) -> dict:
    request = AssetResolverRequest.model_validate(input_json)
    generated_at = iso_now()
    output_dir = Path(request.config.output_dir).resolve()
    result_path = output_dir / "visual_asset_resolution_result.json"
    manifest_path = output_dir / "visual_asset_manifest.json"
    summary_path = output_dir / "summary.json"

    if manifest_path.exists() and not request.config.force:
        raise FileExistsError(f"Visual assets already exist at {manifest_path}. Set config.force=true to replace them.")
    if request.config.force and output_dir.exists():
        shutil.rmtree(output_dir)

    assets_dir = output_dir / "assets"
    screenshots_dir = assets_dir / "source_screenshots"
    logos_dir = assets_dir / "logos"
    raw_capture_dir = output_dir / "debug_raw_screenshots"
    full_page_dir = output_dir / "debug_full_pages"
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    logos_dir.mkdir(parents=True, exist_ok=True)

    visual_scene_plan = request.input.visual_scene_planning.data.visual_scene_plan
    scenes = visual_scene_plan.get("scene_timeline", [])
    resolved_assets: list[dict[str, Any]] = []

    source_scenes = [scene for scene in scenes if scene.get("render_kind") == "source_article_scene"]
    other_scenes = [scene for scene in scenes if scene.get("render_kind") != "source_article_scene"]

    if source_scenes and request.config.source_screenshots.enabled:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=request.config.browser.headless)
            context = browser.new_context(
                viewport={"width": request.config.target_width, "height": request.config.target_height},
                device_scale_factor=request.config.browser.device_scale_factor,
                user_agent=request.config.browser.user_agent,
                service_workers="block",
            )
            try:
                for scene in source_scenes:
                    resolved_assets.append(
                        _resolve_source_screenshot(
                            context=context,
                            scene=scene,
                            request=request,
                            screenshots_dir=screenshots_dir,
                            raw_capture_dir=raw_capture_dir,
                            full_page_dir=full_page_dir,
                        )
                    )
            finally:
                context.close()
                browser.close()
    else:
        for scene in source_scenes:
            resolved_assets.append(_disabled_source_screenshot(scene))

    for scene in other_scenes:
        if scene.get("render_kind") == "logo_reveal_scene":
            resolved_assets.append(_resolve_logo(scene, request, logos_dir))
        elif scene.get("render_kind") == "kinetic_type_scene":
            resolved_assets.append(_resolve_no_asset(scene))
        else:
            resolved_assets.append(_unsupported_scene(scene))

    resolved_assets = sorted(resolved_assets, key=lambda item: item.get("scene_order", 999999))
    failure_reason = _failure_reason(resolved_assets)
    manifest = _build_manifest(
        run_id=request.run.run_id,
        generated_at=generated_at,
        output_dir=output_dir,
        visual_scene_plan=visual_scene_plan,
        resolved_assets=resolved_assets,
    )
    summary = _build_summary(
        resolved_assets=resolved_assets,
        requested_scene_count=len(scenes),
        output_dir=str(output_dir),
        failure_reason=failure_reason,
    )
    status = _status_from_summary(summary)
    response = AssetResolverResponse(
        status=status,
        data={
            "run_id": request.run.run_id,
            "generated_at": generated_at,
            "visual_asset_manifest": manifest,
        },
        summary=summary,
        handoff={
            "ready_for_visual_render": status in {"ok", "partial"} and summary["failed_asset_count"] == 0,
            "next_module": NEXT_MODULE,
        },
    )
    result = response.model_dump(mode="json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _resolve_source_screenshot(
    *,
    context,
    scene: dict[str, Any],
    request: AssetResolverRequest,
    screenshots_dir: Path,
    raw_capture_dir: Path,
    full_page_dir: Path,
) -> dict[str, Any]:
    scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
    output_path = screenshots_dir / f"{scene_id}.png"
    capture = capture_source_viewport(
        context=context,
        scene=scene,
        timeout_ms=request.config.browser.timeout_ms,
        post_load_wait_ms=request.config.browser.post_load_wait_ms,
        capture_mode=request.config.source_screenshots.capture_mode,
        raw_capture_path=(
            raw_capture_dir / f"{scene_id}_raw.png"
            if request.config.source_screenshots.save_raw_capture_debug
            else None
        ),
        full_page_debug_path=(
            full_page_dir / f"{scene_id}_full.png"
            if request.config.source_screenshots.save_full_page_debug
            else None
        ),
    )
    if capture.get("ok"):
        output_path.write_bytes(capture["screenshot_bytes"])
        return _base_asset(scene) | {
            "asset_type": "source_screenshot",
            "status": "resolved",
            "asset_path": str(output_path),
            "capture": {key: value for key, value in capture.items() if key != "screenshot_bytes"},
            "error": "",
        }
    return _base_asset(scene) | {
        "asset_type": "source_screenshot",
        "status": "failed",
        "asset_path": "",
        "capture": capture,
        "error": clean_text(capture.get("error", "source screenshot capture failed")),
    }


def _resolve_logo(scene: dict[str, Any], request: AssetResolverRequest, logos_dir: Path) -> dict[str, Any]:
    local_dir = Path(request.config.logos.local_logo_dir) if request.config.logos.local_logo_dir else None
    resolution = resolve_logo_asset(scene=scene, output_dir=logos_dir, local_logo_dir=local_dir)
    return _base_asset(scene) | {
        "asset_type": "logo_asset",
        "status": resolution["status"],
        "asset_path": resolution.get("logo_path") or resolution.get("fallback_svg_path", ""),
        "logo": resolution,
        "error": "",
    }


def _resolve_no_asset(scene: dict[str, Any]) -> dict[str, Any]:
    return _base_asset(scene) | {
        "asset_type": "none",
        "status": "ready",
        "asset_path": "",
        "error": "",
    }


def _disabled_source_screenshot(scene: dict[str, Any]) -> dict[str, Any]:
    return _base_asset(scene) | {
        "asset_type": "source_screenshot",
        "status": "failed",
        "asset_path": "",
        "error": "source screenshot capture is disabled",
    }


def _unsupported_scene(scene: dict[str, Any]) -> dict[str, Any]:
    return _base_asset(scene) | {
        "asset_type": "unsupported",
        "status": "failed",
        "asset_path": "",
        "error": f"Unsupported render_kind: {scene.get('render_kind')}",
    }


def _base_asset(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_id": clean_text(scene.get("scene_id", "")),
        "scene_order": scene.get("scene_order"),
        "story_id": clean_text(scene.get("story_id", "")),
        "render_kind": clean_text(scene.get("render_kind", "")),
        "source_record_keys": scene.get("source_record_keys", []),
        "source_urls": scene.get("source_urls", []),
    }


def _build_manifest(
    *,
    run_id: str,
    generated_at: str,
    output_dir: Path,
    visual_scene_plan: dict[str, Any],
    resolved_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    by_scene_id = {asset["scene_id"]: asset for asset in resolved_assets}
    render_scenes: list[dict[str, Any]] = []
    for scene in visual_scene_plan.get("scene_timeline", []):
        asset = by_scene_id.get(clean_text(scene.get("scene_id", "")), {})
        render_scenes.append(
            {
                **scene,
                "resolved_asset": asset,
            }
        )
    return {
        "package_type": PACKAGE_TYPE,
        "run_id": run_id,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "visual_scene_plan": visual_scene_plan,
        "resolved_assets": resolved_assets,
        "render_scenes": render_scenes,
    }


def _build_summary(
    *,
    resolved_assets: list[dict[str, Any]],
    requested_scene_count: int,
    output_dir: str,
    failure_reason: str,
) -> dict[str, Any]:
    failed = [asset for asset in resolved_assets if asset.get("status") == "failed"]
    return {
        "requested_scene_count": requested_scene_count,
        "resolved_asset_count": len([asset for asset in resolved_assets if asset.get("status") in {"resolved", "ready"}]),
        "source_screenshot_count": len([asset for asset in resolved_assets if asset.get("asset_type") == "source_screenshot" and asset.get("status") == "resolved"]),
        "logo_asset_count": len([asset for asset in resolved_assets if asset.get("asset_type") == "logo_asset" and asset.get("status") == "resolved"]),
        "failed_asset_count": len(failed),
        "asset_type_counts": counter_dict([asset.get("asset_type", "") for asset in resolved_assets]),
        "status_counts": counter_dict([asset.get("status", "") for asset in resolved_assets]),
        "output_dir": output_dir,
        "failure_reason": failure_reason,
    }


def _failure_reason(resolved_assets: list[dict[str, Any]]) -> str:
    failures = [asset for asset in resolved_assets if asset.get("status") == "failed"]
    if not failures:
        return ""
    return "; ".join(f"{asset.get('scene_id')}: {asset.get('error')}" for asset in failures[:5])


def _status_from_summary(summary: dict[str, Any]) -> str:
    requested = summary["requested_scene_count"]
    failed = summary["failed_asset_count"]
    if requested == 0 or failed == requested:
        return "failed"
    if failed:
        return "partial"
    return "ok"
