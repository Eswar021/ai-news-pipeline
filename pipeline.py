"""
AI Content Creation — Pipeline Runner

Runs any combination of layers, in order, using config/policies/pipeline_config.yaml.

Usage:
    python pipeline.py                              # default preset = collection_only (L0-L3)
    python pipeline.py --preset with_facts          # L0-L4 (best ChatGPT handoff point)
    python pipeline.py --preset with_editorial      # L0-L6
    python pipeline.py --preset full_auto           # L0-L10

    python pipeline.py --layers 0,1,2,3,4           # explicit layer list
    python pipeline.py --run-id <id> --layers 5,6   # continue an existing run from a midpoint

Layer 0 CLI overrides:
    --trigger-type    manual | scheduled | api
    --target-format   auto | roundup | deep_dive | evergreen | comparison | follow_up
    --lookback-hours  integer (overrides run_defaults.yaml)
    --topic-focus     "AI news" | "AI safety" | etc.
    --depth           standard | deep
    --max-videos      integer

LLM usage:
    Pipeline-level API call estimates are intentionally not hardcoded.
    Each LLM layer reports its own run-derived workload after inspecting inputs.
"""

import sys
import argparse
import json
import yaml
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config.paths import RUNS_DIR, PIPELINE_CONFIG_YAML, DATA_DIR, MEMORY_DIR, SCRIPTS_OUTPUT
from pipelines.layer_0_control.output_contract_builder import build_output_contract

PIPELINE_CONFIG = PIPELINE_CONFIG_YAML

_LAYER_EXECUTION_LABELS = {
    0: "free",
    1: "free",
    2: "free",
    3: "local embeddings",
    4: "dynamic LLM usage",
    5: "dynamic LLM usage",
    6: "free",
    7: "dynamic LLM usage",
    8: "dynamic LLM usage",
    9: "dynamic LLM usage",
    10: "free",
}

_LAYER_REQUIRED_OUTPUT_KEYS = {
    0: ["layer_0_manifest", "layer_0_validation_report", "layer_0_config_snapshot"],
    1: ["layer_1_raw_documents", "layer_1_extraction_manifest", "layer_1_validation_report"],
    2: ["layer_2_canonical_documents", "layer_2_source_spans", "layer_2_manifest", "layer_2_validation_report"],
    3: ["layer_3_story_clusters", "layer_3_ranked_stories", "layer_3_manifest", "layer_3_validation_report"],
    4: ["layer_4_verified_claims", "layer_4_story_fact_sheets", "layer_4_manifest", "layer_4_validation_report"],
    5: ["layer_5_selected_video_brief", "layer_5_manifest", "layer_5_validation_report"],
    6: ["layer_6_research_packet", "layer_6_source_pack", "layer_6_manifest", "layer_6_validation_report"],
    7: ["layer_7_video_plan", "layer_7_script_writer_brief", "layer_7_manifest", "layer_7_validation_report"],
    8: ["layer_8_script_md", "layer_8_generated_script", "layer_8_manifest", "layer_8_validation_report"],
    9: ["layer_9_verified_script", "layer_9_verification_report", "layer_9_final_publish_package", "layer_9_manifest", "layer_9_validation_report"],
    10: ["layer_10_manifest", "layer_10_validation_report", "layer_10_memory_index", "layer_10_memory_snapshot"],
}

_VALIDATION_REPORT_KEYS = {
    0: "layer_0_validation_report",
    1: "layer_1_validation_report",
    2: "layer_2_validation_report",
    3: "layer_3_validation_report",
    4: "layer_4_validation_report",
    5: "layer_5_validation_report",
    6: "layer_6_validation_report",
    7: "layer_7_validation_report",
    8: "layer_8_validation_report",
    9: "layer_9_validation_report",
    10: "layer_10_validation_report",
}


