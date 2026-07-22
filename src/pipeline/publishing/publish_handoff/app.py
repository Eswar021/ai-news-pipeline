from __future__ import annotations

from typing import Any

from src.pipeline.contracts import (
    build_artifact_provenance,
    final_video_artifact_payload,
    require_matching_run_id,
    require_parent_fingerprint,
    validate_artifact_provenance,
    validate_script_provenance,
    voiceover_artifact_payload,
)
from src.pipeline.handoffs.common import clean_text, iso_now

from .contract import PublishHandoffRequest


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    try:
        request = PublishHandoffRequest.model_validate(input_json)
        script_package = request.input.script_generation.get("data", {}).get("script_package", {})
        metadata_package = request.input.metadata_finalizer.get("data", {}).get("metadata_package", {})
        metadata = metadata_package.get("youtube_metadata", {})
        video_packet = request.input.video_packaging.get("data", {}).get("video_packet", {})
        voiceover_package = _voiceover_package(request.input.voiceover)
        final_video_package = request.input.video_assembly.get("data", {}).get("final_video_package", {})
        render_mode = clean_text(final_video_package.get("render_mode") or "final")
        if render_mode != "final":
            raise ValueError(
                f"Publish handoff requires a final-quality video assembly; received render_mode={render_mode!r}"
            )
        visual_review_package = (
            (request.input.visual_review or {}).get("data", {}).get("visual_review_package", {})
        )
        require_matching_run_id(request.run.run_id, request.input.run_context.get("run_id"), "run_context")
        require_matching_run_id(
            request.run.run_id,
            request.input.video_packaging.get("data", {}).get("run_id"),
            "video_packaging",
        )
        narration = clean_text(script_package.get("full_script", ""))
        if not narration:
            raise ValueError("script_generation.data.script_package.full_script is empty")
        if not metadata:
            raise ValueError("metadata_finalizer.data.metadata_package.youtube_metadata is missing")
        _validate_lineage(
            run_id=request.run.run_id,
            script_generation=request.input.script_generation,
            script_package=script_package,
            metadata_package=metadata_package,
            voiceover_package=voiceover_package,
            video_assembly=request.input.video_assembly,
            final_video_package=final_video_package,
        )
        _validate_visual_review(visual_review_package, final_video_package)

        content = _build_markdown(
            run_id=request.run.run_id,
            run_context=request.input.run_context,
            video_packet=video_packet,
            script_package=script_package,
            metadata=metadata,
            voiceover=request.input.voiceover,
            video_assembly=request.input.video_assembly,
            visual_review=request.input.visual_review,
        )
        files = [{"filename": "publish_review.md", "content_type": "text/markdown", "content": content}]
        script_provenance = script_package["provenance"]
        package = {
            "package_type": "manual_publish_review",
            "files": files,
        }
        package["provenance"] = build_artifact_provenance(
            artifact_type="publish_handoff",
            run_id=request.run.run_id,
            parents={
                "script": script_provenance["script_fingerprint"],
                "voiceover": voiceover_package["provenance"]["voiceover_fingerprint"],
                "visual_plan": final_video_package["provenance"]["visual_plan_fingerprint"],
                "final_video": final_video_package["provenance"]["artifact_fingerprint"],
                "metadata_final": metadata_package["provenance"]["artifact_fingerprint"],
            },
            script_source=script_provenance.get("script_source", ""),
            payload={"filenames": [item["filename"] for item in files]},
        )
        return {
            "status": "ok",
            "data": {
                "run_id": request.run.run_id,
                "generated_at": iso_now(),
                "publish_handoff_package": package,
            },
            "summary": {
                "file_count": 1,
                "title_option_count": len(metadata.get("title_options", [])),
                "source_url_count": len(metadata.get("source_urls", [])),
                "script_word_count": len(narration.split()),
                "voiceover_attached": True,
                "video_attached": True,
                "chapters_finalized": True,
                "contact_sheet_attached": bool(visual_review_package),
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
    visual_review: dict[str, Any] | None,
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
        f"- Captions: {_caption_paths(voiceover) or 'not attached'}",
        f"- Final video: {_media_path(video_assembly, 'final_video_path') or 'not attached'}",
        f"- Contact sheet: {_contact_sheet_path(visual_review) or 'not attached'}",
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
            "- Open the contact sheet and scan for wrong identities, repetition, tiny text, and visual drift.",
            "- Confirm names, numbers, and on-screen text.",
            "- Pick one title and thumbnail combination.",
            "- Confirm description, chapters, and source links.",
            "- Upload the generated captions and verify cue timing.",
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


def _voiceover_package(value: dict[str, Any]) -> dict[str, Any]:
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    if isinstance(data.get("voiceover_package"), dict):
        return data["voiceover_package"]
    if isinstance(value.get("voiceover_package"), dict):
        return value["voiceover_package"]
    return value


def _contact_sheet_path(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    package = (value.get("data") or {}).get("visual_review_package") or {}
    return clean_text(package.get("contact_sheet_path"))


def _caption_paths(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    package = _voiceover_package(value)
    files = (package.get("captions") or {}).get("files", [])
    return ", ".join(
        clean_text(item.get("path"))
        for item in files
        if isinstance(item, dict) and clean_text(item.get("path"))
    )


def _validate_visual_review(
    visual_review_package: dict[str, Any],
    final_video_package: dict[str, Any],
) -> None:
    if not visual_review_package:
        return
    contact_sheet_path = clean_text(visual_review_package.get("contact_sheet_path"))
    if not contact_sheet_path:
        raise ValueError("visual_review contact_sheet_path is missing")
    expected_hash = clean_text(final_video_package.get("final_video_sha256"))
    reviewed_hash = clean_text(visual_review_package.get("final_video_sha256"))
    if expected_hash and reviewed_hash != expected_hash:
        raise ValueError("visual_review was generated from a different final video")


def _validate_lineage(
    *,
    run_id: str,
    script_generation: dict[str, Any],
    script_package: dict[str, Any],
    metadata_package: dict[str, Any],
    voiceover_package: dict[str, Any],
    video_assembly: dict[str, Any],
    final_video_package: dict[str, Any],
) -> None:
    script_data = script_generation.get("data") or {}
    video_data = video_assembly.get("data") or {}
    require_matching_run_id(run_id, script_data.get("run_id"), "script_generation")
    require_matching_run_id(run_id, voiceover_package.get("run_id"), "voiceover")
    require_matching_run_id(run_id, video_data.get("run_id"), "video_assembly")
    require_matching_run_id(
        run_id,
        (metadata_package.get("provenance") or {}).get("run_id"),
        "metadata_finalizer",
    )
    script_provenance = validate_script_provenance(
        script_package,
        run_id=run_id,
        upstream_run_id=script_data.get("run_id"),
    )
    script_fingerprint = script_provenance["script_fingerprint"]
    voiceover_provenance = voiceover_package.get("provenance")
    if voiceover_package.get("status") != "ready":
        raise ValueError("voiceover package status must be ready")
    validate_artifact_provenance(
        voiceover_provenance,
        artifact_type="voiceover",
        run_id=run_id,
        payload=voiceover_artifact_payload(voiceover_package),
        label="voiceover",
    )
    require_parent_fingerprint(
        voiceover_provenance,
        parent_name="script",
        expected=script_fingerprint,
        label="voiceover",
    )
    voiceover_fingerprint = voiceover_provenance["voiceover_fingerprint"]
    validate_artifact_provenance(
        metadata_package.get("provenance"),
        artifact_type="metadata_final",
        run_id=run_id,
        payload=metadata_package.get("youtube_metadata") or {},
        label="metadata_finalizer",
    )
    require_parent_fingerprint(
        metadata_package.get("provenance"),
        parent_name="script",
        expected=script_fingerprint,
        label="metadata_finalizer",
    )
    require_parent_fingerprint(
        metadata_package.get("provenance"),
        parent_name="voiceover",
        expected=voiceover_fingerprint,
        label="metadata_finalizer",
    )
    require_parent_fingerprint(
        final_video_package.get("provenance"),
        parent_name="script",
        expected=script_fingerprint,
        label="final_video",
    )
    validate_artifact_provenance(
        final_video_package.get("provenance"),
        artifact_type="final_video",
        run_id=run_id,
        payload=final_video_artifact_payload(final_video_package),
        label="final_video",
    )
    require_parent_fingerprint(
        final_video_package.get("provenance"),
        parent_name="voiceover",
        expected=voiceover_fingerprint,
        label="final_video",
    )
    if metadata_package.get("package_stage") != "final":
        raise ValueError("metadata package must be finalized after voiceover")
    if not clean_text(final_video_package.get("final_video_path")):
        raise ValueError("final_video_package.final_video_path is missing")
    metadata = metadata_package.get("youtube_metadata") or {}
    if not bool((metadata.get("metadata_basis") or {}).get("chapters_finalized")):
        raise ValueError("metadata chapters are not finalized")


def _safe_run_id(input_json: dict[str, Any]) -> str:
    return clean_text((input_json.get("run") or {}).get("run_id")) or "unknown"
