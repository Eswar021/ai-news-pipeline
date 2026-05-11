"""
Layer 7 — Module 11: CTA + Engagement Planner

Plans the call-to-action and viewer engagement prompt.
Rule-based — no LLM.

For roundup: comment prompt tied to the episode theme.
For deep_dive: comment prompt tied to the central viewer question.

Key function:
    plan(layer7_ctx, viewer_strategy) → cta_plan dict

Individual test:
    python cta_planner.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader          import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner  import refine


_ROUNDUP_COMMENT_TEMPLATE = (
    "Which of this week's AI updates do you think will have the most real-world impact? "
    "Drop your pick in the comments."
)

_DEEP_DIVE_COMMENT_TEMPLATE = (
    "Based on the evidence we covered — do you think this actually changes things, "
    "or is it still too early to tell? Let us know in the comments."
)


def plan(layer7_ctx: dict, viewer_strategy: dict) -> dict:
    packet_type     = layer7_ctx["packet_type"]
    episode_theme   = layer7_ctx.get("editorial", {}).get("episode_theme", "")
    central_question = viewer_strategy.get("central_viewer_question", "")

    if packet_type == "roundup":
        comment_prompt = _ROUNDUP_COMMENT_TEMPLATE
        cta_style      = "topic_based_weekly"
    elif packet_type == "deep_dive":
        comment_prompt = _DEEP_DIVE_COMMENT_TEMPLATE
        cta_style      = "evidence_opinion"
    else:
        comment_prompt = "What do you think about today's topic? Share in the comments."
        cta_style      = "generic"

    return {
        "comment_prompt":         comment_prompt,
        "subscribe_cta_timing":   "near_end",
        "subscribe_cta_style":    "natural",
        "cta_style":              cta_style,
        "avoid": [
            "Asking for subscribe before value is delivered.",
            "Generic 'like and subscribe' without topic connection.",
            "Mid-video CTA interrupting a key explanation.",
        ],
        "placement_note": (
            "Place comment prompt at the end of final_takeaway, before subscribe CTA. "
            "Subscribe CTA should come last, briefly and naturally."
        ),
    }


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx      = load_packet(layer6_dir)
    strategy = refine(ctx)
    cta      = plan(ctx, strategy)

    print(f"CTA style      : {cta['cta_style']}")
    print(f"Subscribe CTA  : {cta['subscribe_cta_timing']}")
    print(f"Comment prompt : {cta['comment_prompt']}")
    print(f"Placement note : {cta['placement_note']}")
    print(f"\nAvoid:")
    for a in cta["avoid"]:
        print(f"  - {a}")