def load_config() -> dict:
    if not PIPELINE_CONFIG.exists():
        print(f"[pipeline] Config not found: {PIPELINE_CONFIG}")
        sys.exit(1)
    with open(PIPELINE_CONFIG) as f:
        return yaml.safe_load(f)


def resolve_layers(args, cfg: dict) -> list[int]:
    if args.layers:
        try:
            return sorted(int(x.strip()) for x in args.layers.split(","))
        except ValueError:
            print(f"[pipeline] --layers must be comma-separated integers, e.g. 0,1,2,3")
            sys.exit(1)

    preset_name = args.preset or cfg["pipeline"]["default_preset"]
    if preset_name not in cfg["presets"]:
        available = list(cfg["presets"].keys())
        print(f"[pipeline] Unknown preset '{preset_name}'. Available: {available}")
        sys.exit(1)
    return cfg["presets"][preset_name]["layers"]


def _load_run_manifest(run_id: str) -> dict:
    manifest_path = RUNS_DIR / run_id / "run_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"run_manifest.json not found for run '{run_id}' at {manifest_path}")
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def _build_active_output_contract(run_id: str, manifest: dict) -> dict:
    eligible_formats = manifest.get("format_strategy", {}).get("eligible_formats", [])
    return build_output_contract(
        run_id=run_id,
        eligible_formats=eligible_formats,
        data_dir=DATA_DIR,
        scripts_dir=SCRIPTS_OUTPUT,
    )["output_contract"]


def _resolve_output_contract(run_id: str) -> dict:
    manifest = _load_run_manifest(run_id)
    manifest_contract = manifest.get("output_contract", {})
    active_contract = _build_active_output_contract(run_id, manifest)

    manifest_outputs = manifest_contract.get("required_layer_outputs", {})
    active_outputs = active_contract.get("required_layer_outputs", {})

    contract_is_current = all(
        manifest_outputs.get(key) == expected_path
        for key, expected_path in active_outputs.items()
    )

    if not manifest_contract:
        raise KeyError(
            f"run_manifest.json for run '{run_id}' is missing output_contract. "
            "Rebuild the run from Layer 0."
        )

    if not contract_is_current:
        raise RuntimeError(
            f"run_manifest.json for run '{run_id}' has a stale output_contract. "
            "Rebuild the run from Layer 0 so the pipeline uses only manifest-defined output paths."
        )

    return manifest_contract


def _enforce_layer_outputs(layer_num: int, output_contract: dict) -> None:
    required_outputs = output_contract.get("required_layer_outputs", {})
    missing = []

    for key in _LAYER_REQUIRED_OUTPUT_KEYS.get(layer_num, []):
        path_str = required_outputs.get(key)
        if not path_str:
            missing.append(f"{key} (missing from output_contract)")
            continue
        if not Path(path_str).exists():
            missing.append(f"{key} -> {path_str}")

    if missing:
        raise FileNotFoundError(
            f"Layer {layer_num} completed without required outputs:\n  - " +
            "\n  - ".join(missing)
        )


def _enforce_validation_report(layer_num: int, output_contract: dict) -> None:
    report_key = _VALIDATION_REPORT_KEYS.get(layer_num)
    if not report_key:
        return

    report_path = Path(output_contract["required_layer_outputs"][report_key])
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    if layer_num == 0:
        passed = report.get("can_start_layer_1", False)
        status = report.get("validation_status", "unknown")
    else:
        passed = bool(report.get("passed"))
        status = report.get("status", "unknown")

    if passed:
        return

    failure_reason = report.get("failure_reason")
    if not failure_reason:
        errors = report.get("errors")
        if isinstance(errors, list) and errors:
            failure_reason = errors[0]
        elif isinstance(errors, str):
            failure_reason = errors
    if not failure_reason:
        warnings = report.get("warnings")
        if isinstance(warnings, list) and warnings:
            failure_reason = warnings[0]

    raise RuntimeError(
        f"Layer {layer_num} validation did not pass "
        f"(status={status}): {failure_reason or 'see validation report'}"
    )


