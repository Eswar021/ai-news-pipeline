"""
Layer 7 — Module 2: Viewer Promise Refiner

Refines the Layer 6 viewer promise into a structured viewer strategy for planning.

For roundup: derives central viewer question from episode theme + story titles.
For deep_dive: uses the central viewer question directly from the brief.

Rule-based — no LLM.

Key function:
    refine(layer7_ctx) → viewer_strategy dict

Individual test:
    python viewer_promise_refiner.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader import load as load_packet


_ROUNDUP_VIEWER_QUESTION = "What are the most important AI developments from this week, and what do they mean in practice?"

_ROUNDUP_PAYOFF_KEYS = [
    "understand what each update actually does",
    "separate product launches from technical advances",
    "know which changes affect developer tools and APIs",
    "identify which updates require follow-up attention",
]

_DEEP_DIVE_PAYOFF_KEYS = [
    "understand what was announced and what is verified",
    "know why this matters for developers or technical professionals",
    "identify what is still unproven or cautious",
    "walk away with a balanced, evidence-first view",
]


def refine(layer7_ctx: dict) -> dict:
    editorial   = layer7_ctx.get("editorial", {})
    packet_type = layer7_ctx["packet_type"]

    viewer_promise = editorial.get("viewer_promise", "")
    episode_theme  = editorial.get("episode_theme", "")
    tone_guidance  = editorial.get("tone_guidance", "fast, clear, analytical, evidence-first")

    if packet_type == "roundup":
        central_viewer_question = _ROUNDUP_VIEWER_QUESTION
        viewer_payoff           = _ROUNDUP_PAYOFF_KEYS

        # Refined promise: more concrete than L6's version (strip to first 2 sentences)
        sentences = viewer_promise.replace("—", ".").split(".")
        refined   = ". ".join(s.strip() for s in sentences[:2] if s.strip()) + "."

        # Add a brevity note for roundup
        refined += (
            " Every story is kept short and evidence-first — "
            "no hype, no padding."
        )
        promise_risk_level = "low"

    elif packet_type == "deep_dive":
        # For deep dive, use what L6 brief had as central_viewer_question if available
        central_viewer_question = (
            editorial.get("central_viewer_question")
            or episode_theme[:100]
            or "What does this announcement actually mean and what does the evidence show?"
        )
        viewer_payoff           = _DEEP_DIVE_PAYOFF_KEYS
        refined                 = viewer_promise or "Viewers will understand the facts, context, and limitations."
        promise_risk_level      = "low"

    else:
        central_viewer_question = "What does this video cover?"
        viewer_payoff           = []
        refined                 = viewer_promise or ""
        promise_risk_level      = "low"

    return {
        "central_viewer_question": central_viewer_question,
        "refined_viewer_promise":  refined,
        "original_viewer_promise": viewer_promise,
        "viewer_payoff":           viewer_payoff,
        "tone":                    tone_guidance,
        "target_audience":         "technical_but_accessible",
        "promise_risk_level":      promise_risk_level,
    }


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx      = load_packet(layer6_dir)
    strategy = refine(ctx)

    print(f"Format                 : {ctx['selected_format']}")
    print(f"Central viewer question: {strategy['central_viewer_question']}")
    print(f"Refined promise        : {strategy['refined_viewer_promise'][:120]}")
    print(f"Promise risk           : {strategy['promise_risk_level']}")
    print(f"Tone                   : {strategy['tone']}")
    print(f"Viewer payoff ({len(strategy['viewer_payoff'])} items):")
    for p in strategy["viewer_payoff"]:
        print(f"  - {p}")
