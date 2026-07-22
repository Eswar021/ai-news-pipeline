from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from src.pipeline.contracts import (
    artifact_fingerprint,
    build_artifact_provenance,
    visual_assets_artifact_payload,
)

from ..common import iso_now
from ..payload_validation import validate_scene_payload
from ..recipes import ACTIVE_RENDER_KINDS, RECIPE_REGISTRY
from ..render import run as run_visual_render
from .contract import GalleryRequest


def run(input_json: dict) -> dict:
    """Render the source-controlled active visual-family examples."""

    request = GalleryRequest.model_validate(input_json)
    output_dir = Path(request.config.output_dir).resolve()
    if output_dir.exists() and request.config.force:
        shutil.rmtree(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Visual family gallery already exists at {output_dir}. Set config.force=true to replace it."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    assets = _write_sample_assets(output_dir / "sample_assets", request.config)
    palette = _load_palette(request.config.palette)
    scenes, catalog = _build_scenes(request, assets)
    manifest = _build_manifest(request.run.run_id, scenes, palette)
    render_input = {
        "run": request.run.model_dump(mode="json"),
        "config": {
            "output_dir": str(output_dir / "render"),
            "force": True,
            "backend": request.config.backend,
            "render_mode": "preview",
            "quality_preset": "custom",
            "width": request.config.width,
            "height": request.config.height,
            "fps": request.config.fps,
            "crf": 24,
            "x264_preset": "veryfast",
            "pixel_format": "yuv420p",
            "worker_count": request.config.worker_count,
            "frame_concurrency": request.config.frame_concurrency,
            "max_render_attempts": 1,
            "render_timeout_seconds": 240,
            "hyperframes_quality": "draft",
            "hyperframes_strict": True,
            "max_scene_duration_seconds": request.config.scene_duration_seconds + 0.1,
        },
        "input": {
            "visual_asset_resolution": {
                "status": "ok",
                "data": {
                    "run_id": request.run.run_id,
                    "generated_at": request.run.generated_at,
                    "visual_asset_manifest": manifest,
                },
                "summary": {},
                "handoff": {"ready_for_visual_render": True},
            }
        },
    }
    render_result = run_visual_render(render_input)
    contact_sheet = _build_contact_sheet(render_result, output_dir, request.config.width)
    summary = {
        "family_count": len({item["family"] for item in catalog}),
        "scene_type_count": len({item["render_kind"] for item in catalog}),
        "example_count": len(catalog),
        "rendered_count": render_result.get("summary", {}).get("rendered_scene_count", 0),
        "failed_count": render_result.get("summary", {}).get("failed_scene_count", 0),
        "palette": request.config.palette,
        "backend": request.config.backend,
        "contact_sheet_path": str(contact_sheet) if contact_sheet else "",
        "output_dir": str(output_dir),
    }
    result = {
        "status": render_result.get("status", "failed"),
        "data": {
            "run_id": request.run.run_id,
            "generated_at": iso_now(),
            "gallery_catalog": catalog,
            "render_result": render_result,
        },
        "summary": summary,
        "handoff": {"ready_for_visual_review": summary["failed_count"] == 0},
    }
    (output_dir / "gallery_catalog.json").write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "gallery_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def _families_root() -> Path:
    return Path(__file__).resolve().parent


def _load_palette(name: str) -> dict[str, Any]:
    palettes = json.loads((_families_root() / "palettes.json").read_text(encoding="utf-8"))
    if name not in palettes:
        raise ValueError(f"Unknown visual family palette {name!r}; choose one of {sorted(palettes)}")
    return deepcopy(palettes[name])


def _build_scenes(request: GalleryRequest, assets: dict[str, Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_kinds = set(request.config.render_kinds)
    selected_recipes = set(request.config.recipe_ids)
    scenes: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []
    order = 0
    for path in sorted(_families_root().rglob("examples.json")):
        definition = json.loads(path.read_text(encoding="utf-8"))
        render_kind = definition["render_kind"]
        if render_kind not in ACTIVE_RENDER_KINDS:
            raise ValueError(f"Gallery definition {path} uses inactive render kind {render_kind!r}")
        if selected_kinds and render_kind not in selected_kinds:
            continue
        family = path.relative_to(_families_root()).parts[0]
        for example in definition["examples"]:
            payload = deepcopy(example["payload"])
            recipe_id = payload.get("recipe_id", "")
            if selected_recipes and recipe_id not in selected_recipes:
                continue
            if RECIPE_REGISTRY.get(recipe_id, {}).get("render_kind") != render_kind:
                raise ValueError(f"Gallery recipe {recipe_id!r} does not belong to {render_kind!r}")
            payload_errors = validate_scene_payload(render_kind, payload)
            if payload_errors:
                raise ValueError(f"Invalid gallery example {recipe_id}: {'; '.join(payload_errors)}")
            order += 1
            scene_id = f"gallery_{order:03d}_{recipe_id}"
            resolved_asset = _resolved_asset(render_kind, payload, assets)
            scene = {
                "scene_id": scene_id,
                "scene_order": order,
                "story_id": "gallery_story",
                "render_kind": render_kind,
                "start_seconds": round((order - 1) * request.config.scene_duration_seconds, 2),
                "end_seconds": round(order * request.config.scene_duration_seconds, 2),
                "duration_seconds": request.config.scene_duration_seconds,
                "script_excerpt": _sample_excerpt(render_kind),
                "visual_intent": RECIPE_REGISTRY[recipe_id]["description"],
                "payload": payload,
                "resolved_asset": resolved_asset,
            }
            scenes.append(scene)
            catalog.append(
                {
                    "scene_id": scene_id,
                    "family": family,
                    "render_kind": render_kind,
                    "example_name": example["name"],
                    "recipe_id": recipe_id,
                }
            )
    if not scenes:
        raise ValueError("No visual family examples matched the requested selection")
    return scenes, catalog


def _resolved_asset(render_kind: str, payload: dict[str, Any], assets: dict[str, Path]) -> dict[str, Any]:
    base = {
        "status": "resolved",
        "asset_type": "none",
        "asset_path": "",
        "source_label": "Visual family gallery",
    }
    if render_kind in {"source_article_scene", "quote_or_claim_highlight_scene", "browser_walkthrough_scene"}:
        return {**base, "asset_type": "source_screenshot", "asset_path": str(assets["source_page"]), "capture": {"domain": "example.com"}}
    if render_kind == "context_image_scene":
        return {**base, "asset_type": "context_image", "asset_path": str(assets["context_image"]), "media": {"attribution": "Gallery reference image"}}
    if render_kind == "broll_video_scene":
        return {**base, "asset_type": "broll_video", "asset_path": str(assets["video"]), "media": {"attribution": "Gallery reference motion"}}
    if render_kind == "logo_reveal_scene":
        return {**base, "asset_type": "logo_asset", "asset_path": str(assets["logo"])}
    if render_kind == "story_transition_scene" and payload.get("background_media_type"):
        key = "logo" if payload["background_media_type"] == "logo" else "context_image"
        return {**base, "asset_type": f"{payload['background_media_type']}_asset", "asset_path": str(assets[key])}
    if render_kind == "document_stack_scene" and payload.get("recipe_id") == "source_proof_montage":
        nested = []
        for doc in payload.get("documents", []):
            nested.append(
                {
                    "asset_id": doc.get("asset_id"),
                    "asset_type": "source_screenshot",
                    "asset_path": str(assets["source_page"]),
                    "domain": "example.com",
                }
            )
        return {**base, "asset_type": "source_montage", "assets": nested}
    return base


def _build_manifest(run_id: str, scenes: list[dict[str, Any]], palette: dict[str, Any]) -> dict[str, Any]:
    resolved_assets = [
        {
            "scene_id": scene["scene_id"],
            "scene_order": scene["scene_order"],
            **deepcopy(scene["resolved_asset"]),
        }
        for scene in scenes
    ]
    manifest = {
        "package_type": "visual_asset_manifest",
        "run_id": run_id,
        "generated_at": iso_now(),
        "visual_scene_plan": {
            "episode_style": palette,
            "scene_policy": {"max_scene_seconds": 15.0, "hard_max_scene_seconds": 15.0},
        },
        "resolved_assets": resolved_assets,
        "render_scenes": scenes,
    }
    parents = {
        "script": artifact_fingerprint({"fixture": "visual_family_gallery_script"}),
        "visual_plan": artifact_fingerprint({"fixture": "visual_family_gallery_plan"}),
    }
    manifest["provenance"] = build_artifact_provenance(
        artifact_type="visual_assets",
        run_id=run_id,
        parents=parents,
        script_source="visual_family_gallery",
        payload=visual_assets_artifact_payload(manifest),
    )
    return manifest


def _write_sample_assets(output_dir: Path, config) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_page = output_dir / "source_page.svg"
    context_image = output_dir / "context_image.svg"
    logo = output_dir / "logo.svg"
    video = output_dir / "motion_reference.mp4"
    source_page.write_text(_source_page_svg(), encoding="utf-8")
    context_image.write_text(_context_image_svg(), encoding="utf-8")
    logo.write_text(_logo_svg(), encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"testsrc2=size={config.width}x{config.height}:rate={config.fps}",
            "-t", str(config.scene_duration_seconds), "-vf",
            "hue=h=18:s=0.55,drawgrid=width=96:height=96:color=white@0.08",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {"source_page": source_page, "context_image": context_image, "logo": logo, "video": video}


def _build_contact_sheet(render_result: dict[str, Any], output_dir: Path, width: int) -> Path | None:
    package = render_result.get("data", {}).get("visual_render_package", {})
    clips = [
        Path(scene["output_path"])
        for scene in package.get("rendered_scenes", [])
        if scene.get("status") == "rendered" and Path(scene.get("output_path", "")).exists()
    ]
    if not clips:
        return None
    frames_dir = output_dir / "review_frames"
    frames_dir.mkdir(exist_ok=True)
    for index, clip in enumerate(clips, start=1):
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "2", "-i", str(clip), "-frames:v", "1", str(frames_dir / f"frame_{index:03d}.jpg")],
            check=True, capture_output=True, text=True,
        )
    contact_sheet = output_dir / "contact_sheet.jpg"
    tile_width = min(480, width)
    rows = (len(clips) + 2) // 3
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", "1", "-pattern_type", "glob", "-i", str(frames_dir / "frame_*.jpg"),
            "-vf", f"scale={tile_width}:-1,tile=3x{rows}:padding=12:margin=12:color=0xf4efe6", "-frames:v", "1", str(contact_sheet),
        ],
        check=True, capture_output=True, text=True,
    )
    return contact_sheet


