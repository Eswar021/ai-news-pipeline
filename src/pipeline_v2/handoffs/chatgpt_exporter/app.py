from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.pipeline_v2.handoffs.common import clean_text, iso_now

from .contract import ChatGPTExporterRequest


PROMPT_MODULE = "chatgpt_exporter"
PROMPTS_DIR = Path(__file__).parent / "prompts"

PROFILE_ORDER = [
    "publish_review",
    "script_review",
    "content_packet",
    "editorial_brief",
    "fact_packet",
    "story_map",
]

PROFILE_ALIASES = {
    "auto": "auto",
    "l3": "story_map",
    "story": "story_map",
    "story_map": "story_map",
    "after_layer_3": "story_map",
    "l4": "fact_packet",
    "facts": "fact_packet",
    "fact_packet": "fact_packet",
    "after_layer_4": "fact_packet",
    "l5": "editorial_brief",
    "editorial": "editorial_brief",
    "editorial_brief": "editorial_brief",
    "l6": "content_packet",
    "packet": "content_packet",
    "content_packet": "content_packet",
    "after_layer_6": "content_packet",
    "l7": "script_review",
    "script": "script_review",
    "script_review": "script_review",
    "l8": "publish_review",
    "publish": "publish_review",
    "publish_review": "publish_review",
}


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    try:
        request = ChatGPTExporterRequest.model_validate(input_json)
        profile = _resolve_profile(request.config.profile, request.input.artifacts)
        artifact = request.input.artifacts[profile]
        files = _build_files(
            run_id=request.run.run_id,
            manifest=request.input.manifest,
            profile=profile,
            artifact=artifact,
            summaries=request.input.summaries,
            prompt_version=request.config.prompt_version,
        )
        return {
            "status": "ok",
            "data": {
                "run_id": request.run.run_id,
                "generated_at": iso_now(),
                "profile": profile,
                "handoff_package": {
                    "package_type": "chatgpt_handoff",
                    "files": files,
                },
            },
            "summary": {
                "profile": profile,
                "file_count": len(files),
                "artifact_keys": sorted(request.input.artifacts.keys()),
                "summary_count": len(request.input.summaries),
            },
            "handoff": {
                "ready_for_write": True,
                "output_dir": request.config.output_dir,
            },
        }
    except Exception as exc:
        return {
            "status": "failed",
            "data": {
                "run_id": _safe_run_id(input_json),
                "generated_at": iso_now(),
                "profile": None,
                "handoff_package": {"package_type": "chatgpt_handoff", "files": []},
            },
            "summary": {"error": str(exc)},
            "handoff": {"ready_for_write": False},
        }


def _build_files(
    *,
    run_id: str,
    manifest: dict[str, Any],
    profile: str,
    artifact: dict[str, Any],
    summaries: dict[str, Any],
    prompt_version: str,
) -> list[dict[str, str]]:
    return [
        {
            "filename": "01_instructions.md",
            "content_type": "text/markdown",
            "content": _build_instructions(run_id, manifest, profile, prompt_version),
        },
        {
            "filename": "02_payload.md",
            "content_type": "text/markdown",
            "content": _build_payload(run_id, profile, artifact),
        },
        {
            "filename": "03_manifest_context.md",
            "content_type": "text/markdown",
            "content": _build_manifest_context(run_id, manifest, summaries, profile),
        },
    ]


def _resolve_profile(profile: str, artifacts: dict[str, dict[str, Any]]) -> str:
    normalized = PROFILE_ALIASES.get(clean_text(profile).lower())
    if not normalized:
        available = ", ".join(["auto"] + PROFILE_ORDER)
        raise ValueError(f"Unknown ChatGPT export profile '{profile}'. Available: {available}")
    if normalized != "auto":
        if normalized not in artifacts:
            raise KeyError(f"Profile '{normalized}' is missing from input.artifacts")
        return normalized
    for candidate in PROFILE_ORDER:
        if candidate in artifacts:
            return candidate
    raise KeyError("No supported handoff artifact found in input.artifacts")


