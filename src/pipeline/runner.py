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

LLM: no

Module execution order:
    1. parse requested layers
    2. run L0 if requested
    3. run L1 if requested
    4. run L2 if requested

Usage:
    python -m src.pipeline.runner 0 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 2 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 1
    python -m src.pipeline.runner 2
    python -m src.pipeline.runner 1 --run-id run_...
    python -m src.pipeline.runner 1 --run-id current
"""

import argparse
import time

from src.pipeline.L0_manifest.runner import run as run_l0
from src.pipeline.L1_collection.runner import run as run_l1
from src.pipeline.L2_evidence_prep.runner import run as run_l2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("layers", nargs="+", help="0, 1, or all")
    parser.add_argument("--run-profile", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--date", default=None)
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args()

    requested = [0, 1, 2] if args.layers == ["all"] else sorted({int(v) for v in args.layers})
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

    print(f"[runner] Complete in {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
