"""
Layer 7 — Module 7: Pacing + Retention Planner

Plans time budgets and retention beats.

Retention beats are placed every ~60-90s to prevent drop-off:
  viewer_promise  — remind viewers what they'll get
  curiosity_loop  — tease what's coming
  pattern_note    — note an emerging pattern across stories
  limitation_turn — introduce a qualification before the end
  final_setup     — set up the final takeaway

Key function:
    plan(section_plan, layer7_ctx) → pacing_retention_plan dict

Individual test:
    python pacing_retention_planner.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader         import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner import refine
from pipelines.layer_7_content_planning.narrative_arc_planner  import plan as plan_arc
from pipelines.layer_7_content_planning.section_planner        import plan as plan_sections


_BEAT_INTERVAL_ROUNDUP  = 60   # seconds
_BEAT_INTERVAL_DEEP_DIVE = 90


def _seconds_to_timestamp(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def _roundup_beats(section_plan: list[dict], total_seconds: int) -> list[dict]:
    beats = []

    # Beat 1: viewer promise after intro hook (~30s)
    beats.append({
        "beat_id":          "beat_01",
        "timestamp_target": _seconds_to_timestamp(30),
        "beat_type":        "viewer_promise",
        "instruction":      "Tell viewers exactly what they will understand by the end of this episode.",
    })

    # Beat 2: curiosity loop after lead story
    lead_end = 35 + section_plan[1]["target_duration_seconds"]  # intro + story_1
    beats.append({
        "beat_id":          "beat_02",
        "timestamp_target": _seconds_to_timestamp(lead_end),
        "beat_type":        "curiosity_loop",
        "instruction":      "Tease one upcoming story to keep viewers watching — mention it by topic, not by name.",
    })

    # Beat 3: mid-point pattern note
    mid = total_seconds // 2
    beats.append({
        "beat_id":          "beat_03",
        "timestamp_target": _seconds_to_timestamp(mid),
        "beat_type":        "pattern_note",
        "instruction":      "Note the emerging pattern: multiple stories point toward the same underlying shift.",
    })

    # Beat 4: limitation turn before final takeaway
    before_takeaway = total_seconds - 60
    beats.append({
        "beat_id":          "beat_04",
        "timestamp_target": _seconds_to_timestamp(max(before_takeaway, mid + 30)),
        "beat_type":        "limitation_turn",
        "instruction":      "Briefly acknowledge what is still early-stage or uncertain before the final takeaway.",
    })

    return beats


def _deep_dive_beats(section_plan: list[dict], total_seconds: int) -> list[dict]:
    beats = []

    beats.append({
        "beat_id":          "beat_01",
        "timestamp_target": "00:30",
        "beat_type":        "viewer_promise",
        "instruction":      "Tell viewers what they will know by the end — separate evidence from hype.",
    })
    beats.append({
        "beat_id":          "beat_02",
        "timestamp_target": "02:00",
        "beat_type":        "curiosity_loop",
        "instruction":      "Tease the most interesting finding coming later in the video.",
    })
    beats.append({
        "beat_id":          "beat_03",
        "timestamp_target": _seconds_to_timestamp(total_seconds // 2),
        "beat_type":        "pattern_note",
        "instruction":      "Mark the shift from what happened to what it means — keep viewers engaged.",
    })
    beats.append({
        "beat_id":          "beat_04",
        "timestamp_target": _seconds_to_timestamp(total_seconds - 90),
        "beat_type":        "limitation_turn",
        "instruction":      "Introduce the limitation section — frame it as making the analysis more credible.",
    })

    return beats


def plan(section_plan: list[dict], layer7_ctx: dict) -> dict:
    packet_type   = layer7_ctx["packet_type"]
    total_seconds = sum(s["target_duration_seconds"] for s in section_plan)

    # Section time budget (carry from section_plan)
    section_budget = [
        {
            "section_id":              s["section_id"],
            "section_key":             s["section_key"],
            "target_duration_seconds": s["target_duration_seconds"],
        }
        for s in section_plan
    ]

    if packet_type == "roundup":
        retention_beats = _roundup_beats(section_plan, total_seconds)
        beat_interval   = _BEAT_INTERVAL_ROUNDUP
        avoid           = [
            "listing all stories at the start without context",
            "more than 2 minutes on a single short-update story",
            "repeating the same claim across two stories",
        ]
    else:
        retention_beats = _deep_dive_beats(section_plan, total_seconds)
        beat_interval   = _BEAT_INTERVAL_DEEP_DIVE
        avoid           = [
            "long background before viewer stakes are established",
            "more than 3 minutes without a new insight",
            "repeating the same claim in multiple sections",
        ]

    return {
        "target_duration_seconds":  total_seconds,
        "target_duration_minutes":  round(total_seconds / 60, 1),
        "beat_interval_seconds":    beat_interval,
        "section_time_budget":      section_budget,
        "retention_beats":          retention_beats,
        "pacing_avoid":             avoid,
    }


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx      = load_packet(layer6_dir)
    strategy = refine(ctx)
    arc      = plan_arc(ctx, strategy)
    sections = plan_sections(ctx, arc)
    pacing   = plan(sections, ctx)

    print(f"Total duration   : {pacing['target_duration_seconds']}s ({pacing['target_duration_minutes']} min)")
    print(f"Retention beats  : {len(pacing['retention_beats'])}")
    print()
    for beat in pacing["retention_beats"]:
        print(f"  [{beat['timestamp_target']}] {beat['beat_type']:18s} — {beat['instruction'][:65]}")
    print()
    print(f"Pacing avoid ({len(pacing['pacing_avoid'])} rules):")
    for rule in pacing["pacing_avoid"]:
        print(f"  - {rule}")