def _build_instructions(run_id: str, manifest: dict[str, Any], profile: str, prompt_version: str) -> str:
    base_prompt = _load_export_prompt("base", prompt_version)
    profile_prompt = _load_export_prompt(profile, prompt_version)
    return "\n".join(
        [
            f"# ChatGPT Handoff Instructions - {run_id}",
            "",
            f"Generated: {iso_now()}",
            f"Export profile: `{profile}`",
            f"Prompt source: `src/pipeline_v2/handoffs/chatgpt_exporter/prompts/{prompt_version}/{PROMPT_MODULE}/{profile}.md`",
            "",
            "## How To Use",
            "",
            "1. Paste this file first.",
            "2. Paste `02_payload.md` next.",
            "3. Paste `03_manifest_context.md` only if you need the full run/config context.",
            "",
            "## Run Context",
            "",
            *_run_context_lines(manifest),
            "",
            "## Base Instructions",
            "",
            base_prompt,
            "",
            "## Profile Instructions",
            "",
            profile_prompt,
            "",
        ]
    )


def _build_payload(run_id: str, profile: str, artifact: dict[str, Any]) -> str:
    lines = [
        f"# ChatGPT Handoff Payload - {profile}",
        "",
        f"Run ID: `{run_id}`",
        f"Profile: `{profile}`",
        "",
        "## Compact Summary",
        "",
    ]
    lines.extend(_profile_summary_lines(profile, artifact))
    lines.extend(
        [
            "",
            "## Main Artifact JSON",
            "",
            "```json",
            json.dumps(artifact, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _build_manifest_context(run_id: str, manifest: dict[str, Any], summaries: dict[str, Any], profile: str) -> str:
    context = {
        "export_profile": profile,
        "generated_at": iso_now(),
        "run_manifest": manifest,
        "layer_summaries": summaries,
    }
    return "\n".join(
        [
            f"# Manifest Context - {run_id}",
            "",
            "This file contains the run manifest and layer summaries for ChatGPT context.",
            "",
            "Use it for run profile, source scope, prompt/model choices, timing, caps, and verification status.",
            "",
            "```json",
            json.dumps(context, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )


def _profile_summary_lines(profile: str, artifact: dict[str, Any]) -> list[str]:
    if profile == "story_map":
        return _story_map_summary(artifact)
    if profile == "fact_packet":
        return _fact_packet_summary(artifact)
    if profile == "editorial_brief":
        return _editorial_brief_summary(artifact)
    if profile == "content_packet":
        return _content_packet_summary(artifact)
    if profile == "script_review":
        return _script_review_summary(artifact)
    if profile == "publish_review":
        return _publish_review_summary(artifact)
    raise ValueError(f"Unsupported profile summary: {profile}")


def _story_map_summary(artifact: dict[str, Any]) -> list[str]:
    stories = artifact.get("stories") or artifact.get("data", {}).get("stories", [])
    lines = [f"- Stories: {len(stories)}", "", "### Top Stories", ""]
    for story in sorted(stories, key=lambda item: item.get("rank", 999))[:20]:
        lines.append(
            f"- Rank {story.get('rank', '?')}: {story.get('story_title', story.get('title', ''))} "
            f"score={story.get('rank_score', '')} records={story.get('record_count', '')} "
            f"bucket={story.get('priority_bucket', '')}"
        )
    return lines


def _fact_packet_summary(artifact: dict[str, Any]) -> list[str]:
    packets = artifact.get("fact_packets") or artifact.get("data", {}).get("fact_packets", [])
    lines = [f"- Fact packets: {len(packets)}", "", "### Fact Packet Overview", ""]
    for packet in packets[:20]:
        lines.append(
            f"- Rank {packet.get('rank', '?')}: {packet.get('story_title', '')} "
            f"readiness={packet.get('readiness', '')} "
            f"safe={len(packet.get('safe_facts', []))} "
            f"cautious={len(packet.get('cautious_facts', []))} "
            f"discarded={len(packet.get('discarded_facts', []))}"
        )
    return lines


def _editorial_brief_summary(artifact: dict[str, Any]) -> list[str]:
    decision = artifact.get("decision", {})
    video = artifact.get("selected_video", {})
    stories = artifact.get("selected_stories", [])
    lines = [
        f"- Decision: {decision.get('action', '')}",
        f"- Selected format: {decision.get('selected_format', video.get('format', ''))}",
        f"- Target duration: {decision.get('target_duration_seconds', video.get('target_duration_seconds', ''))}s",
        f"- Selected stories: {len(stories)}",
        f"- Viewer promise: {video.get('viewer_promise', '')}",
        f"- Editorial angle: {video.get('editorial_angle', '')}",
        "",
        "### Selected Stories",
        "",
    ]
    for story in stories:
        lines.append(f"- {story.get('story_title', '')} readiness={story.get('readiness', '')}")
    return lines


def _content_packet_summary(artifact: dict[str, Any]) -> list[str]:
    video = artifact.get("video", {})
    segments = artifact.get("segment_plan", [])
    lines = [
        f"- Packet type: {artifact.get('packet_type', '')}",
        f"- Status: {artifact.get('status', '')}",
        f"- Selected format: {video.get('selected_format', '')}",
        f"- Target duration: {video.get('target_duration_seconds', '')}s",
        f"- Segments: {len(segments)}",
        "",
        "### Segment Plan",
        "",
    ]
    for segment in segments:
        lines.append(
            f"- {segment.get('segment_order', '?')}. {segment.get('story_title', '')} "
            f"role={segment.get('role', '')} target={segment.get('target_seconds', '')}s "
            f"required_facts={len(segment.get('required_fact_ids', []))}"
        )
    return lines


def _script_review_summary(artifact: dict[str, Any]) -> list[str]:
    package = artifact.get("data", {}).get("script_package", artifact)
    full_script = package.get("full_script", {})
    if isinstance(full_script, str):
        word_count = len(full_script.split())
        estimated_seconds = int(word_count / 150 * 60) if word_count else 0
    else:
        word_count = full_script.get("total_word_count", "")
        estimated_seconds = full_script.get("estimated_duration_seconds", "")
    metadata = package.get("youtube_metadata", {})
    sections = package.get("section_scripts") or package.get("sections", [])
    return [
        f"- Package type: {package.get('package_type', '')}",
        f"- Status: {artifact.get('status', package.get('status', ''))}",
        f"- Total words: {word_count}",
        f"- Estimated duration: {estimated_seconds}s",
        f"- Sections: {len(sections)}",
        f"- Title options: {len(metadata.get('title_options', []))}",
    ]


def _publish_review_summary(artifact: dict[str, Any]) -> list[str]:
    decision = artifact.get("decision", {})
    final_publish = artifact.get("final_publish_package", {})
    metadata = final_publish.get("youtube_metadata", {})
    lines = [
        f"- Verification status: {artifact.get('status', '')}",
        f"- Ready for memory/update: {decision.get('ready_for_layer_9', artifact.get('layer9_handoff', {}).get('ready_for_layer_9', ''))}",
        f"- Selected format: {final_publish.get('selected_format', '')}",
        f"- Title options: {len(metadata.get('title_options', []))}",
        f"- Thumbnail options: {len(metadata.get('thumbnail_text_options', []))}",
        f"- Source URLs: {len(metadata.get('source_urls', []))}",
        "",
        "### Title Options",
        "",
    ]
    for index, title in enumerate(metadata.get("title_options", []), start=1):
        lines.append(f"{index}. {title.get('title', '') if isinstance(title, dict) else title}")
    return lines


def _run_context_lines(manifest: dict[str, Any]) -> list[str]:
    layer0 = manifest.get("layer_0", {})
    channel = layer0.get("channel", {})
    layer1 = manifest.get("layer_1", {})
    layer5 = manifest.get("layer_5", {})
    collection_window = layer0.get("collection_window", {})
    lookback_hours = collection_window.get("lookback_hours", collection_window.get("hours", ""))
    lines = [
        f"- Run ID: `{manifest.get('run_id', '')}`",
        f"- Run date: `{manifest.get('run_date', '')}`",
        f"- Run profile: `{layer0.get('run_profile', '')}`",
        f"- Channel: `{channel.get('channel_name', '')}`",
        f"- Target format: `{layer5.get('target_format', '')}`",
        f"- Collection window: `{lookback_hours}` hours",
        f"- Enabled source groups: {', '.join(layer1.get('enabled_source_groups', []))}",
        f"- Query themes: {', '.join(layer1.get('query_themes', []))}",
    ]
    if channel.get("content_promise"):
        lines.append(f"- Content promise: {channel['content_promise']}")
    return lines


def _load_export_prompt(name: str, prompt_version: str) -> str:
    path = PROMPTS_DIR / prompt_version / PROMPT_MODULE / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"ChatGPT exporter prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _safe_run_id(input_json: dict[str, Any]) -> str:
    run = input_json.get("run", {}) if isinstance(input_json, dict) else {}
    return clean_text(run.get("run_id")) or "unknown"
