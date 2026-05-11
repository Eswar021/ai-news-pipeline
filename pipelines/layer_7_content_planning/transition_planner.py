"""
Layer 7 — Module 6: Transition Planner

Plans the transition direction between consecutive sections.

For roundup: story-to-story transitions based on segment_role changes.
For deep_dive: concept-bridging transitions between analysis sections.

No new facts in transitions — only directional guidance.

Key function:
    plan(section_plan, layer7_ctx) → transition_plan list

Individual test:
    python transition_planner.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader         import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner import refine
from pipelines.layer_7_content_planning.narrative_arc_planner  import plan as plan_arc
from pipelines.layer_7_content_planning.section_planner        import plan as plan_sections


_ROLE_TRANSITION_OUT = {
    "intro":         "After setting the episode context",
    "lead_story":    "After covering the lead story in detail",
    "major_update":  "After explaining this major update",
    "short_update":  "After this update",
    "brief_mention": "After that quick update",
    "takeaway":      "After the final takeaway",
}

_ROLE_TRANSITION_IN = {
    "lead_story":    "move into the most important story of the week",
    "major_update":  "cover the next significant update",
    "short_update":  "quickly cover another notable update",
    "brief_mention": "briefly touch on one more development",
    "takeaway":      "pull everything together with a final insight",
    "cta":           "invite viewers to join the conversation",
}

_DEEP_DIVE_TRANSITIONS = {
    ("hook",         "what_happened"):    "From the central question, lay out the verified facts of the announcement.",
    ("what_happened", "why_it_matters"):  "Now that the facts are clear, explain why developers and technical professionals should care.",
    ("why_it_matters", "technical_context"): "After establishing relevance, go deeper into the technical or practical change.",
    ("technical_context", "limitations"): "Before concluding, cover what the evidence does not yet prove.",
    ("limitations",   "final_takeaway"):  "With limitations on the table, give a balanced conclusion.",
    ("final_takeaway", "cta"):            "After the takeaway, invite viewers to share their perspective.",
    ("background",    "what_happened"):   "With the context set, move into what specifically changed.",
    ("what_happened", "background"):      "Before going deeper, provide some background that makes the announcement clearer.",
}


def _roundup_transition(from_sec: dict, to_sec: dict) -> str:
    out  = _ROLE_TRANSITION_OUT.get(from_sec["segment_role"], "After this")
    into = _ROLE_TRANSITION_IN.get(to_sec["segment_role"], "move to the next topic")
    return f"{out}, {into}."


def _deep_dive_transition(from_sec: dict, to_sec: dict) -> str:
    key = (from_sec["section_key"], to_sec["section_key"])
    return _DEEP_DIVE_TRANSITIONS.get(
        key,
        f"From {from_sec['section_key'].replace('_',' ')}, move into {to_sec['section_key'].replace('_',' ')}."
    )


def plan(section_plan: list[dict], layer7_ctx: dict) -> list[dict]:
    packet_type = layer7_ctx["packet_type"]
    transitions = []

    for i in range(len(section_plan) - 1):
        from_sec = section_plan[i]
        to_sec   = section_plan[i + 1]

        if packet_type == "roundup":
            direction = _roundup_transition(from_sec, to_sec)
        else:
            direction = _deep_dive_transition(from_sec, to_sec)

        transitions.append({
            "transition_id":   f"tr_{i+1:02d}",
            "from_section_id": from_sec["section_id"],
            "from_section_key": from_sec["section_key"],
            "to_section_id":   to_sec["section_id"],
            "to_section_key":  to_sec["section_key"],
            "transition_direction": direction,
            "no_new_claims":   True,
        })

    return transitions


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx         = load_packet(layer6_dir)
    strategy    = refine(ctx)
    arc         = plan_arc(ctx, strategy)
    sections    = plan_sections(ctx, arc)
    transitions = plan(sections, ctx)

    print(f"Transitions planned : {len(transitions)}")
    for t in transitions:
        print(f"  {t['from_section_key']:20s} → {t['to_section_key']:20s} | {t['transition_direction'][:70]}")
