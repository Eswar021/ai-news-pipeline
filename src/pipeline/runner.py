"""
Pipeline runner — execute the rebuild layers that currently exist.

Reads:
    CLI arguments                            → requested layers / run profile / run id

Writes:
    output/{run_id}/run_manifest.json       → when L0 runs
    output/{run_id}/L1/raw_records.json     → when L1 runs
    output/{run_id}/L1/summary.json         → when L1 runs
    output/{run_id}/L2/prepared_records.json → when L2 runs
    output/{run_id}/L2/summary.json          → when L2 runs
    output/{run_id}/L3/stories.json          → when L3 runs
    output/{run_id}/L3/summary.json          → when L3 runs
    output/{run_id}/L3/llm_calls.jsonl       → when L3 fingerprinting is enabled
    output/{run_id}/L4/fact_packets.json     → when L4 runs
    output/{run_id}/L4/summary.json          → when L4 runs
    output/{run_id}/L4/llm_calls.jsonl       → when L4 runs
    output/{run_id}/L5/selected_video_brief.json → when L5 runs
    output/{run_id}/L5/summary.json          → when L5 runs
    output/{run_id}/L5/llm_calls.jsonl       → when L5 runs
    output/{run_id}/L6/content_packet.json   → when L6 runs
    output/{run_id}/L6/summary.json          → when L6 runs
    output/{run_id}/L7/script_package.json   → when L7 runs
    output/{run_id}/L7/summary.json          → when L7 runs
    output/{run_id}/L7/llm_calls.jsonl       → when L7 runs
    output/{run_id}/L8/verification_package.json → when L8 runs
    output/{run_id}/L8/summary.json          → when L8 runs
    output/{run_id}/L8/llm_calls.jsonl       → when L8 runs
    output/{run_id}/L9/memory_update.json    → when L9 runs
    output/{run_id}/L9/summary.json          → when L9 runs
    output/memory/rebuild_memory.json        → when L9 runs

LLM: yes for L3 story fingerprinting, L4 fact extraction, L5 editorial judgment, L7 script writing, and L8 support verification

Module execution order:
    1. parse requested layers
    2. run L0 if requested
    3. run L1 if requested
    4. run L2 if requested
    5. run L3 if requested
    6. run L4 if requested
    7. run L5 if requested
    8. run L6 if requested
    9. run L7 if requested
    10. run L8 if requested
    11. run L9 if requested

Usage:
    python -m src.pipeline.runner 0 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 3 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 3 4 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 3 4 5 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 3 4 5 6 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 3 4 5 6 7 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 3 4 5 6 7 8 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 3 4 5 6 7 8 9 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 3 4 5 6 7 --run-profile broad_7d_all_sources --script-style general_youtube
    python -m src.pipeline.runner 1
    python -m src.pipeline.runner 2
    python -m src.pipeline.runner 3
    python -m src.pipeline.runner 4
    python -m src.pipeline.runner 5
    python -m src.pipeline.runner 6
    python -m src.pipeline.runner 7
    python -m src.pipeline.runner 8
    python -m src.pipeline.runner 9
    python -m src.pipeline.runner 1 --run-id run_...
    python -m src.pipeline.runner 1 --run-id current
"""

