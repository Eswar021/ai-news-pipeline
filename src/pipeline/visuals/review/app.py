from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape
import json
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any

from PIL import Image, ImageDraw

from src.pipeline.contracts import file_sha256

from ..common import clean_text, format_timestamp, iso_now, safe_float, slugify
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

    story_report = {
        "enabled": False,
        "scene_count": 0,
        "story_count": 0,
        "manifest_path": "",
        "report_path": "",
    }
    planning = request.input.visual_scene_planning
    if request.config.story_report.enabled and planning is not None:
        story_report = _build_story_review_report(
            video_path=video_path,
            duration=duration,
            visual_scene_plan=planning.data.visual_scene_plan,
            output_dir=output_dir,
            ffmpeg_path=request.config.ffmpeg_path,
            worker_count=request.config.story_report.worker_count,
            thumbnail_width=request.config.story_report.thumbnail_width,
            jpeg_quality=request.config.story_report.jpeg_quality,
        )

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
        "story_review_manifest_path": story_report["manifest_path"],
        "story_review_report_path": story_report["report_path"],
        "story_review_scene_count": story_report["scene_count"],
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
        "story_review_scene_count": story_report["scene_count"],
        "story_review_story_count": story_report["story_count"],
        "story_review_manifest_path": story_report["manifest_path"],
        "story_review_report_path": story_report["report_path"],
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
            "story_review_report_path": story_report["report_path"],
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


def _build_story_review_report(
    *,
    video_path: Path,
    duration: float,
    visual_scene_plan: dict[str, Any],
    output_dir: Path,
    ffmpeg_path: str,
    worker_count: int,
    thumbnail_width: int,
    jpeg_quality: int,
) -> dict[str, Any]:
    scenes = [
        scene
        for scene in visual_scene_plan.get("scene_timeline", [])
        if isinstance(scene, dict)
    ]
    if not scenes:
        raise ValueError("visual_scene_plan.scene_timeline must be non-empty for story review")
    assets = {
        clean_text(asset.get("asset_id")): asset
        for asset in (visual_scene_plan.get("asset_catalog") or {}).get("assets", [])
        if isinstance(asset, dict) and clean_text(asset.get("asset_id"))
    }
    story_frames_dir = output_dir / "story_frames"
    story_frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=min(worker_count, len(scenes))) as executor:
        futures = {}
        for index, scene in enumerate(scenes, start=1):
            scene_id = clean_text(scene.get("scene_id")) or f"scene_{index:03d}"
            midpoint = min(
                max(0.0, duration - 0.01),
                max(
                    0.0,
                    (
                        safe_float(scene.get("start_seconds"), 0.0)
                        + safe_float(scene.get("end_seconds"), 0.0)
                    )
                    / 2.0,
                ),
            )
            frame_path = story_frames_dir / f"{index:03d}_{slugify(scene_id)}.jpg"
            futures[
                executor.submit(
                    _extract_scene_review_frame,
                    video_path=video_path,
                    output_path=frame_path,
                    timestamp=midpoint,
                    ffmpeg_path=ffmpeg_path,
                    thumbnail_width=thumbnail_width,
                    jpeg_quality=jpeg_quality,
                )
            ] = (index, frame_path)
        for future in as_completed(futures):
            index, frame_path = futures[future]
            future.result()
            frame_paths[index] = frame_path

    rows: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    group_order: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
        asset_id = clean_text(payload.get("asset_id"))
        asset = assets.get(asset_id, {})
        section_type = clean_text(scene.get("section_type")) or "story"
        story_id = clean_text(scene.get("story_id"))
        group_id = story_id or section_type or "episode"
        story_title = clean_text(scene.get("story_title")) or {
            "intro": "Episode intro",
            "closing": "Episode closing",
        }.get(section_type, "Episode")
        row = {
            "scene_order": index,
            "scene_id": clean_text(scene.get("scene_id")) or f"scene_{index:03d}",
            "section_type": section_type,
            "story_id": story_id,
            "story_title": story_title,
            "start_seconds": round(safe_float(scene.get("start_seconds"), 0.0), 3),
            "end_seconds": round(safe_float(scene.get("end_seconds"), 0.0), 3),
            "duration_seconds": round(safe_float(scene.get("duration_seconds"), 0.0), 3),
            "render_kind": clean_text(scene.get("render_kind")),
            "recipe_id": clean_text(payload.get("recipe_id")),
            "narration_excerpt": clean_text(scene.get("script_excerpt")),
            "visual_intent": clean_text(scene.get("visual_intent")),
            "planner_reason": clean_text(scene.get("reason")),
            "asset_id": asset_id,
            "asset_type": clean_text(asset.get("asset_type")),
            "asset_title": clean_text(asset.get("title")),
            "asset_description": clean_text(
                asset.get("visual_description") or asset.get("description")
            ),
            "asset_source_url": clean_text(asset.get("source_url")),
            "video_moment_id": clean_text(payload.get("video_moment_id")),
            "video_moment_title": _video_moment_title(asset, payload),
            "frame_path": str(frame_paths[index]),
            "frame_relative_path": str(frame_paths[index].relative_to(output_dir)),
        }
        rows.append(row)
        if group_id not in groups:
            groups[group_id] = {
                "group_id": group_id,
                "section_type": section_type,
                "story_id": story_id,
                "story_title": story_title,
                "scenes": [],
            }
            group_order.append(group_id)
        groups[group_id]["scenes"].append(row)

    manifest = {
        "package_type": "story_visual_review_manifest",
        "scene_count": len(rows),
        "story_count": len([group for group in groups.values() if group["story_id"]]),
        "groups": [groups[group_id] for group_id in group_order],
    }
    manifest_path = output_dir / "story_review_manifest.json"
    report_path = output_dir / "story_review_report.html"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report_path.write_text(_story_review_html(manifest), encoding="utf-8")
    return {
        "enabled": True,
        "scene_count": manifest["scene_count"],
        "story_count": manifest["story_count"],
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
    }


