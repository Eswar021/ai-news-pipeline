"""
AI Content Creation — Pipeline Runner

Runs any combination of layers, in order, using config/pipeline_config.yaml.

Usage:
    python pipeline.py                              # default preset = collection_only (L0-L3)
    python pipeline.py --preset with_facts          # L0-L4 (best ChatGPT handoff point)
    python pipeline.py --preset with_editorial      # L0-L6
    python pipeline.py --preset full_auto           # L0-L10

    python pipeline.py --layers 0,1,2,3,4           # explicit layer list
    python pipeline.py --run-id <id> --layers 5,6   # continue an existing run from a midpoint

Layer 0 CLI overrides:
    --trigger-type    manual | scheduled | api
    --target-format   auto | roundup | deep_dive | news_brief
    --lookback-hours  integer (overrides run_defaults.yaml)
    --topic-focus     "AI news" | "AI safety" | etc.
    --depth           standard | deep
    --max-videos      integer

API cost summary (approximate):
    L0-L3  : zero API cost
    L4     : ~218 calls (claim extraction)
    L5     : ~12 calls  (editorial scoring)
    L7     : ~2 calls   (hook + title)
    L8     : ~11 calls  (script sections)
    L9     : ~9 calls   (verification)
    L6,L10 : zero API cost
"""

import sys
import argparse
import yaml
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config.paths import RUNS_DIR, CONFIG_DIR

PIPELINE_CONFIG = CONFIG_DIR / "pipeline_config.yaml"

_LAYER_COSTS = {
    0: "free",
    1: "free",
    2: "free",
    3: "free (local embeddings)",
    4: "~218 API calls",
    5: "~12 API calls",
    6: "free",
    7: "~2 API calls",
    8: "~11 API calls",
    9: "~9 API calls",
    10: "free",
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


def run_layer(layer_num: int, run_id: str, args, l0_defaults: dict) -> dict:
    if layer_num == 0:
        from pipelines.layer_0_control.run_layer_0 import run_layer_0
        return run_layer_0(
            trigger_type   = args.trigger_type  or l0_defaults.get("trigger_type", "manual"),
            target_format  = args.target_format or l0_defaults.get("target_format", "auto"),
            lookback_hours = args.lookback_hours or l0_defaults.get("lookback_hours"),
            topic_focus    = args.topic_focus   or l0_defaults.get("topic_focus", "AI news"),
            depth          = args.depth         or l0_defaults.get("depth", "standard"),
            max_videos     = args.max_videos    or l0_defaults.get("max_videos", 1),
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
    parser.add_argument("--target-format", dest="target_format", default=None)
    parser.add_argument("--lookback-hours", dest="lookback_hours", type=int, default=None)
    parser.add_argument("--topic-focus", dest="topic_focus", default=None)
    parser.add_argument("--depth", default=None)
    parser.add_argument("--max-videos", dest="max_videos", type=int, default=None)

    args = parser.parse_args()

    cfg         = load_config()
    layers      = resolve_layers(args, cfg)
    l0_defaults = cfg.get("layer_0_defaults", {})
    run_id      = args.run_id
    continuing  = run_id is not None

    # If continuing an existing run, Layer 0 is not needed
    if continuing and 0 in layers:
        layers = [l for l in layers if l != 0]
        print(f"[pipeline] --run-id provided — Layer 0 skipped.")

    # Fresh run requires Layer 0 to generate the run_id
    if not continuing and 0 not in layers:
        print("[pipeline] Error: Layer 0 is required when starting a fresh run.")
        print("           Either include layer 0 in --layers, or provide --run-id to continue an existing run.")
        sys.exit(1)

    # Print run plan
    preset_label = args.preset or cfg["pipeline"]["default_preset"] if not args.layers else "custom"
    api_layers   = [l for l in layers if l not in (0, 1, 2, 3, 6, 10)]

    print(f"\n{'='*60}")
    print(f"Pipeline Runner")
    print(f"  Preset  : {preset_label}")
    print(f"  Layers  : {layers}")
    print(f"  Run ID  : {run_id or '(will be generated by Layer 0)'}")
    if api_layers:
        total_cost = sum({4: 218, 5: 12, 7: 2, 8: 11, 9: 9}.get(l, 0) for l in api_layers)
        print(f"  API cost: ~{total_cost} LLM calls (layers {api_layers})")
    else:
        print(f"  API cost: zero (all selected layers are free)")
    print(f"{'='*60}\n")

    started_at = datetime.now(timezone.utc)
    results    = {}
    failed_at  = None

    for layer_num in layers:
        cost_label = _LAYER_COSTS.get(layer_num, "unknown")
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
