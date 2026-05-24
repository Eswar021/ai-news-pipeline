"""
L4 Fact Packet — build grounded fact packets from ranked L3 stories.

Reads:
    output/{run_id}/run_manifest.json
    output/{run_id}/L3/stories.json

Writes:
    output/{run_id}/L4/fact_packets.json
    output/{run_id}/L4/summary.json
    output/{run_id}/L4/llm_calls.jsonl

LLM: yes
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.llm.client import OpenAIJSONClient
from src.llm.prompt_loader import load_prompt_bundle
from src.pipeline.L4_fact_packet.extractor import extract_story_facts
from src.pipeline.L4_fact_packet.fact_filter import filter_story_facts
from src.pipeline.L4_fact_packet.packet_builder import build_fact_packet
from src.pipeline.L4_fact_packet.provenance import resolve_story_provenance
from src.pipeline.L4_fact_packet.selector import select_story_inputs
from src.pipeline.L4_fact_packet.verifier import verify_story_facts


IST = timezone(timedelta(hours=5, minutes=30))


def run(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    layer4_cfg = manifest.get("layer_4")
    if not isinstance(layer4_cfg, dict):
        raise KeyError("run_manifest.json is missing layer_4 config. Re-run layer 0.")

    run_id = manifest["run_id"]
    print(f"[L4] Run: {run_id}")
    stories_payload = _load_l3_stories(run_id)
    print(f"[L4] Input stories: {stories_payload['story_count']}")

    story_inputs = select_story_inputs(stories_payload["stories"], layer4_cfg)
    print(f"[L4] Selected stories: {len(story_inputs)}")

    out_dir = OUTPUT_DIR / run_id / "L4"
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_calls_path = out_dir / "llm_calls.jsonl"
    if llm_calls_path.exists():
        llm_calls_path.unlink()

    prompt_bundle = load_prompt_bundle("claim_extractor", layer4_cfg["claim_extractor_prompt_version"])
    worker_count = int(layer4_cfg["fact_packet_worker_count"])
    if worker_count < 1:
        raise ValueError("layer_4.fact_packet_worker_count must be at least 1")
    print(f"[L4] Fact packet workers: {worker_count}")

    fact_packets = _build_fact_packets_parallel(
        story_inputs=story_inputs,
        layer4_cfg=layer4_cfg,
        system_prompt=prompt_bundle["system"],
        llm_calls_path=llm_calls_path,
        worker_count=worker_count,
    )
    fact_packets = _deduplicate_cross_story_facts(fact_packets)
    totals = _summarize_packets(fact_packets)

    payload = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "story_count": len(fact_packets),
        "fact_packets": fact_packets,
    }
    summary = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "status": "ok",
        "fact_packet_worker_count": worker_count,
        "stories_processed": len(fact_packets),
        "selected_supporting_records": totals["selected_supporting_records"],
        "extracted_facts": totals["extracted_facts"],
        "safe_facts": totals["safe_facts"],
        "cautious_facts": totals["cautious_facts"],
        "discarded_facts": totals["discarded_facts"],
        "filter_discard_counts": totals["filter_discard_counts"],
        "readiness_counts": totals["readiness_counts"],
    }

    data_path = out_dir / "fact_packets.json"
    summary_path = out_dir / "summary.json"
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"[L4] Fact packets: {len(fact_packets)}  "
        f"safe={totals['safe_facts']}  "
        f"cautious={totals['cautious_facts']}  "
        f"discarded={totals['discarded_facts']}"
    )
    print(f"[L4] Wrote: {data_path}")
    return data_path


def _build_fact_packets_parallel(
    *,
    story_inputs: list[dict],
    layer4_cfg: dict,
    system_prompt: str,
    llm_calls_path: Path,
    worker_count: int,
) -> list[dict]:
    if worker_count == 1:
        packets = []
        for story in story_inputs:
            packets.append(
                _process_story(
                    story=story,
                    layer4_cfg=layer4_cfg,
                    system_prompt=system_prompt,
                    llm_calls_path=llm_calls_path,
                )
            )
        return packets

    ordered: list[dict | None] = [None] * len(story_inputs)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _process_story,
                story=story,
                layer4_cfg=layer4_cfg,
                system_prompt=system_prompt,
                llm_calls_path=llm_calls_path,
            ): index
            for index, story in enumerate(story_inputs)
        }
        completed = 0
        for future in as_completed(future_to_index):
            packet = future.result()
            ordered[future_to_index[future]] = packet
            completed += 1
            print(
                f"[L4] Story {completed:>2}/{len(story_inputs)} done — "
                f"rank={packet['rank']} safe={packet['evidence_summary']['safe_fact_count']} "
                f"cautious={packet['evidence_summary']['cautious_fact_count']} "
                f"discarded={packet['evidence_summary']['discarded_fact_count']} "
                f"readiness={packet['readiness']}"
            )

    if any(packet is None for packet in ordered):
        raise RuntimeError("L4 fact packet processing finished with missing story outputs")
    return [packet for packet in ordered if packet is not None]


def _process_story(
    *,
    story: dict,
    layer4_cfg: dict,
    system_prompt: str,
    llm_calls_path: Path,
) -> dict:
    _ensure_record_keys(story)
    print(
        f"[L4] Story {story['rank']:>2} — {story['story_title'][:80]}  "
        f"records={len(story['selected_supporting_records'])}"
    )
    llm_client = OpenAIJSONClient(model=layer4_cfg["claim_extractor_model"])
    story_extraction = extract_story_facts(
        story,
        layer4_cfg=layer4_cfg,
        llm_client=llm_client,
        system_prompt=system_prompt,
        log_path=llm_calls_path,
    )
    story_with_provenance = resolve_story_provenance(story_extraction)
    story_filtered = filter_story_facts(story_with_provenance)
    story_verified = verify_story_facts(story_filtered)
    return build_fact_packet(
        story_verified,
        max_facts_per_story=int(layer4_cfg["max_facts_per_story"]),
    )


def _summarize_packets(fact_packets: list[dict]) -> dict:
    readiness_counts = {"ready": 0, "caution": 0, "insufficient": 0}
    totals = {
        "selected_supporting_records": 0,
        "extracted_facts": 0,
        "safe_facts": 0,
        "cautious_facts": 0,
        "discarded_facts": 0,
        "filter_discard_counts": {},
        "readiness_counts": readiness_counts,
    }
    for packet in fact_packets:
        totals["selected_supporting_records"] += packet["evidence_summary"]["selected_record_count"]
        totals["extracted_facts"] += packet["evidence_summary"]["extracted_fact_count"]
        totals["safe_facts"] += packet["evidence_summary"]["safe_fact_count"]
        totals["cautious_facts"] += packet["evidence_summary"]["cautious_fact_count"]
        totals["discarded_facts"] += packet["evidence_summary"]["discarded_fact_count"]
        for reason, count in packet["evidence_summary"].get("filter_discard_counts", {}).items():
            totals["filter_discard_counts"][reason] = totals["filter_discard_counts"].get(reason, 0) + count
        readiness = packet["readiness"]
        readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1
    return totals


def _deduplicate_cross_story_facts(fact_packets: list[dict]) -> list[dict]:
    seen: list[tuple[str, frozenset[str], str]] = []
    deduped_packets: list[dict] = []

    for packet in fact_packets:
        next_packet = dict(packet)
        discarded = list(next_packet["discarded_facts"])
        filter_counts = dict(next_packet["evidence_summary"].get("filter_discard_counts", {}))

        for bucket_name in ("safe_facts", "cautious_facts"):
            kept_bucket = []
            for fact in next_packet[bucket_name]:
                fact_type = fact.get("fact_type", "")
                tokens = _fact_tokens(fact.get("fact_text", ""))
                normalized = _normalized_fact_text(fact.get("fact_text", ""))
                if _seen_fact(normalized, tokens, fact_type, seen):
                    duplicate = dict(fact)
                    duplicate["status"] = "discarded"
                    duplicate["confidence"] = "none"
                    duplicate["discard_reason"] = "duplicate_fact_across_stories"
                    discarded.append(duplicate)
                    filter_counts["duplicate_fact_across_stories"] = (
                        filter_counts.get("duplicate_fact_across_stories", 0) + 1
                    )
                    continue

                kept_bucket.append(fact)
                seen.append((normalized, tokens, fact_type))
            next_packet[bucket_name] = kept_bucket

        next_packet["discarded_facts"] = discarded
        next_packet["evidence_summary"] = {
            **next_packet["evidence_summary"],
            "safe_fact_count": len(next_packet["safe_facts"]),
            "cautious_fact_count": len(next_packet["cautious_facts"]),
            "discarded_fact_count": len(next_packet["discarded_facts"]),
            "filter_discard_counts": filter_counts,
        }
        next_packet["readiness"] = _packet_readiness(next_packet)
        deduped_packets.append(next_packet)

    return deduped_packets


def _seen_fact(
    normalized: str,
    tokens: frozenset[str],
    fact_type: str,
    seen: list[tuple[str, frozenset[str], str]],
) -> bool:
    for seen_normalized, seen_tokens, seen_type in seen:
        if fact_type != seen_type:
            continue
        if normalized == seen_normalized:
            return True
        if _jaccard(tokens, seen_tokens) >= 0.86:
            return True
    return False


def _packet_readiness(packet: dict) -> str:
    safe_count = len(packet["safe_facts"])
    cautious_count = len(packet["cautious_facts"])
    official_count = packet["evidence_summary"].get("official_record_count", 0)
    if safe_count >= 3:
        return "ready"
    if safe_count >= 2 and official_count >= 1:
        return "ready"
    if safe_count + cautious_count >= 3:
        return "caution"
    return "insufficient"


def _normalized_fact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip(" .")


def _fact_tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _ensure_record_keys(story: dict) -> None:
    missing = [record.get("title", "") for record in story["selected_supporting_records"] if not record.get("record_key")]
    if missing:
        raise ValueError(
            "L4 requires stable record_key on supporting records. Re-run layers 2 and 3 with the updated rebuild code."
        )


def _load_l3_stories(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L3" / "stories.json"
    if not path.exists():
        raise FileNotFoundError(f"L3 stories.json not found for {run_id}. Run layer 3 first.")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_manifest(run_ref: str) -> dict:
    if run_ref == "current":
        path = CURRENT_MANIFEST_PATH
    else:
        path = OUTPUT_DIR / run_ref / "run_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"run_manifest.json not found for {run_ref}. Run L0 first.")
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    path = run(args.run_id)
    print(path)
