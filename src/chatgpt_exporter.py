"""
ChatGPT handoff exporter for the rebuilt src pipeline.

This is a helper tool, not a pipeline layer.

Reads:
    output/{run_id}/run_manifest.json
    output/{run_id}/L3-L8 main artifacts, depending on export profile

Writes:
    output/chatgpt_handoffs/{run_id}/{profile}/01_instructions.md
    output/chatgpt_handoffs/{run_id}/{profile}/02_payload.md
    output/chatgpt_handoffs/{run_id}/{profile}/03_manifest_context.md

Usage:
    python3 -m src.chatgpt_exporter --run-id current
    python3 -m src.chatgpt_exporter --run-id current --profile script_review
    python3 -m src.chatgpt_exporter --run-id current --profile publish_review
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR, PROMPTS_DIR
from src.pipeline.L1_collection.common import clean_text


IST = timezone(timedelta(hours=5, minutes=30))
HANDOFFS_DIR = OUTPUT_DIR / "chatgpt_handoffs"
PROMPT_VERSION = "v1"
PROMPT_MODULE = "chatgpt_exporter"

PROFILE_ORDER = [
    "publish_review",
    "script_review",
    "content_packet",
    "editorial_brief",
    "fact_packet",
    "story_map",
]

PROFILE_ARTIFACTS = {
    "story_map": ("L3", "stories.json"),
    "fact_packet": ("L4", "fact_packets.json"),
    "editorial_brief": ("L5", "selected_video_brief.json"),
    "content_packet": ("L6", "content_packet.json"),
    "script_review": ("L7", "script_package.json"),
    "publish_review": ("L8", "verification_package.json"),
}

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ChatGPT handoff files for rebuild runs")
    parser.add_argument("--run-id", default="current")
    parser.add_argument("--profile", default="auto", help=f"auto or one of: {', '.join(PROFILE_ORDER)}")
    args = parser.parse_args()

    result = export(run_ref=args.run_id, profile=args.profile)
    print(f"[chatgpt_exporter] Wrote: {result['out_dir']}")
    print(f"  Profile      : {result['profile']}")
    print(f"  Instructions : {result['instructions_path']}")
    print(f"  Payload      : {result['payload_path']}")
    print(f"  Manifest     : {result['manifest_path']}")


def export(run_ref: str = "current", profile: str = "auto") -> dict:
    manifest = _load_manifest(run_ref)
    run_id = manifest["run_id"]
    run_dir = OUTPUT_DIR / run_id
    resolved_profile = _resolve_profile(profile, run_dir)
    artifact = _load_profile_artifact(run_dir, resolved_profile)
    summaries = _load_summaries(run_dir)

    out_dir = HANDOFFS_DIR / run_id / resolved_profile
    out_dir.mkdir(parents=True, exist_ok=True)

    instructions = _build_instructions(manifest, resolved_profile)
    payload = _build_payload(manifest, resolved_profile, artifact)
    context = _build_manifest_context(manifest, summaries, resolved_profile)

    instructions_path = out_dir / "01_instructions.md"
    payload_path = out_dir / "02_payload.md"
    manifest_path = out_dir / "03_manifest_context.md"
    instructions_path.write_text(instructions, encoding="utf-8")
    payload_path.write_text(payload, encoding="utf-8")
    manifest_path.write_text(context, encoding="utf-8")

    return {
        "run_id": run_id,
        "profile": resolved_profile,
        "out_dir": str(out_dir),
        "instructions_path": str(instructions_path),
        "payload_path": str(payload_path),
        "manifest_path": str(manifest_path),
    }


def _load_manifest(run_ref: str) -> dict:
    if run_ref == "current":
        if not CURRENT_MANIFEST_PATH.exists():
            raise FileNotFoundError(f"Current manifest not found: {CURRENT_MANIFEST_PATH}")
        current = json.loads(CURRENT_MANIFEST_PATH.read_text(encoding="utf-8"))
        run_id = current.get("run_id")
        if not run_id:
            raise KeyError("output/current_manifest.json is missing run_id")
        path = OUTPUT_DIR / run_id / "run_manifest.json"
    else:
        path = OUTPUT_DIR / run_ref / "run_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Run manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_profile(profile: str, run_dir: Path) -> str:
    normalized = PROFILE_ALIASES.get(clean_text(profile).lower())
    if not normalized:
        available = ", ".join(["auto"] + PROFILE_ORDER)
        raise ValueError(f"Unknown ChatGPT export profile '{profile}'. Available: {available}")
    if normalized != "auto":
        _require_profile_artifact(run_dir, normalized)
        return normalized
    for candidate in PROFILE_ORDER:
        if _profile_artifact_path(run_dir, candidate).exists():
            return candidate
    raise FileNotFoundError(
        f"No completed rebuild artifacts found for ChatGPT export in: {run_dir}. "
        "Expected at least L3/stories.json."
    )


def _load_profile_artifact(run_dir: Path, profile: str) -> dict:
    path = _require_profile_artifact(run_dir, profile)
    return json.loads(path.read_text(encoding="utf-8"))


def _require_profile_artifact(run_dir: Path, profile: str) -> Path:
    path = _profile_artifact_path(run_dir, profile)
    if not path.exists():
        layer, filename = PROFILE_ARTIFACTS[profile]
        raise FileNotFoundError(f"Profile '{profile}' requires {layer}/{filename}: {path}")
    return path


def _profile_artifact_path(run_dir: Path, profile: str) -> Path:
    layer, filename = PROFILE_ARTIFACTS[profile]
    return run_dir / layer / filename


def _load_summaries(run_dir: Path) -> dict:
    summaries = {}
    for layer_dir in sorted(run_dir.glob("L*/summary.json")):
        summaries[layer_dir.parent.name] = json.loads(layer_dir.read_text(encoding="utf-8"))
    return summaries


def _build_instructions(manifest: dict, profile: str) -> str:
    base_prompt = _load_export_prompt("base")
    profile_prompt = _load_export_prompt(profile)
    run_context = _run_context_lines(manifest)
    return "\n".join(
        [
            f"# ChatGPT Handoff Instructions — {manifest['run_id']}",
            "",
            f"Generated: {_iso_now()}",
            f"Export profile: `{profile}`",
            f"Prompt source: `prompts/{PROMPT_VERSION}/{PROMPT_MODULE}/{profile}.md`",
            "",
            "## How To Use",
            "",
            "1. Paste this file first.",
            "2. Paste `02_payload.md` next.",
            "3. Paste `03_manifest_context.md` only if you need the full run/config context.",
            "",
            "## Run Context",
            "",
            *run_context,
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


def _build_payload(manifest: dict, profile: str, artifact: dict) -> str:
    lines = [
        f"# ChatGPT Handoff Payload — {profile}",
        "",
        f"Run ID: `{manifest['run_id']}`",
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


def _build_manifest_context(manifest: dict, summaries: dict, profile: str) -> str:
    context = {
        "export_profile": profile,
        "generated_at": _iso_now(),
        "run_manifest": manifest,
        "layer_summaries": summaries,
    }
    lines = [
        f"# Manifest Context — {manifest['run_id']}",
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
    return "\n".join(lines)


def _profile_summary_lines(profile: str, artifact: dict) -> list[str]:
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


def _story_map_summary(artifact: dict) -> list[str]:
    stories = artifact.get("stories", [])
    lines = [
        f"- Stories: {len(stories)}",
        "",
        "### Top Stories",
        "",
    ]
    for story in sorted(stories, key=lambda item: item.get("rank", 999))[:20]:
        lines.append(
            f"- Rank {story.get('rank', '?')}: {story.get('story_title', '')} "
            f"score={story.get('rank_score', '')} records={story.get('record_count', '')} "
            f"bucket={story.get('priority_bucket', '')}"
        )
    return lines


def _fact_packet_summary(artifact: dict) -> list[str]:
    packets = artifact.get("fact_packets", [])
    lines = [
        f"- Fact packets: {len(packets)}",
        "",
        "### Fact Packet Overview",
        "",
    ]
    for packet in packets[:20]:
        lines.append(
            f"- Rank {packet.get('rank', '?')}: {packet.get('story_title', '')} "
            f"readiness={packet.get('readiness', '')} "
            f"safe={len(packet.get('safe_facts', []))} "
            f"cautious={len(packet.get('cautious_facts', []))} "
            f"discarded={len(packet.get('discarded_facts', []))}"
        )
    return lines


def _editorial_brief_summary(artifact: dict) -> list[str]:
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


def _content_packet_summary(artifact: dict) -> list[str]:
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


def _script_review_summary(artifact: dict) -> list[str]:
    full_script = artifact.get("full_script", {})
    metadata = artifact.get("youtube_metadata", {})
    sections = artifact.get("section_scripts", [])
    lines = [
        f"- Package type: {artifact.get('package_type', '')}",
        f"- Status: {artifact.get('status', '')}",
        f"- Total words: {full_script.get('total_word_count', '')}",
        f"- Estimated duration: {full_script.get('estimated_duration_seconds', '')}s",
        f"- Sections: {len(sections)}",
        f"- Title options: {len(metadata.get('title_options', []))}",
        "",
        "### Sections",
        "",
    ]
    for section in sections:
        lines.append(
            f"- {section.get('section_order', '?')}. {section.get('chapter_title', section.get('title', ''))} "
            f"words={section.get('word_count', '')} facts={len(section.get('used_fact_ids', []))}"
        )
    return lines


def _publish_review_summary(artifact: dict) -> list[str]:
    decision = artifact.get("decision", {})
    final_publish = artifact.get("final_publish_package", {})
    metadata = final_publish.get("youtube_metadata", {})
    lines = [
        f"- Verification status: {artifact.get('status', '')}",
        f"- Ready for L9: {decision.get('ready_for_layer_9', artifact.get('layer9_handoff', {}).get('ready_for_layer_9', ''))}",
        f"- Selected format: {final_publish.get('selected_format', '')}",
        f"- Title options: {len(metadata.get('title_options', []))}",
        f"- Thumbnail options: {len(metadata.get('thumbnail_text_options', []))}",
        f"- Source URLs: {len(metadata.get('source_urls', []))}",
        "",
        "### Title Options",
        "",
    ]
    for index, title in enumerate(metadata.get("title_options", []), start=1):
        if isinstance(title, dict):
            lines.append(f"{index}. {title.get('title', '')}")
        else:
            lines.append(f"{index}. {title}")
    return lines


def _run_context_lines(manifest: dict) -> list[str]:
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


def _load_export_prompt(name: str) -> str:
    path = PROMPTS_DIR / PROMPT_VERSION / PROMPT_MODULE / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"ChatGPT exporter prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    main()