def _enforce_layer_completion(layer_num: int, output_contract: dict) -> None:
    _enforce_layer_outputs(layer_num, output_contract)
    _enforce_validation_report(layer_num, output_contract)


def run_layer(layer_num: int, run_id: str, args, l0_defaults: dict) -> dict:
    if layer_num == 0:
        from pipelines.layer_0_control.run_layer_0 import run_layer_0
        default_run_profile = (
            l0_defaults.get("run_profile")
            if not args.run_profile and not args.target_format and not args.lookback_hours
            else None
        )
        return run_layer_0(
            trigger_type   = args.trigger_type  or l0_defaults.get("trigger_type", "manual"),
            run_profile    = args.run_profile   or default_run_profile,
            target_format  = args.target_format or l0_defaults.get("target_format"),
            lookback_hours = args.lookback_hours or l0_defaults.get("lookback_hours"),
            topic_focus    = args.topic_focus   or l0_defaults.get("topic_focus", "AI news"),
            depth          = args.depth         or l0_defaults.get("depth"),
            max_videos     = args.max_videos    or l0_defaults.get("max_videos"),
        )

    if layer_num == 1:
        from pipelines.layer_1_extraction.run_layer_1 import run_layer_1
        return run_layer_1(run_id)

    if layer_num == 2:
        from pipelines.layer_2_canonicalization.run_layer_2 import run_layer_2
        return run_layer_2(run_id)

    if layer_num == 3:
        from pipelines.layer_3_story_processing.run_layer_3 import run_layer_3
        return run_layer_3(run_id)

    if layer_num == 4:
        from pipelines.layer_4_evidence_intelligence.run_layer_4 import run_layer_4
        return run_layer_4(run_id)

    if layer_num == 5:
        from pipelines.layer_5_editorial_intelligence.run_layer_5 import run_layer_5
        return run_layer_5(run_id)

    if layer_num == 6:
        from pipelines.layer_6_research_packets.run_layer_6 import run_layer_6
        return run_layer_6(run_id)

    if layer_num == 7:
        from pipelines.layer_7_content_planning.run_layer_7 import run_layer_7
        return run_layer_7(run_id)

    if layer_num == 8:
        from pipelines.layer_8_script_generation.run_layer_8 import run_layer_8
        return run_layer_8(run_id)

    if layer_num == 9:
        from pipelines.layer_9_verification_firewall.run_layer_9 import run_layer_9
        return run_layer_9(run_id)

    if layer_num == 10:
        from pipelines.layer_10_memory_learning.run_layer_10 import run_layer_10
        return run_layer_10(run_id)

    raise ValueError(f"Unknown layer: {layer_num}")


