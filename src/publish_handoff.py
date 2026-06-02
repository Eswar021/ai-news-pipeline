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
import re

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR


IST = timezone(timedelta(hours=5, minutes=30))
INTERNAL_FACT_ID_RE = re.compile(r"\bfact_[a-z0-9_]+\b", re.IGNORECASE)


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
    issues = _quality_issues(final_publish)
    status_line = "Do not publish yet - rerun the script step first." if issues else "Ready for human review."
    title_options = metadata.get("title_options", [])
    thumbnail_options = metadata.get("thumbnail_text_options", [])
    chapters = metadata.get("chapters", [])
    source_urls = metadata.get("source_urls", [])
    story_chapters = [
        chapter.get("title", "")
        for chapter in chapters
        if chapter.get("title") not in {"Intro", "Closing"}
    ]
    first_title = _title_text(title_options[0]) if title_options else ""
    lines = [
        f"# Publishing Preview - {manifest['run_id']}",
        "",
        "This is the human review file before upload. It is meant to be easy to read, not a pipeline report.",
        "",
        "## Quick Check",
        "",
        f"- Review status: {status_line}",
        f"- Pipeline status: L8 {verification.get('status')}",
        "- Publish status: not uploaded yet",
        f"- Channel: {video.get('channel_name') or manifest['layer_0']['channel']['channel_name']}",
        f"- Format: {final_publish.get('selected_format', video.get('selected_format', ''))}",
        f"- Generated: {_iso_now()}",
        "",
        "## Before You Upload",
        "",
    ]
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
        lines.extend(
            [
                "- Suggested next step: rerun `python3 -m src.pipeline.runner 7 8 --run-id current` after the code fix, then rebuild this preview.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "- Read the script once out loud.",
                "- Pick one title and one thumbnail line.",
                "- Confirm the source links are the ones you want in the description.",
                "",
            ]
        )

    lines.extend(
        [
            "## What This Video Is",
            "",
            _plain_video_summary(story_chapters),
            "",
            f"Viewer promise: {_plain_text(video.get('viewer_promise', ''))}",
            "",
            f"Tone: {_plain_text(video.get('tone', ''))}",
            "",
        ]
    )

    if first_title:
        lines.extend(["## Suggested First Title", "", first_title, ""])

    lines.extend(["## Other Title Options", ""])
    if title_options:
        for index, item in enumerate(title_options, start=1):
            title = _title_text(item)
            if not title:
                continue
            details = _title_details(item)
            lines.append(f"{index}. {title}")
            if details:
                lines.append(f"   {details}")
    else:
        lines.append("No title options available.")

    lines.extend(["", "## Thumbnail Text Ideas", ""])
    if thumbnail_options:
        for item in thumbnail_options:
            lines.append(f"- {_thumbnail_text(item)}")
    else:
        lines.append("No thumbnail text options available.")

    lines.extend(["", "## YouTube Description", "", "```text", metadata.get("description_draft", ""), "```"])

    lines.extend(["", "## Chapters", ""])
    for chapter in chapters:
        lines.append(f"- {chapter.get('timestamp', '')} {chapter.get('title', '')}")

    lines.extend(["", "## Script To Record", ""])
    if issues:
        lines.append("Warning: fix the issues above before recording or uploading this script.")
        lines.append("")
    lines.append(final_publish.get("narration_text", ""))

    lines.extend(["", "## Sources", ""])
    for url in source_urls:
        lines.append(f"- {url}")

    lines.extend(["", "## Tags To Copy", ""])
    lines.append(", ".join(metadata.get("tags", [])))

    visual_notes = final_publish.get("visual_notes", [])
    if visual_notes:
        lines.extend(["", "## Simple Editor Notes", ""])
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
        lines.extend(["", "## Avoid Saying These Things", ""])
        for angle in blocked_angles:
            lines.append(f"- {angle}")

    lines.extend(
        [
            "",
            "## After Upload",
            "",
            "- This run is stored as approved_not_published.",
            "- After upload, run the later publish sync with the final title, YouTube video id, and published timestamp.",
            "",
        ]
    )
    return "\n".join(lines)


def _quality_issues(final_publish: dict) -> list[str]:
    issues = []
    narration = final_publish.get("narration_text", "")
    leaked = sorted(set(INTERNAL_FACT_ID_RE.findall(narration)))
    if leaked:
        issues.append(
            "Internal fact IDs appear in the spoken script. They should never be read aloud. "
            f"Examples: {', '.join(leaked[:3])}"
        )
    return issues


def _plain_video_summary(story_chapters: list[str]) -> str:
    if not story_chapters:
        return "This is an AI news roundup."
    if len(story_chapters) == 1:
        return f"This is a short AI news video about {story_chapters[0]}."
    visible = ", ".join(story_chapters[:5])
    if len(story_chapters) > 5:
        visible += f", and {story_chapters[-1]}"
    return f"This is a {len(story_chapters)}-story AI news roundup covering {visible}."


def _title_text(item) -> str:
    if isinstance(item, dict):
        return _plain_text(item.get("title", ""))
    return _plain_text(str(item or ""))


def _title_details(item) -> str:
    if not isinstance(item, dict):
        return ""
    parts = []
    if item.get("accuracy_risk"):
        parts.append(f"risk: {item['accuracy_risk']}")
    if item.get("click_potential"):
        parts.append(f"click: {item['click_potential']}")
    if item.get("why_it_works"):
        parts.append(_plain_text(item["why_it_works"]))
    return " | ".join(parts)


def _thumbnail_text(item) -> str:
    if isinstance(item, dict):
        return _plain_text(item.get("text", ""))
    return _plain_text(str(item or ""))


def _plain_text(value: str) -> str:
    return " ".join(str(value or "").split())


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
