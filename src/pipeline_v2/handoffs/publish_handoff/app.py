from __future__ import annotations

import json
import re
from typing import Any

from src.pipeline_v2.handoffs.common import clean_text, iso_now

from .contract import PublishHandoffRequest


INTERNAL_FACT_ID_RE = re.compile(r"\bfact_[a-z0-9_]+\b", re.IGNORECASE)


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    try:
        request = PublishHandoffRequest.model_validate(input_json)
        verification = request.input.verification_package
        if request.config.require_approved and verification.get("status") != "approved":
            raise ValueError(f"Publish handoff requires status='approved', got: {verification.get('status')}")
        final_publish = verification.get("final_publish_package")
        if not isinstance(final_publish, dict) or not final_publish:
            raise KeyError("verification_package is missing final_publish_package")

        content = _build_markdown(request.input.manifest, verification, final_publish)
        files = [{"filename": "publish_handoff.md", "content_type": "text/markdown", "content": content}]
        return {
            "status": "ok",
            "data": {
                "run_id": request.run.run_id,
                "generated_at": iso_now(),
                "publish_handoff_package": {
                    "package_type": "publish_handoff",
                    "files": files,
                },
            },
            "summary": {
                "file_count": len(files),
                "quality_issue_count": len(_quality_issues(final_publish)),
                "title_option_count": len(final_publish.get("youtube_metadata", {}).get("title_options", [])),
                "source_url_count": len(final_publish.get("youtube_metadata", {}).get("source_urls", [])),
            },
            "handoff": {"ready_for_write": True, "output_dir": request.config.output_dir},
        }
    except Exception as exc:
        return {
            "status": "failed",
            "data": {
                "run_id": _safe_run_id(input_json),
                "generated_at": iso_now(),
                "publish_handoff_package": {"package_type": "publish_handoff", "files": []},
            },
            "summary": {"error": str(exc)},
            "handoff": {"ready_for_write": False},
        }


def _build_markdown(manifest: dict[str, Any], verification: dict[str, Any], final_publish: dict[str, Any]) -> str:
    metadata = final_publish.get("youtube_metadata", {})
    video = final_publish.get("video", {})
    issues = _quality_issues(final_publish)
    verification_status = clean_text(verification.get("status"))
    if verification_status != "approved":
        status_line = (
            f"Draft/unapproved package ({verification_status or 'unknown status'}). "
            "Use for human review only; do not publish until verification approves it."
        )
    elif issues:
        status_line = "Do not publish yet - rerun the script/verification steps first."
    else:
        status_line = "Ready for human review."
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
        f"# Publishing Preview - {manifest.get('run_id', '')}",
        "",
        "This is the human review file before upload. It is meant to be easy to read, not a pipeline report.",
        "",
        "## Quick Check",
        "",
        f"- Review status: {status_line}",
        f"- Verification status: {verification.get('status')}",
        "- Publish status: not uploaded yet",
        f"- Channel: {_channel_name(manifest, video)}",
        f"- Format: {final_publish.get('selected_format', video.get('selected_format', ''))}",
        f"- Generated: {iso_now()}",
        "",
        "## Before You Upload",
        "",
    ]
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
        lines.extend(["- Suggested next step: regenerate or revise the script, then rebuild this preview.", ""])
    elif verification_status != "approved":
        lines.extend(
            [
                "- This is a draft handoff because the v2 verification app has not approved it yet.",
                "- Use it to review script, title, thumbnail, description, sources, and voiceover readiness.",
                "- Do not upload from this handoff until a verification step approves the publish package.",
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
            f"Viewer promise: {clean_text(video.get('viewer_promise', ''))}",
            "",
            f"Tone: {clean_text(video.get('tone', ''))}",
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

    blocked_angles = final_publish.get("evidence_boundaries", {}).get("blocked_angles", []) or video.get("blocked_angles", [])
    if blocked_angles:
        lines.extend(["", "## Avoid Saying These Things", ""])
        for angle in blocked_angles:
            lines.append(f"- {angle}")

    lines.extend(["", "## After Upload", "", "- Save the final title, URL, published timestamp, and performance notes for future memory updates.", ""])
    return "\n".join(lines)


def _quality_issues(final_publish: dict[str, Any]) -> list[str]:
    narration = final_publish.get("narration_text", "")
    leaked = sorted(set(INTERNAL_FACT_ID_RE.findall(narration)))
    if not leaked:
        return []
    return [
        "Internal fact IDs appear in the spoken script. They should never be read aloud. "
        f"Examples: {', '.join(leaked[:3])}"
    ]


def _plain_video_summary(story_chapters: list[str]) -> str:
    if not story_chapters:
        return "This is an AI news roundup."
    if len(story_chapters) == 1:
        return f"This is a short AI news video about {story_chapters[0]}."
    visible = ", ".join(story_chapters[:5])
    if len(story_chapters) > 5:
        visible += f", and {story_chapters[-1]}"
    return f"This is a {len(story_chapters)}-story AI news roundup covering {visible}."


def _title_text(item: Any) -> str:
    if isinstance(item, dict):
        return clean_text(item.get("title", ""))
    return clean_text(item)


def _title_details(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    parts = []
    if item.get("accuracy_risk"):
        parts.append(f"risk: {item['accuracy_risk']}")
    if item.get("click_potential"):
        parts.append(f"click: {item['click_potential']}")
    if item.get("why_it_works"):
        parts.append(clean_text(item["why_it_works"]))
    return " | ".join(parts)


def _thumbnail_text(item: Any) -> str:
    if isinstance(item, dict):
        return clean_text(item.get("text", ""))
    return clean_text(item)


def _channel_name(manifest: dict[str, Any], video: dict[str, Any]) -> str:
    return clean_text(
        video.get("channel_name")
        or manifest.get("layer_0", {}).get("channel", {}).get("channel_name")
        or manifest.get("channel", {}).get("channel_name")
    )


def _safe_run_id(input_json: dict[str, Any]) -> str:
    run_info = input_json.get("run", {}) if isinstance(input_json, dict) else {}
    return clean_text(run_info.get("run_id")) or "unknown"