def _sample_excerpt(render_kind: str) -> str:
    return {
        "editorial_text_scene": "The helpful answer may be making us less accurate.",
        "story_transition_scene": "First, the strange link between confidence and accuracy.",
        "simple_explainer_scene": "A polished answer reduces checking, and that changes the result.",
        "interface_transform_scene": "The human moves from doing every step to reviewing the agent's work.",
    }.get(render_kind, "The visual now shows the exact evidence or action discussed by the narration.")


def _source_page_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"><rect width="1920" height="1080" fill="#fffdf8"/><rect x="0" y="0" width="1920" height="112" fill="#173246"/><text x="110" y="72" fill="#fff" font-family="Georgia" font-size="46" font-weight="700">THE SIGNAL REVIEW</text><text x="150" y="250" fill="#171611" font-family="Georgia" font-size="78" font-weight="700">A computer designed around uncertainty</text><text x="150" y="330" fill="#6b655d" font-family="Arial" font-size="32">Researchers connect probabilistic bits so noise becomes useful.</text><rect x="150" y="410" width="820" height="420" rx="18" fill="#dfe8e7"/><circle cx="560" cy="620" r="145" fill="#b64b2d" opacity=".82"/><path d="M370 620 C470 470 650 770 760 575" stroke="#173246" stroke-width="28" fill="none"/><text x="1050" y="470" fill="#171611" font-family="Georgia" font-size="44" font-weight="700">The key finding</text><text x="1050" y="535" fill="#4e4a44" font-family="Arial" font-size="30">Each p-bit moves between zero and one.</text><text x="1050" y="590" fill="#4e4a44" font-family="Arial" font-size="30">Linked together, the states settle on</text><text x="1050" y="645" fill="#4e4a44" font-family="Arial" font-size="30">a likely answer instead of one fixed path.</text><rect x="1044" y="690" width="650" height="16" fill="#b64b2d"/></svg>"""


