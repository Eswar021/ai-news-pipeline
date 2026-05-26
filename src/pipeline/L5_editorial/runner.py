"""
L5 Editorial — build a roundup-first video brief from grounded L4 fact packets.

Reads:
    output/{run_id}/run_manifest.json
    output/{run_id}/L4/fact_packets.json

Writes:
    output/{run_id}/L5/selected_video_brief.json
    output/{run_id}/L5/summary.json
    output/{run_id}/L5/llm_calls.jsonl

LLM: yes
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.llm.prompt_loader import load_prompt_bundle
from src.pipeline.L5_editorial.brief_builder import build_selected_video
from src.pipeline.L5_editorial.candidate_builder import build_candidates, compact_candidate_evaluation
from src.pipeline.L5_editorial.formats.roundup import choose_roundup, evaluate_candidates, mark_selected
from src.pipeline.L5_editorial.viewer_value import add_viewer_values


IST = timezone(timedelta(hours=5, minutes=30))


def run(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    layer5_cfg = manifest.get("layer_5")
    if not isinstance(layer5_cfg, dict):
        raise KeyError("run_manifest.json is missing layer_5 config. Re-run layer 0 after adding L5.")
    target_format = _resolve_target_format(layer5_cfg)

    run_id = manifest["run_id"]
    print(f"[L5] Run: {run_id}")
    print(f"[L5] Target format: {target_format}")
    fact_packets_payload = _load_l4_fact_packets(run_id)
    fact_packets = fact_packets_payload["fact_packets"]
    print(f"[L5] Input fact packets: {len(fact_packets)}")

    out_dir = OUTPUT_DIR / run_id / "L5"
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_calls_path = out_dir / "llm_calls.jsonl"
    llm_calls_path.write_text("", encoding="utf-8")

    candidates = build_candidates(fact_packets, layer5_cfg)
    print(f"[L5] Editorial candidates: {len(candidates)}")

    viewer_prompt = load_prompt_bundle("viewer_value_analyzer", layer5_cfg["viewer_value_prompt_version"])
    candidates = add_viewer_values(
        candidates,
        layer5_cfg=layer5_cfg,
        system_prompt=viewer_prompt["system"],
        log_path=llm_calls_path,
    )

    evaluations = evaluate_candidates(candidates, layer5_cfg)
    decision_result = choose_roundup(evaluations, layer5_cfg)
    selected_story_ids = set(decision_result["selected_story_ids"])
    evaluations = mark_selected(
        evaluations,
        selected_story_ids,
        selected_evaluations=decision_result["selected_evaluations"],
    )
    decision_result["selected_evaluations"] = [
        evaluation for evaluation in evaluations if evaluation["story_id"] in selected_story_ids
    ]

    brief_prompt = load_prompt_bundle("editorial_brief_builder", layer5_cfg["editorial_brief_prompt_version"])
    selected_video = build_selected_video(
        decision_result,
        layer5_cfg=layer5_cfg,
        system_prompt=brief_prompt["system"],
        log_path=llm_calls_path,
    )

    selected_packets = [evaluation["fact_packet"] for evaluation in decision_result["selected_evaluations"]]
    payload = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "decision": _serialize_decision(decision_result),
        "selected_video": selected_video,
        "selected_stories": selected_packets,
        "candidate_evaluations": [compact_candidate_evaluation(evaluation) for evaluation in evaluations],
        "evidence_boundaries": _build_evidence_boundaries(selected_packets, evaluations, selected_video),
    }
    summary = _build_summary(run_id, payload, evaluations, llm_calls_path)

    data_path = out_dir / "selected_video_brief.json"
    summary_path = out_dir / "summary.json"
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"[L5] Decision: {payload['decision']['action']} "
        f"format={payload['decision']['selected_format']} "
        f"stories={payload['decision']['selected_story_count']}"
    )
    print(f"[L5] Wrote: {data_path}")
    return data_path


def _serialize_decision(decision_result: dict) -> dict:
    return {
        "action": decision_result["action"],
        "selected_format": decision_result["selected_format"],
        "confidence": decision_result["confidence"],
        "decision_reason": decision_result["decision_reason"],
        "target_duration_seconds": decision_result["target_duration_seconds"],
        "selected_story_count": len(decision_result["selected_story_ids"]),
        "selected_story_ids": decision_result["selected_story_ids"],
    }


def _resolve_target_format(layer5_cfg: dict) -> str:
    target_format = layer5_cfg.get("target_format")
    if not isinstance(target_format, str) or not target_format.strip():
        raise KeyError(
            "run_manifest.json is missing layer_5.target_format. "
            "Re-run layer 0 after updating L5 config."
        )
    target_format = target_format.strip()
    if target_format != "roundup":
        raise NotImplementedError(
            f"Layer 5 target_format '{target_format}' is not implemented yet. "
            "Only 'roundup' is active in the current rebuild."
        )
    return target_format


def _build_evidence_boundaries(selected_packets: list[dict], evaluations: list[dict], selected_video: dict) -> dict:
    safe_fact_ids: list[str] = []
    cautious_fact_ids: list[str] = []
    caution_notes: list[dict] = []
    blocked_angles: list[str] = list(selected_video.get("blocked_angles", []))

    selected_ids = {packet["story_id"] for packet in selected_packets}
    evaluation_by_id = {evaluation["story_id"]: evaluation for evaluation in evaluations}

    for packet in selected_packets:
        safe_fact_ids.extend(fact["fact_id"] for fact in packet.get("safe_facts", []))
        cautious_fact_ids.extend(fact["fact_id"] for fact in packet.get("cautious_facts", []))
        if packet.get("readiness") != "ready" or packet.get("cautious_facts"):
            caution_notes.append(
                {
                    "story_id": packet["story_id"],
                    "story_title": packet["story_title"],
                    "readiness": packet.get("readiness", ""),
                    "cautious_fact_count": len(packet.get("cautious_facts", [])),
                    "note": "Use cautious facts with explicit caveats; do not present them as fully confirmed.",
                }
            )

    for story_id in selected_ids:
        viewer_value = evaluation_by_id[story_id].get("viewer_value", {})
        blocked_angles.extend(viewer_value.get("blocked_angles", []))

    return {
        "safe_fact_ids": safe_fact_ids,
        "cautious_fact_ids": cautious_fact_ids,
        "caution_notes": caution_notes,
        "blocked_claims": [
            "Do not introduce claims that are not present in selected safe_facts or cautious_facts.",
            "Do not treat cautious facts as confirmed without caveat language.",
            "Do not infer product adoption, market impact, or causality beyond the selected evidence.",
        ],
        "blocked_angles": _dedupe_strings(blocked_angles),
    }


def _build_summary(run_id: str, payload: dict, evaluations: list[dict], llm_calls_path: Path) -> dict:
    readiness_mix = Counter(evaluation.get("readiness", "unknown") for evaluation in evaluations)
    role_mix = Counter(
        evaluation.get("segment_role", "unselected")
        for evaluation in evaluations
        if evaluation.get("selected")
    )
    source_relationship_mix = Counter()
    audience_fit_mix = Counter(
        (evaluation.get("viewer_value") or {}).get("audience_fit", "unknown")
        for evaluation in evaluations
    )
    roundup_fit_mix = Counter(
        (evaluation.get("viewer_value") or {}).get("roundup_segment_fit", "unknown")
        for evaluation in evaluations
    )
    selected_audience_fit_mix = Counter()
    selected_roundup_fit_mix = Counter()
    for evaluation in evaluations:
        if not evaluation.get("selected"):
            continue
        source_relationship_mix.update(evaluation.get("source_relationship_counts", {}))
        viewer_value = evaluation.get("viewer_value") or {}
        selected_audience_fit_mix.update([viewer_value.get("audience_fit", "unknown")])
        selected_roundup_fit_mix.update([viewer_value.get("roundup_segment_fit", "unknown")])
    selected_count = payload["decision"]["selected_story_count"]
    return {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "status": "ok",
        "candidates_evaluated": len(evaluations),
        "selected_format": payload["decision"]["selected_format"],
        "decision_action": payload["decision"]["action"],
        "selected_story_count": selected_count,
        "rejected_count": len(evaluations) - selected_count,
        "readiness_mix": dict(readiness_mix),
        "selected_role_mix": dict(role_mix),
        "selected_source_relationship_mix": dict(source_relationship_mix),
        "audience_fit_mix": dict(audience_fit_mix),
        "roundup_segment_fit_mix": dict(roundup_fit_mix),
        "selected_audience_fit_mix": dict(selected_audience_fit_mix),
        "selected_roundup_segment_fit_mix": dict(selected_roundup_fit_mix),
        "llm_call_count": _count_jsonl_lines(llm_calls_path),
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    kept = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        kept.append(cleaned)
    return kept


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _load_manifest(run_ref: str) -> dict:
    if run_ref == "current":
        path = CURRENT_MANIFEST_PATH
    else:
        path = OUTPUT_DIR / run_ref / "run_manifest.json"

    if not path.exists():
        raise FileNotFoundError(f"run_manifest.json not found for {run_ref}")
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


def _load_l4_fact_packets(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L4" / "fact_packets.json"
    if not path.exists():
        raise FileNotFoundError(
            f"L4/fact_packets.json not found for {run_id}. Run L4 first:\n"
            f"  python -m src.pipeline.runner 4 --run-id {run_id}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("fact_packets"), list):
        raise ValueError(f"L4/fact_packets.json has no valid fact_packets list: {path}")
    return payload


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    path = run(args.run_id)
    print(path)
