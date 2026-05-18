"""
Pipeline runner — execute the rebuild layers that currently exist.

Reads:
    CLI arguments                            → requested layers / run profile / run id

Writes:
    output/{run_id}/run_manifest.json       → when L0 runs
    output/{run_id}/L1/raw_records.json     → when L1 runs
    output/{run_id}/L1/summary.json         → when L1 runs

LLM: no

Module execution order:
    1. parse requested layers
    2. run L0 if requested
    3. run L1 if requested

Usage:
    python -m src.pipeline.runner 0 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 0 1 --run-profile daily_48h_all_sources
    python -m src.pipeline.runner 1 --run-id run_...
    python -m src.pipeline.runner 1 --run-id current
"""

import argparse

from src.pipeline.L0_manifest.runner import run as run_l0
from src.pipeline.L1_collection.runner import run as run_l1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("layers", nargs="+", help="0, 1, or all")
    parser.add_argument("--run-profile", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--date", default=None)
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args()

    requested = [0, 1] if args.layers == ["all"] else sorted({int(v) for v in args.layers})
    run_id = args.run_id

    if 0 in requested:
        if not args.run_profile:
            raise ValueError("--run-profile is required when running layer 0")
        manifest_path = run_l0(
            run_profile=args.run_profile,
            run_date=args.date,
            trigger_type=args.trigger,
        )
        run_id = manifest_path.parent.name

    if 1 in requested:
        if not run_id:
            raise ValueError("--run-id is required when running layer 1 directly")
        run_l1(run_id=run_id)


if __name__ == "__main__":
    main()
