from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.pipeline.handoffs.common import clean_text, iso_now

from .contract import ChatGPTExporterRequest


PROMPT_MODULE = "chatgpt_exporter"
PROMPTS_DIR = Path(__file__).parent / "prompts"

PROFILE_ORDER = [
    "script_review",
    "visual_scene_plan",
    "content_packet",
    "story_map",
]

PROFILE_ALIASES = {
    "auto": "auto",
    "story": "story_map",
    "story_map": "story_map",
    "packet": "content_packet",
    "content_packet": "content_packet",
    "script": "script_review",
    "script_review": "script_review",
    "visual": "visual_scene_plan",
    "visuals": "visual_scene_plan",
    "visual_plan": "visual_scene_plan",
    "visual_scene_plan": "visual_scene_plan",
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
            f"Prompt source: `src/pipeline/handoffs/chatgpt_exporter/prompts/{prompt_version}/{PROMPT_MODULE}/{profile}.md`",
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
        "run_context": manifest,
        "module_summaries": summaries,
    }
    return "\n".join(
        [
            f"# Manifest Context - {run_id}",
            "",
            "This file contains the frozen run context and module summaries for ChatGPT.",
            "",
            "Use it for run profile, prompt/model choices, timing, caps, and production policy.",
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
    if profile == "content_packet":
        return _content_packet_summary(artifact)
    if profile == "script_review":
        return _script_review_summary(artifact)
    if profile == "visual_scene_plan":
        return _visual_scene_plan_summary(artifact)
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


def _content_packet_summary(artifact: dict[str, Any]) -> list[str]:
    packet = artifact.get("data", {}).get("video_packet", artifact)
    stories = packet.get("stories", []) if isinstance(packet.get("stories"), list) else []
    lines = [
        f"- Packet type: {packet.get('packet_type', '')}",
        f"- Selected format: {packet.get('selected_format', '')}",
        f"- Target duration: {packet.get('target_duration_seconds', '')}s",
        f"- Selected stories: {len(stories)}",
        "",
        "### Selected Story Plan",
        "",
    ]
    for story in sorted(stories, key=lambda item: (item.get("video_segment") or {}).get("segment_order", 999)):
        segment = story.get("video_segment") or {}
        lines.append(
            f"- {segment.get('segment_order', '?')}. {story.get('story_title', '')} "
            f"role={segment.get('role', '')} target={segment.get('target_seconds', '')}s "
            f"records={len(story.get('records', []))}"
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
    sections = package.get("sections", [])
    return [
        f"- Package type: {package.get('package_type', '')}",
        f"- Status: {artifact.get('status', package.get('status', ''))}",
        f"- Total words: {word_count}",
        f"- Estimated duration: {estimated_seconds}s",
        f"- Sections: {len(sections)}",
        f"- Generation source: {package.get('generation_source', 'native_app')}",
    ]


def _visual_scene_plan_summary(artifact: dict[str, Any]) -> list[str]:
    script = artifact.get("script", {}) if isinstance(artifact.get("script"), dict) else {}
    video_packet = artifact.get("video_packet", {}) if isinstance(artifact.get("video_packet"), dict) else {}
    voiceover = artifact.get("voiceover_timing", {}) if isinstance(artifact.get("voiceover_timing"), dict) else {}
    visual_context = artifact.get("visual_context", {}) if isinstance(artifact.get("visual_context"), dict) else {}
    scene_policy = visual_context.get("scene_policy", {}) if isinstance(visual_context.get("scene_policy"), dict) else {}
    capabilities = visual_context.get("visual_capabilities", {}) if isinstance(visual_context.get("visual_capabilities"), dict) else {}
    stories = video_packet.get("stories") or video_packet.get("selected_stories") or []
    chunks = voiceover.get("chunks") if isinstance(voiceover.get("chunks"), list) else []
    return [
        f"- Packet type: {artifact.get('package_type', '')}",
        f"- Selected format: {artifact.get('selected_format', video_packet.get('selected_format', ''))}",
        f"- Script words: {script.get('word_count', '')}",
        f"- Voiceover duration: {voiceover.get('duration_seconds', '')}s",
        f"- Voiceover chunks: {len(chunks)}",
        f"- Selected stories: {len(stories) if isinstance(stories, list) else ''}",
        f"- Max scene seconds: {scene_policy.get('max_scene_seconds', '')}",
        f"- Allowed render kinds: {', '.join(scene_policy.get('allowed_render_kinds', []))}",
        f"- Visual capabilities: {len(capabilities)}",
    ]


def _run_context_lines(manifest: dict[str, Any]) -> list[str]:
    profile = manifest.get("profile_config", {}) if isinstance(manifest.get("profile_config"), dict) else {}
    packaging = profile.get("video_packaging", {}) if isinstance(profile.get("video_packaging"), dict) else {}
    script = profile.get("script_generation", {}) if isinstance(profile.get("script_generation"), dict) else {}
    lines = [
        f"- Run ID: `{manifest.get('run_id', '')}`",
        f"- Created: `{manifest.get('created_at', '')}`",
        f"- Run profile: `{manifest.get('run_profile', '')}`",
        f"- Target format: `{packaging.get('target_format', '')}`",
        f"- Script model: `{script.get('provider', '')}/{script.get('model', '')}`",
        f"- Config hash: `{manifest.get('pipeline_config_sha256', '')}`",
    ]
    return lines


def _load_export_prompt(name: str, prompt_version: str) -> str:
    path = PROMPTS_DIR / prompt_version / PROMPT_MODULE / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"ChatGPT exporter prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _safe_run_id(input_json: dict[str, Any]) -> str:
    run = input_json.get("run", {}) if isinstance(input_json, dict) else {}
    return clean_text(run.get("run_id")) or "unknown"
