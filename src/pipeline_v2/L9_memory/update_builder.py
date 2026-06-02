"""
Build the Layer 9 memory update from an approved Layer 8 package.

L9 records an approved script candidate, not a published YouTube upload.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


IST = timezone(timedelta(hours=5, minutes=30))
MEMORY_STATUS = "approved_not_published"


def build_memory_update(manifest: dict, verification_package: dict) -> dict:
    _validate_approved_package(verification_package)

    final_publish = verification_package["final_publish_package"]
    script_package = verification_package.get("verified_script_package", {})
    video = final_publish.get("video", {})
    metadata = final_publish.get("youtube_metadata", {})
    evidence_usage = final_publish.get("evidence_usage", {})
    evidence_boundaries = final_publish.get("evidence_boundaries", {})
    source_index = final_publish.get("source_index", [])
    sections = script_package.get("section_scripts", [])
    full_script = script_package.get("full_script", {})
    approved_at = verification_package.get("generated_at") or _iso_now()

    story_memory = _build_story_memory(sections, source_index)
    source_memory = _build_source_memory(source_index)
    evidence_memory = _build_evidence_memory(evidence_usage, evidence_boundaries)
    video_memory = _build_video_memory(
        manifest=manifest,
        final_publish=final_publish,
        script_package=script_package,
        video=video,
        metadata=metadata,
        story_memory=story_memory,
        source_memory=source_memory,
        evidence_memory=evidence_memory,
        full_script=full_script,
        approved_at=approved_at,
    )

    return {
        "run_id": manifest["run_id"],
        "generated_at": _iso_now(),
        "package_type": "memory_update",
        "status": "applied",
        "memory_status": MEMORY_STATUS,
        "video_memory": video_memory,
        "story_memory": story_memory,
        "source_memory": source_memory,
        "evidence_memory": evidence_memory,
        "publish_sync": {
            "publish_status": "not_published",
            "can_promote_to_published": True,
            "required_publish_fields": [
                "final_title",
                "youtube_video_id",
                "published_at",
            ],
            "note": "L9 records an approved script candidate. A later publish sync may promote it to published.",
        },
    }


def _validate_approved_package(package: dict) -> None:
    if package.get("status") != "approved":
        raise ValueError(f"Layer 9 requires L8 status='approved', got: {package.get('status')}")

    handoff = package.get("layer9_handoff")
    if not isinstance(handoff, dict) or not handoff.get("ready_for_layer_9"):
        raise ValueError("Layer 9 requires layer9_handoff.ready_for_layer_9=true")

    final_publish = package.get("final_publish_package")
    if not isinstance(final_publish, dict) or not final_publish:
        raise KeyError("Layer 8 package is missing final_publish_package")

    required = ["video", "youtube_metadata", "source_index", "evidence_usage"]
    missing = [key for key in required if key not in final_publish]
    if missing:
        raise KeyError(f"final_publish_package missing required keys: {missing}")


def _build_video_memory(
    manifest: dict,
    final_publish: dict,
    script_package: dict,
    video: dict,
    metadata: dict,
    story_memory: list[dict],
    source_memory: list[dict],
    evidence_memory: dict,
    full_script: dict,
    approved_at: str,
) -> dict:
    run_id = manifest["run_id"]
    channel_cfg = manifest.get("layer_0", {}).get("channel", {})
    selected_format = final_publish.get("selected_format") or video.get("selected_format")

    return {
        "run_id": run_id,
        "approved_at": approved_at,
        "memory_status": MEMORY_STATUS,
        "publish_status": "not_published",
        "selected_format": selected_format,
        "channel_name": video.get("channel_name") or channel_cfg.get("channel_name"),
        "viewer_promise": video.get("viewer_promise", ""),
        "editorial_angle": video.get("editorial_angle", ""),
        "thesis_or_theme": video.get("thesis_or_theme", ""),
        "tone": video.get("tone", ""),
        "title_options": metadata.get("title_options", []),
        "thumbnail_text_options": metadata.get("thumbnail_text_options", []),
        "blocked_angles": video.get("blocked_angles", []),
        "blocked_title_angles": metadata.get("blocked_title_angles", []),
        "chapter_count": len(metadata.get("chapters", [])),
        "story_count": len(story_memory),
        "source_count": len(source_memory),
        "used_fact_count": len(evidence_memory["used_fact_ids"]),
        "cautious_fact_count": len(evidence_memory["cautious_fact_ids"]),
        "script_word_count": full_script.get("total_word_count"),
        "estimated_duration_seconds": full_script.get("estimated_duration_seconds"),
        "package_type": script_package.get("package_type"),
    }


def _build_story_memory(sections: list[dict], source_index: list[dict]) -> list[dict]:
    urls_by_story: dict[str, list[str]] = {}
    for source in source_index:
        url = source.get("source_url")
        if not url:
            continue
        for story_id in source.get("used_story_ids", []):
            urls_by_story.setdefault(story_id, [])
            if url not in urls_by_story[story_id]:
                urls_by_story[story_id].append(url)

    stories = []
    for section in sections:
        if section.get("section_type") != "story":
            continue
        story_id = section.get("story_id", "")
        stories.append(
            {
                "story_id": story_id,
                "story_title": section.get("title", ""),
                "chapter_title": section.get("chapter_title", ""),
                "section_id": section.get("section_id", ""),
                "section_order": section.get("section_order"),
                "role": section.get("role", ""),
                "word_count": section.get("word_count"),
                "estimated_seconds": section.get("estimated_seconds"),
                "used_fact_ids": section.get("used_fact_ids", []),
                "required_fact_ids": section.get("required_fact_ids", []),
                "required_cautious_fact_ids": section.get("required_cautious_fact_ids", []),
                "source_urls": urls_by_story.get(story_id, []),
            }
        )
    return stories


def _build_source_memory(source_index: list[dict]) -> list[dict]:
    sources = []
    seen = set()
    for source in source_index:
        url = source.get("source_url", "")
        key = url or source.get("record_key", "")
        if not key or key in seen:
            continue
        seen.add(key)
        sources.append(
            {
                "source_url": url,
                "source_name": source.get("source_name", ""),
                "source_group": source.get("source_group", ""),
                "source_relationship": source.get("source_relationship", ""),
                "published_at": source.get("published_at", ""),
                "trust_tier": source.get("trust_tier"),
                "used_story_ids": source.get("used_story_ids", []),
                "supported_fact_ids": source.get("supported_fact_ids", []),
                "recommended_for_description": bool(source.get("recommended_for_description")),
            }
        )
    return sources


def _build_evidence_memory(evidence_usage: dict, evidence_boundaries: dict) -> dict:
    return {
        "used_fact_ids": evidence_usage.get("used_fact_ids", []),
        "required_fact_ids": evidence_usage.get("required_fact_ids", []),
        "required_cautious_fact_ids": evidence_usage.get("required_cautious_fact_ids", []),
        "omitted_required_fact_ids": evidence_usage.get("omitted_required_fact_ids", []),
        "cautious_fact_ids": evidence_boundaries.get("cautious_fact_ids", []),
        "safe_fact_ids": evidence_boundaries.get("safe_fact_ids", []),
        "blocked_fact_ids": evidence_boundaries.get("blocked_fact_ids", []),
        "blocked_claims": evidence_boundaries.get("blocked_claims", []),
        "caution_notes": evidence_boundaries.get("caution_notes", []),
    }


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
