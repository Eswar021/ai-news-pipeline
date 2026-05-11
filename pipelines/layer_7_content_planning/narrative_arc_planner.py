"""
Layer 7 — Module 3: Narrative Arc Planner

Builds the narrative arc and story flow for the video.
Rule-based — no LLM. Uses segment roles from L6 context to order the flow.

For roundup:
  episode theme → intro_hook → lead_story → major_updates → short_updates →
  brief_mentions → final_takeaway → cta

For deep_dive:
  tension → what_happened → why_it_matters → technical_context →
  limitations → final_takeaway → cta

Key function:
    plan(layer7_ctx, viewer_strategy) → narrative_plan dict

Individual test:
    python narrative_arc_planner.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader        import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner import refine


_ROUNDUP_ARC = (
    "episode theme → intro hook → lead story → major updates → "
    "short updates → brief mentions → final pattern across stories"
)

_DEEP_DIVE_ARC = (
    "tension → what happened → why it matters → "
    "technical context → limitations → final takeaway"
)

_SEGMENT_ROLE_PURPOSE = {
    "lead_story":    "Explain the most important story of the week in full.",
    "major_update":  "Cover a significant update — what changed and why it matters.",
    "short_update":  "Quickly explain a notable update with key facts.",
    "brief_mention": "Mention a minor update — one core fact and its implication.",
}


def _roundup_story_flow(sections: list[dict]) -> list[dict]:
    flow = [{
        "order":   1,
        "stage":   "intro_hook",
        "purpose": "Preview the week's most important AI updates and set the evidence-first tone.",
    }]

    for i, sec in enumerate(sections, start=2):
        role    = sec.get("segment_role", "short_update")
        goal    = sec.get("goal", f"Cover story {i-1}.")
        purpose = _SEGMENT_ROLE_PURPOSE.get(role, goal)
        story_suffix = sec.get("story_id", "")[-6:]
        flow.append({
            "order":    i,
            "stage":    f"story_{i-1}",
            "story_id": sec.get("story_id", ""),
            "role":     role,
            "purpose":  purpose,
            "label":    goal.replace("Cover: ", ""),
        })

    flow.append({
        "order":   len(sections) + 2,
        "stage":   "final_takeaway",
        "purpose": "Connect the common thread across all stories and give viewers a practical takeaway.",
    })
    flow.append({
        "order":   len(sections) + 3,
        "stage":   "cta",
        "purpose": "Ask viewers to engage — tied to the episode theme.",
    })

    return flow


def _deep_dive_story_flow(sections: list[dict]) -> list[dict]:
    _STAGE_PURPOSE = {
        "what_happened":    "State the verified announcement and what specifically changed.",
        "why_it_matters":   "Connect the facts to viewer relevance and developer workflow impact.",
        "technical_context": "Explain the technical or practical detail without overhyping.",
        "limitations":       "Clarify what is not proven, early-stage, or uncertain.",
        "final_takeaway":    "Give a balanced conclusion grounded in the evidence.",
        "background":        "Provide necessary context before the main analysis.",
    }

    flow = [{
        "order":   1,
        "stage":   "hook",
        "purpose": "Create curiosity by posing the central viewer question.",
    }]

    for i, sec in enumerate(sections, start=2):
        key     = sec.get("section_key", f"section_{i}")
        purpose = _STAGE_PURPOSE.get(key, sec.get("goal", f"Cover {key}."))
        flow.append({
            "order":   i,
            "stage":   key,
            "purpose": purpose,
        })

    flow.append({
        "order":   len(sections) + 2,
        "stage":   "cta",
        "purpose": "Ask viewers to share their view — tied to central question.",
    })

    return flow


def _roundup_tension(editorial: dict) -> str:
    theme = editorial.get("episode_theme", "")
    if "autonomous" in theme.lower() or "coding" in theme.lower():
        return (
            "AI is shipping at speed — but the real question is which updates "
            "actually change something and which are product noise."
        )
    return (
        "This week's AI news covers multiple announcements — "
        "the tension is separating meaningful advances from routine releases."
    )


def _deep_dive_tension(editorial: dict) -> str:
    theme = editorial.get("episode_theme", "")
    return theme[:150] if theme else "The announcement sounds significant — the question is whether the evidence supports the hype."


def plan(layer7_ctx: dict, viewer_strategy: dict) -> dict:
    packet_type = layer7_ctx["packet_type"]
    sections    = layer7_ctx.get("sections", [])
    editorial   = layer7_ctx.get("editorial", {})

    if packet_type == "roundup":
        narrative_arc = _ROUNDUP_ARC
        core_tension  = _roundup_tension(editorial)
        story_flow    = _roundup_story_flow(sections)

    elif packet_type == "deep_dive":
        narrative_arc = _DEEP_DIVE_ARC
        core_tension  = _deep_dive_tension(editorial)
        story_flow    = _deep_dive_story_flow(sections)

    else:
        narrative_arc = "hook → content → takeaway"
        core_tension  = ""
        story_flow    = []

    return {
        "narrative_arc":            narrative_arc,
        "core_tension":             core_tension,
        "central_viewer_question":  viewer_strategy["central_viewer_question"],
        "story_flow":               story_flow,
        "total_stages":             len(story_flow),
    }


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx      = load_packet(layer6_dir)
    strategy = refine(ctx)
    arc      = plan(ctx, strategy)

    print(f"Narrative arc  : {arc['narrative_arc']}")
    print(f"Core tension   : {arc['core_tension'][:100]}")
    print(f"Total stages   : {arc['total_stages']}")
    print(f"\nStory flow:")
    for stage in arc["story_flow"]:
        label = stage.get("label") or stage["purpose"][:60]
        print(f"  {stage['order']:2d}. [{stage['stage']:15s}] {label}")