def main():
    parser = argparse.ArgumentParser(
        description="AI Content Creation Pipeline Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--preset", help="Named preset from pipeline_config.yaml")
    parser.add_argument("--layers", help="Comma-separated layer numbers, e.g. 0,1,2,3")
    parser.add_argument("--run-id", dest="run_id", help="Continue an existing run (Layer 0 auto-skipped)")

    # Layer 0 overrides
    parser.add_argument("--trigger-type", dest="trigger_type", default=None)
    parser.add_argument("--run-profile", dest="run_profile", default=None)
    parser.add_argument("--target-format", dest="target_format", default=None)
    parser.add_argument("--lookback-hours", dest="lookback_hours", type=int, default=None)
    parser.add_argument("--topic-focus", dest="topic_focus", default=None)
    parser.add_argument("--depth", default=None)
    parser.add_argument("--max-videos", dest="max_videos", type=int, default=None)
    parser.add_argument(
        "--sync-publishing-channel",
        action="store_true",
        help="Sync authenticated publishing-channel state before running pipeline layers.",
    )

    args = parser.parse_args()

    cfg         = load_config()
    layers      = resolve_layers(args, cfg)
    l0_defaults = cfg.get("layer_0_defaults", {})
    run_id      = args.run_id
    continuing  = run_id is not None
    output_contract = None

    # If continuing an existing run, Layer 0 is not needed
    if continuing and 0 in layers:
        layers = [l for l in layers if l != 0]
        print(f"[pipeline] --run-id provided — Layer 0 skipped.")

    # Fresh run requires Layer 0 to generate the run_id
    if not continuing and 0 not in layers:
        print("[pipeline] Error: Layer 0 is required when starting a fresh run.")
        print("           Either include layer 0 in --layers, or provide --run-id to continue an existing run.")
        sys.exit(1)

    if continuing:
        output_contract = _resolve_output_contract(run_id)

    if args.sync_publishing_channel:
        from pipelines.layer_10_memory_learning.publishing_channel_sync import sync_channel_state
        print("[pipeline] Syncing publishing channel before pipeline run...")
        sync_result = sync_channel_state(
            memory_dir=MEMORY_DIR,
            interactive=True,
            sync_analytics_for_mapped_videos=True,
        )
        print(
            f"[pipeline] Publishing channel synced: "
            f"{sync_result['videos_seen_this_sync']} videos seen, "
            f"{sync_result['analytics_records_synced']} analytics record(s) updated."
        )

    # Print run plan
    preset_label = args.preset or cfg["pipeline"]["default_preset"] if not args.layers else "custom"
    llm_layers = [l for l in layers if l in (4, 5, 7, 8, 9)]

    print(f"\n{'='*60}")
    print(f"Pipeline Runner")
    print(f"  Preset  : {preset_label}")
    print(f"  Layers  : {layers}")
    print(f"  Run ID  : {run_id or '(will be generated by Layer 0)'}")
    if llm_layers:
        print(f"  LLM use : dynamic (reported by layers {llm_layers} after input inspection)")
    else:
        print(f"  LLM use : none")
    print(f"{'='*60}\n")

    started_at = datetime.now(timezone.utc)
    results    = {}
    failed_at  = None

    for layer_num in layers:
        cost_label = _LAYER_EXECUTION_LABELS.get(layer_num, "unknown")
        print(f"\n{'─'*60}")
        print(f"[pipeline] Layer {layer_num}  ({cost_label})")
        print(f"{'─'*60}")

        try:
            result = run_layer(layer_num, run_id, args, l0_defaults)

            # Layer 0 returns the run_id
            if layer_num == 0:
                run_id = result.get("run_id") or result.get("manifest", {}).get("run_id")
                if not run_id:
                    print("[pipeline] Layer 0 did not return a run_id. Cannot continue.")
                    results[layer_num] = {"status": "failed", "error": "no run_id returned"}
                    failed_at = layer_num
                    break
                print(f"[pipeline] Run ID generated: {run_id}")
                output_contract = _resolve_output_contract(run_id)

            if not output_contract:
                output_contract = _resolve_output_contract(run_id)

            _enforce_layer_completion(layer_num, output_contract)

            results[layer_num] = {"status": "done"}
            print(f"[pipeline] Layer {layer_num} complete.")

        except Exception as e:
            import traceback
            print(f"\n[pipeline] Layer {layer_num} FAILED:")
            traceback.print_exc()
            results[layer_num] = {"status": "failed", "error": str(e)}
            failed_at = layer_num
            break

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    print(f"\n{'='*60}")
    print(f"Pipeline {'FAILED at Layer ' + str(failed_at) if failed_at is not None else 'COMPLETE'}")
    print(f"  Run ID  : {run_id}")
    print(f"  Elapsed : {elapsed:.1f}s")
    print(f"  Layers:")
    for ln in layers:
        status = results.get(ln, {}).get("status", "not reached")
        print(f"    Layer {ln:2d}: {status}")
    print(f"{'='*60}\n")

    if run_id:
        print(f"Run output: {RUNS_DIR / run_id}")
    if failed_at is not None:
        sys.exit(1)


if __name__ == "__main__":
    main()
