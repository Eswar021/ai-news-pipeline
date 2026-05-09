"""
Layer 4 Orchestrator — Run the full content generation pipeline

Runs all 3 modules in sequence:
  1. script_planner    — LLM designs video structure (angle, sections, timing)
  2. script_writer     — LLM writes word-for-word script following the plan
  3. output_packager   — code-only: bundles script.txt, script.md, sources.json, metadata.json

Input:  output/layer_3_intelligence/context_packets/context_packet_*.json
Output: output/layer_4_content/scripts/{date}_{slug}/

Usage:
    python run_content.py                   # uses latest context packet
    python run_content.py --duration 8      # target 8-minute video
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import INTEL_CONTEXT, CONTENT_SCRIPTS, ensure_output_dirs

from pipelines.layer_4_content.script_planner import run_planner, save_plan
from pipelines.layer_4_content.script_writer import run_writer, save_script, count_words
from pipelines.layer_4_content.output_packager import run_packager


def find_latest(directory, pattern):
    candidates = sorted(Path(directory).glob(pattern), reverse=True)
    return candidates[0] if candidates else None


def run_content(packet_path=None, duration=10):
    ensure_output_dirs()

    packet_path = packet_path or find_latest(INTEL_CONTEXT, "context_packet_*.json")
    if not packet_path:
        print("No context packet found. Run Layer 3 first:")
        print("  python pipelines/layer_3_intelligence/run_intelligence.py")
        sys.exit(1)

    date_str = Path(packet_path).stem.replace("context_packet_", "")

    # ── Step 1: Plan ──
    print("=" * 65)
    print("  Step 1: SCRIPT PLANNER")
    print("=" * 65)
    plan = run_planner(packet_path, target_duration=duration)
    plan_path = save_plan(plan, date_str)

    print(f"\n  Angle: {plan['angle'][:60]}")
    print(f"  Sections: {plan['section_count']}  |  Est: {plan['estimated_duration_minutes']} min")
    print(f"  Saved → {plan_path.name}")

    # ── Step 2: Write ──
    print()
    print("=" * 65)
    print("  Step 2: SCRIPT WRITER")
    print("=" * 65)
    script_data = run_writer(plan_path, packet_path)
    txt_path, md_path = save_script(script_data, date_str)

    print(f"\n  Words: {script_data['total_words']} (~{script_data['est_duration_min']} min)")
    print(f"  Sections written: {script_data['section_count']}")
    print(f"  Saved → {txt_path.name}")

    # ── Step 3: Package ──
    print()
    print("=" * 65)
    print("  Step 3: OUTPUT PACKAGER")
    print("=" * 65)
    folder, sources = run_packager(txt_path, plan_path, packet_path)

    files = list(folder.iterdir())
    print(f"\n  Folder: {folder.name}/")
    for f in sorted(files):
        print(f"    {f.name:<20} {f.stat().st_size:>8,} bytes")

    # ── Final summary ──
    print()
    print("=" * 65)
    print("  LAYER 4 COMPLETE")
    print("=" * 65)
    print(f"  Topic:    {plan['topic']}")
    print(f"  Script:   {script_data['total_words']} words, ~{script_data['est_duration_min']} min")
    print(f"  Sources:  {len(sources)} (for YouTube description)")
    print()
    print(f"  Open and record:")
    print(f"    {folder}/script.txt")
    print()
    print(f"  Paste into YouTube description:")
    for s in sources:
        print(f"    • {s['title'][:45]} — {s['url'][:55]}")

    return folder


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run full Layer 4 content generation pipeline")
    parser.add_argument("--packet",   help="Path to context_packet JSON (default: latest)")
    parser.add_argument("--duration", type=int, default=10, help="Target video duration in minutes (default: 10)")
    args = parser.parse_args()

    run_content(packet_path=args.packet, duration=args.duration)