def _context_image_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"><defs><radialGradient id="g" cx="50%" cy="45%" r="70%"><stop offset="0" stop-color="#d7eee8"/><stop offset="1" stop-color="#456a72"/></radialGradient></defs><rect width="1920" height="1080" fill="url(#g)"/><g fill="none" stroke="#fff" stroke-width="12" opacity=".8"><circle cx="960" cy="540" r="290"/><circle cx="960" cy="540" r="180"/><path d="M340 540H1580M960 110V970"/></g><g fill="#f4efe6" stroke="#b64b2d" stroke-width="12"><circle cx="960" cy="540" r="72"/><circle cx="670" cy="540" r="48"/><circle cx="1250" cy="540" r="48"/><circle cx="960" cy="250" r="48"/><circle cx="960" cy="830" r="48"/></g><text x="115" y="970" fill="#fff" font-family="Georgia" font-size="68" font-weight="700">Probabilistic hardware prototype</text></svg>"""


def _logo_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" width="900" height="600" viewBox="0 0 900 600"><path d="M160 350C225 130 390 95 450 300C510 95 675 130 740 350C620 500 280 500 160 350Z" fill="#b64b2d"/><circle cx="450" cy="300" r="96" fill="#f4efe6"/><path d="M410 300l65-65v45h80v40h-80v45z" fill="#171611"/><text x="450" y="555" text-anchor="middle" fill="#171611" font-family="Georgia" font-size="82" font-weight="700">SIGNAL LAB</text></svg>"""
