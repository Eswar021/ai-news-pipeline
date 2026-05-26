"""
L7 Script — generate the roundup script package for L8.

Reads:
    output/{run_id}/run_manifest.json
    output/{run_id}/L6/content_packet.json

Writes:
    output/{run_id}/L7/script_package.json
    output/{run_id}/L7/summary.json
    output/{run_id}/L7/llm_calls.jsonl

LLM: yes, for section narration and draft title/thumbnail metadata.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.llm.prompt_loader import load_prompt_bundle
from src.pipeline.L7_script.checks import (
    build_evidence_usage,
    build_full_script,
    check_script_package,
    collect_visual_notes,
)
from src.pipeline.L7_script.formats.roundup import build_roundup_sections
from src.pipeline.L7_script.metadata import build_youtube_metadata
from src.pipeline.L7_script.writer import write_sections


IST = timezone(timedelta(hours=5, minutes=30))


def run(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    run_id = manifest["run_id"]
    layer7_cfg = _layer7_config(manifest)
    print(f"[L7] Run: {run_id}")

    content_packet = _load_l6_packet(run_id)
    selected_format = content_packet.get("video", {}).get("selected_format", content_packet.get("packet_type", ""))
    print(f"[L7] Input packet: {content_packet.get('packet_type', '')}  format={selected_format}")

    out_dir = OUTPUT_DIR / run_id / "L7"
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_calls_path = out_dir / "llm_calls.jsonl"
    llm_calls_path.write_text("", encoding="utf-8")

    if not content_packet.get("ready_for_layer_7", False):
        package = _build_no_video_package(run_id, content_packet)
        summary = _build_summary(package, llm_calls_path, content_packet)
        return _write_outputs(out_dir, package, summary)

    if selected_format != "roundup":
        raise NotImplementedError(
            f"Layer 7 format '{selected_format}' is not implemented yet. "
            "Only 'roundup' is active in the current rebuild."
        )

    script_prompt = load_prompt_bundle(
        "roundup_script_writer",
        layer7_cfg["script_writer_prompt_version"],
    )
    title_prompt = load_prompt_bundle(
        "title_thumbnail_planner",
        layer7_cfg["title_thumbnail_prompt_version"],
    )

    sections = build_roundup_sections(content_packet, layer7_cfg)
    print(f"[L7] Sections: {len(sections)}")
    section_scripts = write_sections(
        sections,
        manifest=manifest,
        layer7_cfg=layer7_cfg,
        prompt_bundle=script_prompt,
        log_path=llm_calls_path,
    )
    full_script = build_full_script(section_scripts)
    evidence_usage = build_evidence_usage(section_scripts, content_packet)
    visual_notes = collect_visual_notes(section_scripts)

    package = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "package_type": "roundup_script",
        "status": "ready_for_layer_8",
        "video": _build_video(content_packet, manifest),
        "section_scripts": section_scripts,
        "full_script": full_script,
        "youtube_metadata": {},
        "source_index": content_packet.get("source_index", []),
        "evidence_boundaries": content_packet.get("evidence_boundaries", {}),
        "evidence_usage": evidence_usage,
        "visual_notes": visual_notes,
        "layer8_handoff": _build_layer8_handoff(content_packet, section_scripts, evidence_usage),
    }
    package["youtube_metadata"] = build_youtube_metadata(
        package_draft=package,
        content_packet=content_packet,
        manifest=manifest,
        layer7_cfg=layer7_cfg,
        prompt_bundle=title_prompt,
        log_path=llm_calls_path,
    )

    checks = check_script_package(package, content_packet)
    if not checks["passed"]:
        raise ValueError(f"L7 script package checks failed: {checks['errors']}")

    summary = _build_summary(package, llm_calls_path, content_packet, checks)
    print(
        f"[L7] Script words: {full_script['total_word_count']}  "
        f"estimated={full_script['estimated_duration_seconds']}s  "
        f"sources={len(package['source_index'])}"
    )
    return _write_outputs(out_dir, package, summary)


def _build_no_video_package(run_id: str, content_packet: dict) -> dict:
    return {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "package_type": "no_video_script",
        "status": "no_video",
        "video": content_packet.get("video", {}),
        "section_scripts": [],
        "full_script": {
            "narration_text": "",
            "total_word_count": 0,
            "estimated_duration_seconds": 0,
            "section_order": [],
        },
        "youtube_metadata": {
            "title_options": [],
            "thumbnail_text_options": [],
            "blocked_title_angles": [],
            "chapters": [],
            "description_draft": "",
            "tags": [],
            "source_urls": [],
        },
        "source_index": content_packet.get("source_index", []),
        "evidence_boundaries": content_packet.get("evidence_boundaries", {}),
        "evidence_usage": {
            "used_fact_ids": [],
            "required_fact_ids": [],
            "required_cautious_fact_ids": [],
            "used_required_fact_ids": [],
            "omitted_required_fact_ids": [],
            "section_usage": [],
            "fact_index": {},
        },
        "visual_notes": [],
        "layer8_handoff": {
            "ready_for_layer_8": False,
            "reason": "No video selected upstream.",
        },
    }


def _build_video(content_packet: dict, manifest: dict) -> dict:
    video = dict(content_packet["video"])
    video["channel_name"] = manifest["layer_0"]["channel"]["channel_name"]
    video["content_promise"] = manifest["layer_0"]["channel"].get("content_promise", "")
    video["script_style"] = manifest.get("layer_7", {}).get("script_style", "")
    video["script_style_description"] = manifest.get("layer_7", {}).get("script_style_description", "")
    return video


def _build_layer8_handoff(content_packet: dict, section_scripts: list[dict], evidence_usage: dict) -> dict:
    return {
        "ready_for_layer_8": True,
        "package_type": "roundup_script",
        "selected_format": "roundup",
        "section_count": len(section_scripts),
        "required_fact_ids": evidence_usage["required_fact_ids"],
        "required_cautious_fact_ids": evidence_usage["required_cautious_fact_ids"],
        "used_fact_ids": evidence_usage["used_fact_ids"],
        "source_ref_ids": list(content_packet.get("layer7_handoff", {}).get("source_ref_ids", [])),
        "unsupported_claim_rule": content_packet.get("layer7_handoff", {}).get(
            "unsupported_claim_rule",
            "Layer 8 must verify the script against this package only.",
        ),
    }


def _write_outputs(out_dir: Path, package: dict, summary: dict) -> Path:
    package_path = out_dir / "script_package.json"
    summary_path = out_dir / "summary.json"
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[L7] Wrote: {package_path}")
    return package_path


def _build_summary(
    package: dict,
    llm_calls_path: Path,
    content_packet: dict,
    checks: dict | None = None,
) -> dict:
    role_mix = Counter(section.get("role", "") for section in package.get("section_scripts", []) if section.get("role"))
    section_type_mix = Counter(section.get("section_type", "") for section in package.get("section_scripts", []))
    evidence_usage = package.get("evidence_usage", {})
    return {
        "run_id": package["run_id"],
        "generated_at": _iso_now(),
        "status": package["status"],
        "package_type": package["package_type"],
        "selected_format": package.get("video", {}).get("selected_format", ""),
        "script_style": package.get("video", {}).get("script_style", ""),
        "section_count": len(package.get("section_scripts", [])),
        "story_section_count": section_type_mix.get("story", 0),
        "role_mix": dict(role_mix),
        "total_word_count": package.get("full_script", {}).get("total_word_count", 0),
        "estimated_duration_seconds": package.get("full_script", {}).get("estimated_duration_seconds", 0),
        "source_count": len(package.get("source_index", [])),
        "title_option_count": len(package.get("youtube_metadata", {}).get("title_options", [])),
        "thumbnail_option_count": len(package.get("youtube_metadata", {}).get("thumbnail_text_options", [])),
        "required_fact_count": len(evidence_usage.get("required_fact_ids", [])),
        "required_cautious_fact_count": len(evidence_usage.get("required_cautious_fact_ids", [])),
        "used_fact_count": len(evidence_usage.get("used_fact_ids", [])),
        "omitted_required_fact_count": len(evidence_usage.get("omitted_required_fact_ids", [])),
        "input_segment_count": len(content_packet.get("segment_plan", [])),
        "llm_call_count": _count_lines(llm_calls_path),
        "checks": checks or {"passed": package["status"] == "no_video", "errors": [], "warnings": []},
    }


def _layer7_config(manifest: dict) -> dict:
    cfg = manifest.get("layer_7")
    if not isinstance(cfg, dict):
        raise KeyError(
            "run_manifest.json is missing layer_7 config. "
            "Rerun Layer 0 after adding L7, then rerun the required upstream layers."
        )
    required = [
        "script_writer_model",
        "script_writer_prompt_version",
        "script_worker_count",
        "words_per_minute",
        "title_thumbnail_model",
        "title_thumbnail_prompt_version",
    ]
    missing = [key for key in required if key not in cfg]
    if missing:
        raise KeyError(f"run_manifest.json layer_7 missing required keys: {missing}")
    return cfg


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
        run_manifest_path = OUTPUT_DIR / run_id / "run_manifest.json"
        if not run_manifest_path.exists():
            raise FileNotFoundError(f"Run manifest not found: {run_manifest_path}")
        manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    return manifest


def _load_l6_packet(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L6" / "content_packet.json"
    if not path.exists():
        raise FileNotFoundError(f"L6 content_packet.json not found: {path}")
    packet = json.loads(path.read_text(encoding="utf-8"))
    if "packet_type" not in packet or "video" not in packet:
        raise KeyError("L6 content_packet.json is missing required packet_type or video keys")
    return packet


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="current")
    args = parser.parse_args()
    run(args.run_id)
