from __future__ import annotations

from typing import Any

from src.pipeline.handoffs.common import clean_text, iso_now

from .contract import PublishHandoffRequest


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    try:
        request = PublishHandoffRequest.model_validate(input_json)
        script_package = request.input.script_generation.get("data", {}).get("script_package", {})
        metadata = (
            request.input.metadata_creator.get("data", {})
            .get("metadata_package", {})
            .get("youtube_metadata", {})
        )
        video_packet = request.input.video_packaging.get("data", {}).get("video_packet", {})
        narration = clean_text(script_package.get("full_script", ""))
        if not narration:
            raise ValueError("script_generation.data.script_package.full_script is empty")
        if not metadata:
            raise ValueError("metadata_creator.data.metadata_package.youtube_metadata is missing")

        content = _build_markdown(
            run_id=request.run.run_id,
            run_context=request.input.run_context,
            video_packet=video_packet,
            script_package=script_package,
            metadata=metadata,
            voiceover=request.input.voiceover,
            video_assembly=request.input.video_assembly,
        )
        files = [{"filename": "publish_review.md", "content_type": "text/markdown", "content": content}]
        return {
            "status": "ok",
            "data": {
                "run_id": request.run.run_id,
                "generated_at": iso_now(),
                "publish_handoff_package": {"package_type": "manual_publish_review", "files": files},
            },
            "summary": {
                "file_count": 1,
                "title_option_count": len(metadata.get("title_options", [])),
                "source_url_count": len(metadata.get("source_urls", [])),
                "script_word_count": len(narration.split()),
                "voiceover_attached": request.input.voiceover is not None,
                "video_attached": request.input.video_assembly is not None,
            },
            "handoff": {"ready_for_write": True, "ready_for_manual_publish_review": True},
        }
    except Exception as exc:
        return {
            "status": "failed",
            "data": {
                "run_id": _safe_run_id(input_json),
                "generated_at": iso_now(),
                "publish_handoff_package": {"package_type": "manual_publish_review", "files": []},
            },
            "summary": {"error": str(exc)},
            "handoff": {"ready_for_write": False, "ready_for_manual_publish_review": False},
        }


def _build_markdown(
    *,
    run_id: str,
    run_context: dict[str, Any],
    video_packet: dict[str, Any],
    script_package: dict[str, Any],
    metadata: dict[str, Any],
    voiceover: dict[str, Any] | None,
    video_assembly: dict[str, Any] | None,
) -> str:
    titles = metadata.get("title_options", [])
    thumbnails = metadata.get("thumbnail_text_options", [])
    chapters = metadata.get("chapters", [])
    source_urls = metadata.get("source_urls", [])
    lines = [
        f"# Manual Publish Review - {run_id}",
        "",
        "This package is ready for a human editorial and playback review. It is not an automated publish approval.",
        "",
        "## Run",
        "",
        f"- Profile: {run_context.get('run_profile', '')}",
        f"- Format: {video_packet.get('selected_format', '')}",
        f"- Selected stories: {len(video_packet.get('stories', []))}",
        f"- Script words: {len(clean_text(script_package.get('full_script', '')).split())}",
        f"- Voiceover: {_media_path(voiceover, 'audio_path') or 'not attached'}",
        f"- Final video: {_media_path(video_assembly, 'final_video_path') or 'not attached'}",
        "",
        "## Title Options",
        "",
    ]
    for index, item in enumerate(titles, start=1):
        title = clean_text(item.get("title") if isinstance(item, dict) else item)
        if title:
            lines.append(f"{index}. {title}")
    lines.extend(["", "## Thumbnail Text", ""])
    lines.extend(f"- {clean_text(item)}" for item in thumbnails if clean_text(item))
    lines.extend(["", "## Description", "", metadata.get("description_draft", ""), "", "## Chapters", ""])
    for chapter in chapters:
        lines.append(f"- {chapter.get('timestamp', '')} {chapter.get('title', '')}")
    lines.extend(["", "## Sources", ""])
    lines.extend(f"- {url}" for url in source_urls)
    lines.extend(["", "## Narration", "", script_package.get("full_script", ""), "", "## Final Checklist", ""])
    lines.extend(
        [
            "- Watch the complete video with headphones.",
            "- Confirm visuals match the active narration beats.",
            "- Confirm names, numbers, and on-screen text.",
            "- Pick one title and thumbnail combination.",
            "- Confirm description, chapters, and source links.",
            "- Upload manually only after these checks pass.",
            "",
        ]
    )
    return "\n".join(lines)


def _media_path(envelope: dict[str, Any] | None, key: str) -> str:
    if not envelope:
        return ""
    summary = envelope.get("summary", {}) if isinstance(envelope, dict) else {}
    return clean_text(summary.get(key, ""))


def _safe_run_id(input_json: dict[str, Any]) -> str:
    return clean_text((input_json.get("run") or {}).get("run_id")) or "unknown"