def _extract_scene_review_frame(
    *,
    video_path: Path,
    output_path: Path,
    timestamp: float,
    ffmpeg_path: str,
    thumbnail_width: int,
    jpeg_quality: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    quality_scale = max(2, min(31, round((100 - jpeg_quality) / 4) + 2))
    completed = subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={thumbnail_width}:-2",
            "-q:v",
            str(quality_scale),
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not extract story review frame at {timestamp:.3f}s: "
            f"{clean_text(completed.stderr)[-600:]}"
        )


def _video_moment_title(asset: dict[str, Any], payload: dict[str, Any]) -> str:
    moment_id = clean_text(payload.get("video_moment_id"))
    if not moment_id:
        return ""
    for moment in asset.get("video_moments", []):
        if isinstance(moment, dict) and clean_text(moment.get("video_moment_id")) == moment_id:
            return clean_text(moment.get("title"))
    return ""


def _story_review_html(manifest: dict[str, Any]) -> str:
    sections = []
    for group in manifest.get("groups", []):
        scene_cards = []
        for row in group.get("scenes", []):
            source_url = clean_text(row.get("asset_source_url"))
            source_markup = (
                f'<a href="{escape(source_url, quote=True)}">source</a>' if source_url else ""
            )
            asset_line = " · ".join(
                item
                for item in (
                    clean_text(row.get("asset_type")),
                    clean_text(row.get("asset_title")),
                    clean_text(row.get("video_moment_title")),
                )
                if item
            )
            scene_cards.append(
                """
                <article class="scene">
                  <img src="{frame}" alt="Rendered frame for {scene_id}">
                  <div class="details">
                    <div class="meta">{order:02d} · {start}–{end} · {kind} · {recipe}</div>
                    <h3>{scene_id}</h3>
                    <p class="narration">{narration}</p>
                    <p><strong>Visual intent:</strong> {intent}</p>
                    <p><strong>Planner reason:</strong> {reason}</p>
                    <p><strong>Asset:</strong> {asset} {source}</p>
                  </div>
                </article>
                """.format(
                    frame=escape(clean_text(row.get("frame_relative_path")), quote=True),
                    scene_id=escape(clean_text(row.get("scene_id"))),
                    order=int(row.get("scene_order", 0)),
                    start=escape(format_timestamp(safe_float(row.get("start_seconds"), 0.0))),
                    end=escape(format_timestamp(safe_float(row.get("end_seconds"), 0.0))),
                    kind=escape(clean_text(row.get("render_kind"))),
                    recipe=escape(clean_text(row.get("recipe_id")) or "no recipe"),
                    narration=escape(clean_text(row.get("narration_excerpt"))),
                    intent=escape(clean_text(row.get("visual_intent")) or "—"),
                    reason=escape(clean_text(row.get("planner_reason")) or "—"),
                    asset=escape(asset_line or "none"),
                    source=source_markup,
                )
            )
        sections.append(
            f'<section><p class="eyebrow">{escape(clean_text(group.get("section_type"))).upper()}</p>'
            f'<h2>{escape(clean_text(group.get("story_title")))}</h2>{"".join(scene_cards)}</section>'
        )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Story visual review</title><style>
:root { color-scheme: light; --paper:#f3efe5; --ink:#191815; --muted:#6b675e; --accent:#e65b2f; }
* { box-sizing:border-box; } body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.5 Georgia,serif; }
main { width:min(1380px,94vw); margin:48px auto 100px; } h1,h2,h3 { margin:0; line-height:1.05; }
h1 { font-size:clamp(42px,6vw,86px); max-width:900px; } h2 { font-size:clamp(30px,4vw,54px); margin-bottom:24px; }
section { padding:54px 0; border-top:1px solid #bbb4a7; } .eyebrow,.meta { font:700 12px/1.2 ui-monospace,monospace; letter-spacing:.12em; text-transform:uppercase; color:var(--accent); }
.scene { display:grid; grid-template-columns:minmax(360px,1.1fr) minmax(320px,.9fr); gap:28px; align-items:start; margin:0 0 34px; }
.scene img { width:100%; display:block; border:1px solid #bbb4a7; box-shadow:0 16px 38px rgba(31,25,17,.12); }
.details { padding-top:6px; } .details h3 { font:700 24px/1.15 ui-sans-serif,sans-serif; margin:10px 0 16px; }
.details p { margin:9px 0; } .narration { font-size:21px; line-height:1.42; } a { color:var(--accent); }
@media (max-width:800px) { .scene { grid-template-columns:1fr; } main { margin-top:28px; } }
</style></head><body><main><p class="eyebrow">Scene-by-scene QA</p><h1>Does every visual support what the viewer hears?</h1>
""" + "".join(sections) + "</main></body></html>"


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
