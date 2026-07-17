from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from src.pipeline.contracts import (
    build_artifact_provenance,
    require_matching_run_id,
    require_parent_fingerprint,
    validate_artifact_provenance,
    visual_plan_artifact_payload,
)

from ..common import clean_text, counter_dict, iso_now
from ..generators.logo_reveal import resolve_logo_asset
from ..generators.source_screenshot import capture_source_viewport
from .config import NEXT_MODULE, PACKAGE_TYPE
from .contract import AssetResolverRequest, AssetResolverResponse

SOURCE_SCREENSHOT_RENDER_KINDS = {"source_article_scene", "quote_or_claim_highlight_scene"}
DISCOVERED_MEDIA_RENDER_KINDS = {"context_image_scene", "broll_video_scene"}
NO_ASSET_RENDER_KINDS = {
    "editorial_text_scene",
    "simple_explainer_scene",
    "story_transition_scene",
    "kinetic_type_scene",
    "bullet_build_scene",
    "entity_compare_scene",
    "recap_sequence_scene",
    "data_counter_scene",
    "trend_line_scene",
    "bar_chart_scene",
    "bar_race_scene",
    "ranked_list_scene",
    "benchmark_delta_scene",
    "ecosystem_map_scene",
    "architecture_flow_scene",
    "process_zoom_scene",
    "browser_walkthrough_scene",
    "decision_tree_scene",
    "capability_matrix_scene",
    "timeline_zoom_scene",
    "document_stack_scene",
    "signal_radar_scene",
    "interface_transform_scene",
    "transition_stinger_scene",
}


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

    visual_media_package = _visual_media_package(request)
    canonical_visual_scene_plan = request.input.visual_scene_planning.data.visual_scene_plan
    visual_scene_plan = (
        visual_media_package.get("visual_scene_plan", {})
        if visual_media_package
        else canonical_visual_scene_plan
    )
    scenes = visual_scene_plan.get("scene_timeline", [])
    require_matching_run_id(
        request.run.run_id,
        request.input.visual_scene_planning.data.run_id,
        "visual_scene_planning",
    )
    plan_provenance = _required_plan_provenance(canonical_visual_scene_plan, request.run.run_id)
    if visual_media_package:
        require_matching_run_id(request.run.run_id, visual_media_package.get("run_id"), "visual_media")
        validate_artifact_provenance(
            visual_media_package.get("provenance"),
            artifact_type="visual_media",
            run_id=request.run.run_id,
            payload=_media_identity_payload(visual_media_package),
            label="visual_media",
        )
        require_parent_fingerprint(
            visual_media_package.get("provenance"),
            parent_name="visual_plan",
            expected=plan_provenance["visual_plan_fingerprint"],
            label="visual_media",
        )
    resolved_assets: list[dict[str, Any]] = []
    media_selections = {
        clean_text(selection.get("scene_id", "")): selection
        for selection in visual_media_package.get("selections", [])
        if isinstance(selection, dict) and clean_text(selection.get("scene_id", ""))
    }

    source_scenes = [scene for scene in scenes if scene.get("render_kind") in SOURCE_SCREENSHOT_RENDER_KINDS]
    other_scenes = [scene for scene in scenes if scene.get("render_kind") not in SOURCE_SCREENSHOT_RENDER_KINDS]

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
        elif scene.get("render_kind") == "story_transition_scene":
            background_type = clean_text((scene.get("payload") or {}).get("background_media_type"))
            if background_type in {"image", "video"}:
                resolved_assets.append(_resolve_discovered_media(scene, media_selections))
            elif background_type == "logo":
                resolved_assets.append(_resolve_logo(scene, request, logos_dir))
            else:
                resolved_assets.append(_resolve_no_asset(scene))
        elif scene.get("render_kind") in DISCOVERED_MEDIA_RENDER_KINDS:
            resolved_assets.append(_resolve_discovered_media(scene, media_selections))
        elif scene.get("render_kind") in NO_ASSET_RENDER_KINDS:
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
        visual_media_package=visual_media_package,
        resolved_assets=resolved_assets,
        plan_provenance=plan_provenance,
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
    capture_scene = _scene_with_capture_target(scene)
    capture = capture_source_viewport(
        context=context,
        scene=capture_scene,
        timeout_ms=request.config.browser.timeout_ms,
        post_load_wait_ms=request.config.browser.post_load_wait_ms,
        capture_mode=request.config.source_screenshots.capture_mode,
        focus_zoom=request.config.source_screenshots.focus_zoom,
        highlight_target=request.config.source_screenshots.highlight_target,
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
        target_text = clean_text((capture_scene.get("payload") or {}).get("target_text", ""))
        target_missed = bool(target_text) and not bool(capture.get("target_found"))
        status = "resolved"
        error = ""
        if target_missed and request.config.source_screenshots.target_miss_policy != "allow":
            status = request.config.source_screenshots.target_miss_policy
            error = "Screenshot was captured, but the requested target text was not located on the page."
        return _base_asset(scene) | {
            "asset_type": "source_screenshot",
            "status": status,
            "asset_path": str(output_path),
            "capture": {key: value for key, value in capture.items() if key != "screenshot_bytes"},
            "error": error,
        }
    return _base_asset(scene) | {
        "asset_type": "source_screenshot",
        "status": "failed",
        "asset_path": "",
        "capture": capture,
        "error": clean_text(capture.get("error", "source screenshot capture failed")),
    }


def _scene_with_capture_target(scene: dict[str, Any]) -> dict[str, Any]:
    payload = dict(scene.get("payload") or {})
    payload["target_text"] = clean_text(
        payload.get("target_text")
        or payload.get("supporting_text")
        or payload.get("claim_text")
    )
    return {**scene, "payload": payload}


def _resolve_logo(scene: dict[str, Any], request: AssetResolverRequest, logos_dir: Path) -> dict[str, Any]:
    local_dir = Path(request.config.logos.local_logo_dir) if request.config.logos.local_logo_dir else None
    resolution = resolve_logo_asset(
        scene=scene,
        output_dir=logos_dir,
        local_logo_dir=local_dir,
        simple_icons_enabled=request.config.logos.simple_icons_enabled,
        favicon_fallback_enabled=request.config.logos.favicon_fallback_enabled,
        text_fallback_enabled=request.config.logos.text_fallback_enabled,
        favicon_timeout_seconds=request.config.logos.favicon_timeout_seconds,
    )
    return _base_asset(scene) | {
        "asset_type": "logo_asset",
        "status": resolution["status"],
        "asset_path": resolution.get("logo_path") or resolution.get("fallback_svg_path", ""),
        "logo": resolution,
        "error": clean_text(resolution.get("error", "")),
    }


def _resolve_no_asset(scene: dict[str, Any]) -> dict[str, Any]:
    return _base_asset(scene) | {
        "asset_type": "none",
        "status": "ready",
        "asset_path": "",
        "error": "",
    }


def _resolve_discovered_media(
    scene: dict[str, Any],
    media_selections: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    scene_id = clean_text(scene.get("scene_id", ""))
    render_kind = clean_text(scene.get("render_kind", ""))
    expected_type = (
        clean_text((scene.get("payload") or {}).get("background_media_type"))
        if render_kind == "story_transition_scene"
        else ("video" if render_kind == "broll_video_scene" else "image")
    )
    asset_type = "broll_video" if expected_type == "video" else "context_image"
    selection = media_selections.get(scene_id)
    if not selection:
        return _base_asset(scene) | {
            "asset_type": asset_type,
            "status": "failed",
            "asset_path": "",
            "media": {},
            "error": "media discovery did not provide a selection for this scene",
        }
    asset_path = Path(clean_text(selection.get("asset_path", "")))
    if selection.get("media_type") != expected_type:
        return _base_asset(scene) | {
            "asset_type": asset_type,
            "status": "failed",
            "asset_path": "",
            "media": selection,
            "error": f"media selection type {selection.get('media_type')!r} does not match expected {expected_type!r}",
        }
    if not asset_path.exists() or not asset_path.is_file() or asset_path.stat().st_size <= 0:
        return _base_asset(scene) | {
            "asset_type": asset_type,
            "status": "failed",
            "asset_path": str(asset_path),
            "media": selection,
            "error": "selected media file is missing or empty",
        }
    return _base_asset(scene) | {
        "asset_type": asset_type,
        "status": "resolved",
        "asset_path": str(asset_path.resolve()),
        "media": selection,
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
    visual_media_package: dict[str, Any],
    resolved_assets: list[dict[str, Any]],
    plan_provenance: dict[str, Any],
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
    manifest = {
        "package_type": PACKAGE_TYPE,
        "run_id": run_id,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "visual_scene_plan": visual_scene_plan,
        "visual_media_package": visual_media_package,
        "resolved_assets": resolved_assets,
        "render_scenes": render_scenes,
    }
    parents = {
        "visual_plan": plan_provenance["visual_plan_fingerprint"],
        "script": plan_provenance["script_fingerprint"],
    }
    if plan_provenance.get("voiceover_fingerprint"):
        parents["voiceover"] = plan_provenance["voiceover_fingerprint"]
    if visual_media_package:
        parents["visual_media"] = visual_media_package["provenance"]["artifact_fingerprint"]
    manifest["provenance"] = build_artifact_provenance(
        artifact_type="visual_assets",
        run_id=run_id,
        parents=parents,
        script_source=plan_provenance.get("script_source", ""),
        payload=_asset_identity_payload(manifest),
    )
    return manifest


def _build_summary(
    *,
    resolved_assets: list[dict[str, Any]],
    requested_scene_count: int,
    output_dir: str,
    failure_reason: str,
) -> dict[str, Any]:
    failed = [asset for asset in resolved_assets if asset.get("status") == "failed"]
    degraded = [asset for asset in resolved_assets if asset.get("status") in {"partial", "fallback"}]
    return {
        "requested_scene_count": requested_scene_count,
        "resolved_asset_count": len([asset for asset in resolved_assets if asset.get("status") in {"resolved", "ready", "partial", "fallback"}]),
        "source_screenshot_count": len([asset for asset in resolved_assets if asset.get("asset_type") == "source_screenshot" and asset.get("status") in {"resolved", "partial"}]),
        "logo_asset_count": len([asset for asset in resolved_assets if asset.get("asset_type") == "logo_asset" and asset.get("status") in {"resolved", "fallback"}]),
        "context_image_count": len([asset for asset in resolved_assets if asset.get("asset_type") == "context_image" and asset.get("status") == "resolved"]),
        "broll_video_count": len([asset for asset in resolved_assets if asset.get("asset_type") == "broll_video" and asset.get("status") == "resolved"]),
        "failed_asset_count": len(failed),
        "degraded_asset_count": len(degraded),
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
    if summary.get("degraded_asset_count"):
        return "partial"
    return "ok"


def _visual_media_package(request: AssetResolverRequest) -> dict[str, Any]:
    envelope = request.input.visual_media_discovery
    if envelope is None:
        return {}
    return envelope.data.visual_media_package


def _required_plan_provenance(plan: dict[str, Any], run_id: str) -> dict[str, Any]:
    provenance = plan.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("visual_scene_plan.provenance is required")
    require_matching_run_id(run_id, provenance.get("run_id"), "visual_scene_plan.provenance")
    validate_artifact_provenance(
        provenance,
        artifact_type="visual_plan",
        run_id=run_id,
        payload=visual_plan_artifact_payload(plan),
        label="visual_scene_plan",
    )
    for field in ("visual_plan_fingerprint", "script_fingerprint"):
        if not clean_text(provenance.get(field)):
            raise ValueError(f"visual_scene_plan.provenance.{field} is required")
    return provenance


def _media_identity_payload(package: dict[str, Any]) -> dict[str, Any]:
    plan = package.get("visual_scene_plan") or {}
    return {
        "selections": package.get("selections", []),
        "fallbacks": package.get("fallbacks", []),
        "unresolved": package.get("unresolved", []),
        "scene_timeline": plan.get("scene_timeline", []),
    }


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