import argparse
import json
import time

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.pipeline.L0_manifest.runner import run as run_l0
from src.pipeline.L1_collection.runner import run as run_l1
from src.pipeline.L2_evidence_prep.runner import run as run_l2
from src.pipeline.L3_story_map.runner import run as run_l3
from src.pipeline.L4_fact_packet.runner import run as run_l4
from src.pipeline.L5_editorial.runner import run as run_l5
from src.pipeline.L6_package.runner import run as run_l6
from src.pipeline.L7_script.runner import run as run_l7
from src.pipeline.L8_verify.runner import run as run_l8
from src.pipeline.L9_memory.runner import run as run_l9


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("layers", nargs="+", help="0, 1, or all")
    parser.add_argument("--run-profile", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--date", default=None)
    parser.add_argument("--trigger", default="manual")
    parser.add_argument(
        "--script-style",
        default=None,
        help="Optional L7 script style override, resolved by L0 into run_manifest.json.",
    )
    args = parser.parse_args()

    requested = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] if args.layers == ["all"] else sorted({int(v) for v in args.layers})
    run_id = args.run_id
    started = time.time()

    if 0 not in requested and not run_id:
        run_id = "current"

    if 0 in requested:
        layer_started = time.time()
        print("[runner] Layer 0")
        if not args.run_profile:
            raise ValueError(
                "Layer 0 creates a new run, so --run-profile is required.\n"
                "Start a new run with:\n"
                "  python -m src.pipeline.runner 0 1 2 --run-profile daily_48h_all_sources\n"
                "Continue the current run without L0 with:\n"
                "  python -m src.pipeline.runner 1 2"
            )
        manifest_path = run_l0(
            run_profile=args.run_profile,
            run_date=args.date,
            trigger_type=args.trigger,
            script_style=args.script_style,
        )
        run_id = manifest_path.parent.name
        print(f"[runner] Layer 0 done in {time.time() - layer_started:.1f}s")

    if 1 in requested:
        layer_started = time.time()
        print("[runner] Layer 1")
        run_l1(run_id=run_id)
        print(f"[runner] Layer 1 done in {time.time() - layer_started:.1f}s")

    if 2 in requested:
        layer_started = time.time()
        print("[runner] Layer 2")
        run_l2(run_ref=run_id)
        print(f"[runner] Layer 2 done in {time.time() - layer_started:.1f}s")

    if 3 in requested:
        layer_started = time.time()
        print("[runner] Layer 3")
        run_l3(run_ref=run_id)
        print(f"[runner] Layer 3 done in {time.time() - layer_started:.1f}s")

    if 4 in requested:
        layer_started = time.time()
        print("[runner] Layer 4")
        run_l4(run_ref=run_id)
        print(f"[runner] Layer 4 done in {time.time() - layer_started:.1f}s")

    if 5 in requested:
        layer_started = time.time()
        print("[runner] Layer 5")
        run_l5(run_ref=run_id)
        print(f"[runner] Layer 5 done in {time.time() - layer_started:.1f}s")

    if 6 in requested:
        layer_started = time.time()
        print("[runner] Layer 6")
        run_l6(run_ref=run_id)
        print(f"[runner] Layer 6 done in {time.time() - layer_started:.1f}s")

    if 7 in requested:
        layer_started = time.time()
        print("[runner] Layer 7")
        run_l7(run_ref=run_id)
        print(f"[runner] Layer 7 done in {time.time() - layer_started:.1f}s")

    if 8 in requested:
        layer_started = time.time()
        print("[runner] Layer 8")
        run_l8(run_ref=run_id)
        print(f"[runner] Layer 8 done in {time.time() - layer_started:.1f}s")

    if 9 in requested:
        layer_started = time.time()
        print("[runner] Layer 9")
        if 8 in requested and not _l8_ready_for_l9(run_id):
            print("[runner] Layer 9 skipped: Layer 8 did not approve this run.")
        else:
            run_l9(run_ref=run_id)
            print(f"[runner] Layer 9 done in {time.time() - layer_started:.1f}s")

    print(f"[runner] Complete in {time.time() - started:.1f}s")


def _l8_ready_for_l9(run_ref: str) -> bool:
    run_id = _resolve_run_id(run_ref)
    summary_path = OUTPUT_DIR / run_id / "L8" / "summary.json"
    if not summary_path.exists():
        return False
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return summary.get("status") == "approved" and summary.get("ready_for_layer_9") is True


def _resolve_run_id(run_ref: str) -> str:
    if run_ref != "current":
        return run_ref
    if not CURRENT_MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Current manifest not found: {CURRENT_MANIFEST_PATH}")
    manifest = json.loads(CURRENT_MANIFEST_PATH.read_text(encoding="utf-8"))
    run_id = manifest.get("run_id")
    if not run_id:
        raise KeyError("output/current_manifest.json is missing run_id")
    return run_id


if __name__ == "__main__":
    main()
