"""
Build a human-readable publishing handoff from an approved L8 package.

This is not a pipeline layer. It exports the approved script, metadata, chapters,
and sources into one Markdown file for manual publishing work.

Usage:
    python3 -m src.publish_handoff --run-id current
    python3 -m src.publish_handoff --run-id run_...
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR


IST = timezone(timedelta(hours=5, minutes=30))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="current")
    args = parser.parse_args()
    path = build_publish_handoff(args.run_id)
    print(f"[publish_handoff] Wrote: {path}")


def build_publish_handoff(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    run_id = manifest["run_id"]
    verification = _load_l8_package(run_id)
    if verification.get("status") != "approved":
        raise ValueError(f"Publish handoff requires L8 status='approved', got: {verification.get('status')}")

    final_publish = verification.get("final_publish_package")
    if not isinstance(final_publish, dict) or not final_publish:
        raise KeyError("L8 verification_package.json is missing final_publish_package")

    out_dir = OUTPUT_DIR / run_id / "publish_handoff"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "publish_handoff.md"
    path.write_text(_build_markdown(manifest, verification, final_publish), encoding="utf-8")
    return path


def _build_markdown(manifest: dict, verification: dict, final_publish: dict) -> str:
    metadata = final_publish.get("youtube_metadata", {})
    video = final_publish.get("video", {})
    lines = [
        f"# Publish Handoff — {manifest['run_id']}",
        "",
        f"Generated: {_iso_now()}",
        f"L8 status: {verification.get('status')}",
        f"Memory status: approved_not_published",
        f"Channel: {video.get('channel_name') or manifest['layer_0']['channel']['channel_name']}",
        f"Format: {final_publish.get('selected_format', video.get('selected_format', ''))}",
        "",
        "## Video Direction",
        "",
        f"Viewer promise: {video.get('viewer_promise', '')}",
        "",
        f"Editorial angle: {video.get('editorial_angle', '')}",
        "",
        f"Theme: {video.get('thesis_or_theme', '')}",
        "",
        "## Title Options",
        "",
    ]
    title_options = metadata.get("title_options", [])
    if title_options:
        for index, item in enumerate(title_options, start=1):
            if isinstance(item, dict):
                title = item.get("title", "")
                risk = item.get("accuracy_risk", "")
                click = item.get("click_potential", "")
                reason = item.get("why_it_works", "")
                lines.append(f"{index}. {title}  ")
                lines.append(f"   Accuracy risk: {risk} | Click potential: {click}  ")
                if reason:
                    lines.append(f"   Why: {reason}")
            else:
                lines.append(f"{index}. {item}")
    else:
        lines.append("No title options available.")

    lines.extend(["", "## Thumbnail Text Options", ""])
    for item in metadata.get("thumbnail_text_options", []):
        lines.append(f"- {item}")

    lines.extend(["", "## Description Draft", "", "```text", metadata.get("description_draft", ""), "```"])

    lines.extend(["", "## Chapters", ""])
    for chapter in metadata.get("chapters", []):
        lines.append(f"- {chapter.get('timestamp', '')} {chapter.get('title', '')}")

    lines.extend(["", "## Sources", ""])
    for url in metadata.get("source_urls", []):
        lines.append(f"- {url}")

    lines.extend(["", "## Tags", ""])
    lines.append(", ".join(metadata.get("tags", [])))

    lines.extend(["", "## Full Script", "", final_publish.get("narration_text", "")])

    visual_notes = final_publish.get("visual_notes", [])
    if visual_notes:
        lines.extend(["", "## Visual / Editor Notes", ""])
        for note in visual_notes:
            if isinstance(note, dict):
                section = note.get("section_id", "")
                text = note.get("note") or note.get("visual_note") or json.dumps(note, ensure_ascii=False)
                lines.append(f"- {section}: {text}")
            else:
                lines.append(f"- {note}")

    boundaries = final_publish.get("evidence_boundaries", {})
    blocked_angles = boundaries.get("blocked_angles", []) or video.get("blocked_angles", [])
    if blocked_angles:
        lines.extend(["", "## Blocked Angles", ""])
        for angle in blocked_angles:
            lines.append(f"- {angle}")

    lines.extend(
        [
            "",
            "## Publishing Status",
            "",
            "- This package is approved by L8.",
            "- It is not marked as published.",
            "- After upload, a later publish sync should record final title, YouTube video id, and published timestamp.",
            "",
        ]
    )
    return "\n".join(lines)


def _load_manifest(run_ref: str) -> dict:
    if run_ref == "current":
        path = CURRENT_MANIFEST_PATH
    else:
        path = OUTPUT_DIR / run_ref / "run_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Run manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if run_ref == "current":
        run_id = manifest.get("run_id")
        if not run_id:
            raise KeyError("output/current_manifest.json is missing run_id")
        path = OUTPUT_DIR / run_id / "run_manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"Run manifest not found: {path}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
    return manifest


def _load_l8_package(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L8" / "verification_package.json"
    if not path.exists():
        raise FileNotFoundError(f"L8 verification_package.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    main()
