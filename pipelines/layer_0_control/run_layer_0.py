"""
Module: run_layer_0
Layer: 0 — Channel Strategy + Run Control
Purpose: Entry point. Orchestrates all Layer 0 modules in sequence and produces run_manifest.json.
         Usage: python -m pipelines.layer_0_control.run_layer_0 [--format auto] [--lookback-hours 48]
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on the path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml

from config.paths import (
    CHANNEL_THESIS_YAML,
    AUDIENCE_PROFILES_YAML,
    CHANNELS_YAML,
    CHATGPT_PROMPTS_YAML,
    ENTITY_TOPIC_TAXONOMY_YAML,
    FORMAT_CONFIG_YAML,
    QUALITY_RULES_YAML,
    SOURCES_YAML,
    DATA_DIR,
    MEMORY_DIR,
    SCRIPTS_OUTPUT,
    RUNS_DIR,
    RUN_DEFAULTS_YAML,
    SOURCE_STRATEGY_YAML,
)

from pipelines.layer_0_control.run_request_parser import parse_run_request
from pipelines.layer_0_control.channel_thesis_loader import load_channel_thesis
from pipelines.layer_0_control.audience_profile_resolver import resolve_audience_profile
from pipelines.layer_0_control.run_mode_resolver import resolve_run_mode
from pipelines.layer_0_control.time_window_resolver import resolve_time_window
from pipelines.layer_0_control.format_strategy_resolver import resolve_format_strategy
from pipelines.layer_0_control.source_scope_planner import plan_source_scope
from pipelines.layer_0_control.quality_policy_loader import load_quality_policy
from pipelines.layer_0_control.memory_context_planner import plan_memory_context
from pipelines.layer_0_control.budget_depth_controller import build_depth_limits
from pipelines.layer_0_control.output_contract_builder import build_output_contract
from pipelines.layer_0_control.resolved_config_snapshot_builder import build_resolved_config_snapshots
from pipelines.layer_0_control.run_manifest_builder import build_run_manifest
from pipelines.layer_0_control.run_validation_gate import validate_manifest


def run_layer_0(
    trigger_type: str = "manual",
    target_format: str = "auto",
    lookback_hours: int = None,
    topic_focus: str = "AI news",
    depth: str = "standard",
    max_videos: int = 1,
    requested_at: str = None,
) -> dict:
    """
    Runs the full Layer 0 pipeline and returns the run result.

    Returns:
        dict with: run_id, manifest_path, status, validation_report
    """
    # Load run defaults for normalization fallbacks
    defaults = {}
    if RUN_DEFAULTS_YAML.exists():
        with open(RUN_DEFAULTS_YAML) as f:
            raw = yaml.safe_load(f)
            defaults = raw.get("defaults", {})

    # Step 1 — Normalize the run request
    run_request = parse_run_request(
        trigger_type=trigger_type,
        requested_at=requested_at,
        target_format=target_format,
        lookback_hours=lookback_hours,
        topic_focus=topic_focus,
        depth=depth,
        max_videos=max_videos,
        defaults=defaults,
    )

    run_id = run_request["run_id"]
    print(f"[Layer 0] Run ID: {run_id}")

    # Step 2 — Load channel identity + editorial rules
    channel_strategy = load_channel_thesis(CHANNEL_THESIS_YAML)

    # Step 3 — Resolve audience profile (default from channel thesis)
    audience_strategy = resolve_audience_profile(
        profiles_path=AUDIENCE_PROFILES_YAML,
        default_audience_id=channel_strategy["primary_audience_id"],
    )

    # Step 4 — Determine run mode and eligible formats
    run_mode = resolve_run_mode(
        target_format=run_request["target_format"],
        format_config_path=FORMAT_CONFIG_YAML,
        max_videos=max_videos,
    )

    # Step 5 — Resolve collection + memory time windows
    time_window = resolve_time_window(
        requested_at=run_request["requested_at"],
        lookback_hours=run_request["lookback_hours"],
        target_format=run_request["target_format"],
    )

    # Step 6 — Load format requirements for all eligible formats
    format_strategy = resolve_format_strategy(
        format_config_path=FORMAT_CONFIG_YAML,
        eligible_formats=run_mode["eligible_formats"],
    )

    # Step 7 — Build source collection plan for Layer 1
    source_scope = plan_source_scope(
        sources_path=SOURCES_YAML,
        source_strategy_path=SOURCE_STRATEGY_YAML,
        topic_focus=run_request["topic_focus"],
        target_format=run_request["target_format"],
    )

    # Step 8 — Load quality + hallucination control rules
    quality_policy = load_quality_policy(
        quality_rules_path=QUALITY_RULES_YAML,
        eligible_formats=run_mode["eligible_formats"],
    )

    # Step 9 — Plan memory usage (what to load at which pipeline stages)
    memory_context = plan_memory_context(
        run_mode=run_mode["run_mode"],
        memory_windows=time_window["memory_windows"],
        memory_dir=MEMORY_DIR,
    )

    # Step 10 — Set processing depth limits for all downstream layers
    depth_limits = build_depth_limits(
        target_format=run_request["target_format"],
        depth=run_request["depth"],
        max_videos=max_videos,
        run_defaults_path=RUN_DEFAULTS_YAML,
    )

    # Step 11 — Declare all expected output paths
    output_contract = build_output_contract(
        run_id=run_id,
        eligible_formats=run_mode["eligible_formats"],
        data_dir=DATA_DIR,
        scripts_dir=SCRIPTS_OUTPUT,
    )

    # Step 11A — Snapshot resolved runtime config for downstream layers
    resolved_config = build_resolved_config_snapshots(
        sources_path=SOURCES_YAML,
        source_strategy_path=SOURCE_STRATEGY_YAML,
        channels_path=CHANNELS_YAML,
        run_defaults_path=RUN_DEFAULTS_YAML,
        entity_topic_taxonomy_path=ENTITY_TOPIC_TAXONOMY_YAML,
        chatgpt_prompts_path=CHATGPT_PROMPTS_YAML,
        enabled_source_groups=source_scope["source_collection_plan"]["enabled_source_groups"],
        source_group_details=source_scope["source_group_details"],
    )

    # Step 12 — Assemble and write run_manifest.json
    manifest, manifest_path = build_run_manifest(
        run_request=run_request,
        channel_strategy=channel_strategy,
        audience_strategy=audience_strategy,
        run_mode=run_mode,
        time_window=time_window,
        format_strategy=format_strategy,
        source_scope=source_scope,
        quality_policy=quality_policy,
        memory_context=memory_context,
        depth_limits=depth_limits,
        output_contract=output_contract,
        resolved_config=resolved_config,
        runs_dir=RUNS_DIR,
    )

    # Step 13 — Validate manifest (pass/fail gate before Layer 1)
    validation_report = validate_manifest(manifest, manifest_path)

    return {
        "run_id": run_id,
        "manifest_path": str(manifest_path),
        "status": manifest.get("status"),
        "validation_report": validation_report,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Layer 0 — Channel Strategy + Run Control",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--format",
        dest="target_format",
        default="auto",
        choices=["auto", "roundup", "deep_dive", "evergreen", "comparison", "follow_up"],
        help="Target video format (auto = Layer 5 decides after story ranking)",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=None,
        help="How many hours back to collect news (default: 48 from run_defaults.yaml)",
    )
    parser.add_argument(
        "--topic",
        default="AI news",
        help="Topic focus for query themes",
    )
    parser.add_argument(
        "--depth",
        default="standard",
        choices=["light", "standard", "deep"],
        help="Processing depth profile",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=1,
        help="Maximum number of videos to produce in this run",
    )
    parser.add_argument(
        "--trigger",
        default="manual",
        choices=["manual", "scheduled", "api"],
        help="What triggered this run",
    )
    args = parser.parse_args()

    result = run_layer_0(
        trigger_type=args.trigger,
        target_format=args.target_format,
        lookback_hours=args.lookback_hours,
        topic_focus=args.topic,
        depth=args.depth,
        max_videos=args.max_videos,
    )

    vr = result["validation_report"]
    if vr["can_start_layer_1"]:
        print(f"[Layer 0] SUCCESS  status={result['status']}")
        print(f"[Layer 0] Manifest: {result['manifest_path']}")
        if vr["warnings"]:
            print(f"[Layer 0] {len(vr['warnings'])} warning(s) — see validation report.")
    else:
        print(f"[Layer 0] FAILED")
        for err in vr["errors"]:
            print(f"  ERROR: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
