"""
L6 Package — build the production content packet for L7.

Reads:
    output/{run_id}/run_manifest.json
    output/{run_id}/L5/selected_video_brief.json

Writes:
    output/{run_id}/L6/content_packet.json
    output/{run_id}/L6/summary.json

LLM: no
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.pipeline.L6_package.formats.roundup import build_roundup_package
from src.pipeline.L6_package.source_index import build_source_index


IST = timezone(timedelta(hours=5, minutes=30))


def run(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    run_id = manifest["run_id"]
    print(f"[L6] Run: {run_id}")

    brief = _load_l5_brief(run_id)
    decision = brief["decision"]
    selected_format = decision.get("selected_format", "")
    print(f"[L6] Input format: {selected_format}  action={decision.get('action', '')}")

    out_dir = OUTPUT_DIR / run_id / "L6"
    out_dir.mkdir(parents=True, exist_ok=True)

    if decision.get("action") == "no_video":
        packet = _build_no_video_packet(run_id, brief)
    elif selected_format == "roundup":
        packet = _build_roundup_packet(run_id, brief)
    else:
        raise NotImplementedError(
            f"Layer 6 format '{selected_format}' is not implemented yet. "
            "Only 'roundup' is active in the current rebuild."
        )

    summary = _build_summary(packet)
    packet_path = out_dir / "content_packet.json"
    summary_path = out_dir / "summary.json"
    packet_path.write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"[L6] Status: {packet['status']}  "
        f"segments={len(packet['segment_plan'])}  sources={len(packet['source_index'])}"
    )
    print(f"[L6] Wrote: {packet_path}")
    return packet_path


def _build_roundup_packet(run_id: str, brief: dict) -> dict:
    built = build_roundup_package(brief)
    source_index = build_source_index(built["segment_plan"])
    return {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "packet_type": "roundup",
        "status": "ready_for_layer_7",
        "ready_for_layer_7": True,
        "decision": brief["decision"],
        "video": built["video"],
        "segment_plan": built["segment_plan"],
        "source_index": source_index,
        "evidence_boundaries": _build_evidence_boundaries(brief),
        "layer7_handoff": {
            **built["layer7_handoff"],
            "source_ref_ids": [source["source_ref_id"] for source in source_index],
            "unsupported_claim_rule": (
                "Layer 7 must use only facts carried in this content_packet and must not "
                "introduce unsupported claims."
            ),
        },
    }


def _build_no_video_packet(run_id: str, brief: dict) -> dict:
    return {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "packet_type": brief.get("decision", {}).get("selected_format", "none"),
        "status": "no_video",
        "ready_for_layer_7": False,
        "decision": brief.get("decision", {}),
        "video": {
            "selected_format": brief.get("decision", {}).get("selected_format", "none"),
            "target_duration_seconds": 0,
            "viewer_promise": "",
            "editorial_angle": "",
            "thesis_or_theme": "",
            "opening_hook_direction": "",
            "tone": "",
            "blocked_angles": [],
        },
        "segment_plan": [],
        "source_index": [],
        "evidence_boundaries": _build_evidence_boundaries(brief),
        "layer7_handoff": {
            "ready_for_layer_7": False,
            "selected_format": brief.get("decision", {}).get("selected_format", "none"),
            "packet_type": brief.get("decision", {}).get("selected_format", "none"),
            "target_duration_seconds": 0,
            "intro_seconds": 0,
            "closing_seconds": 0,
            "segment_count": 0,
            "segment_ids": [],
            "required_fact_ids": [],
            "cautious_fact_ids": [],
            "source_record_keys": [],
            "source_ref_ids": [],
            "unsupported_claim_rule": "No video selected; Layer 7 must not generate a script.",
        },
    }


def _build_evidence_boundaries(brief: dict) -> dict:
    l5_boundaries = brief.get("evidence_boundaries", {})
    discarded_fact_ids = []
    for story in brief.get("selected_stories", []):
        discarded_fact_ids.extend(fact["fact_id"] for fact in story.get("discarded_facts", []))

    return {
        "safe_fact_ids": list(l5_boundaries.get("safe_fact_ids", [])),
        "cautious_fact_ids": list(l5_boundaries.get("cautious_fact_ids", [])),
        "discarded_fact_ids": _dedupe(discarded_fact_ids),
        "blocked_fact_ids": _dedupe(discarded_fact_ids),
        "caution_notes": list(l5_boundaries.get("caution_notes", [])),
        "blocked_claims": list(l5_boundaries.get("blocked_claims", [])),
        "blocked_angles": list(l5_boundaries.get("blocked_angles", [])),
        "unsupported_claim_rule": (
            "L7 may use only facts included in segment_plan.safe_facts, "
            "segment_plan.cautious_facts, required_facts, or optional_facts."
        ),
    }


def _build_summary(packet: dict) -> dict:
    segment_plan = packet.get("segment_plan", [])
    required_fact_ids = []
    optional_fact_ids = []
    cautious_only_segments = 0
    role_mix = Counter()
    for segment in segment_plan:
        role_mix.update([segment.get("role", "unknown")])
        required_fact_ids.extend(segment.get("required_fact_ids", []))
        optional_fact_ids.extend(segment.get("optional_fact_ids", []))
        if segment.get("cautious_fact_ids") and not segment.get("safe_fact_ids"):
            cautious_only_segments += 1

    boundaries = packet.get("evidence_boundaries", {})
    return {
        "run_id": packet["run_id"],
        "generated_at": _iso_now(),
        "status": packet["status"],
        "packet_type": packet["packet_type"],
        "ready_for_layer_7": packet["ready_for_layer_7"],
        "selected_format": packet.get("decision", {}).get("selected_format", ""),
        "segment_count": len(segment_plan),
        "source_count": len(packet.get("source_index", [])),
        "role_mix": dict(role_mix),
        "required_fact_count": len(_dedupe(required_fact_ids)),
        "optional_fact_count": len(_dedupe(optional_fact_ids)),
        "safe_fact_count": len(boundaries.get("safe_fact_ids", [])),
        "cautious_fact_count": len(boundaries.get("cautious_fact_ids", [])),
        "discarded_fact_count": len(boundaries.get("discarded_fact_ids", [])),
        "cautious_only_segment_count": cautious_only_segments,
    }


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


def _load_l5_brief(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L5" / "selected_video_brief.json"
    if not path.exists():
        raise FileNotFoundError(f"L5 selected_video_brief.json not found: {path}")
    brief = json.loads(path.read_text(encoding="utf-8"))
    if "decision" not in brief or "selected_video" not in brief:
        raise KeyError("L5 selected_video_brief.json is missing required decision or selected_video keys")
    return brief


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    kept = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        kept.append(value)
    return kept


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="current")
    args = parser.parse_args()
    run(args.run_id)
