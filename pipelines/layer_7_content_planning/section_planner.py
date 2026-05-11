"""
Layer 7 — Module 4: Section Planner

Builds the section-by-section video plan from L6 packet context.

For roundup:
  intro_hook (35s) + N story segments (from L6 target_seconds) +
  final_takeaway (45s) + cta (15s)

For deep_dive:
  hook (30s) + research_sections (from L6) + final_takeaway (45s) + cta (15s)

Each section gets:
  section_id, section_key, target_duration_seconds, section_goal,
  required_claim_ids, optional_claim_ids, cautious_claim_ids,
  writer_instructions, story_id (roundup only)

Key function:
    plan(layer7_ctx, narrative_plan) → section_plan list

Individual test:
    python section_planner.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_7_content_planning.packet_loader         import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner import refine
from pipelines.layer_7_content_planning.narrative_arc_planner  import plan as plan_arc


_ROLE_INSTRUCTIONS = {
    "lead_story": [
        "Give this story the most air time — it is the lead.",
        "Open with the most striking verified fact.",
        "Explain what changed and why developers or tech professionals should care.",
        "Use at least 2 required claim IDs as the factual backbone.",
    ],
    "major_update": [
        "Cover the key announcement and its practical implication.",
        "Keep it focused — one main point plus one supporting detail.",
        "Do not pad with background unless it is directly needed.",
    ],
    "short_update": [
        "One verified fact + one practical takeaway. Keep it tight.",
        "No more than 2-3 sentences of explanation.",
    ],
    "brief_mention": [
        "Mention this quickly — one sentence on what it is, one on why it matters.",
        "Stay within the required claim IDs only.",
    ],
}

_INTRO_HOOK_INSTRUCTIONS = [
    "Preview the episode theme without listing all stories by name.",
    "Set the evidence-first tone immediately.",
    "Tease the most interesting story to create curiosity.",
    "Do not make claims here — save evidence for the stories.",
]

_FINAL_TAKEAWAY_INSTRUCTIONS = [
    "Connect the common thread across all stories.",
    "Give viewers one practical pattern or takeaway they can apply.",
    "Stay grounded — no hype or prediction beyond what the evidence supports.",
]

_CTA_INSTRUCTIONS = [
    "Ask one topic-relevant question for viewers to answer in comments.",
    "Subscribe CTA should feel natural, not forced.",
    "Do not interrupt the flow — place after the final takeaway.",
]


def _build_roundup_sections(sections_ctx: list[dict]) -> list[dict]:
    result = []

    # intro_hook
    result.append({
        "section_id":              "sec_00",
        "section_key":             "intro_hook",
        "target_duration_seconds": 35,
        "section_goal":            "Preview the week's most important AI updates and set evidence-first tone.",
        "story_id":                None,
        "segment_role":            "intro",
        "required_claim_ids":      [],
        "optional_claim_ids":      [],
        "cautious_claim_ids":      [],
        "writer_instructions":     _INTRO_HOOK_INSTRUCTIONS,
    })

    for i, sec in enumerate(sections_ctx, start=1):
        role         = sec.get("segment_role", "short_update")
        required_ids = [c["claim_id"] for c in sec.get("required_claims", [])]
        optional_ids = sec.get("optional_claim_ids", [])
        cautious_ids = sec.get("cautious_claim_ids", [])
        instructions = _ROLE_INSTRUCTIONS.get(role, _ROLE_INSTRUCTIONS["short_update"])

        result.append({
            "section_id":              f"sec_{i:02d}",
            "section_key":             f"story_{i}",
            "target_duration_seconds": sec.get("target_seconds", 60),
            "section_goal":            sec.get("goal", f"Cover story {i}."),
            "story_id":                sec.get("story_id"),
            "segment_role":            role,
            "required_claim_ids":      required_ids,
            "optional_claim_ids":      optional_ids,
            "cautious_claim_ids":      cautious_ids,
            "writer_instructions":     instructions,
        })

    n = len(sections_ctx)

    # final_takeaway
    result.append({
        "section_id":              f"sec_{n+1:02d}",
        "section_key":             "final_takeaway",
        "target_duration_seconds": 45,
        "section_goal":            "Tie all stories together with one shared insight or practical pattern.",
        "story_id":                None,
        "segment_role":            "takeaway",
        "required_claim_ids":      [],
        "optional_claim_ids":      [],
        "cautious_claim_ids":      [],
        "writer_instructions":     _FINAL_TAKEAWAY_INSTRUCTIONS,
    })

    # cta
    result.append({
        "section_id":              f"sec_{n+2:02d}",
        "section_key":             "cta",
        "target_duration_seconds": 15,
        "section_goal":            "Engage viewers with a topic-relevant question and subscribe prompt.",
        "story_id":                None,
        "segment_role":            "cta",
        "required_claim_ids":      [],
        "optional_claim_ids":      [],
        "cautious_claim_ids":      [],
        "writer_instructions":     _CTA_INSTRUCTIONS,
    })

    return result


def _build_deep_dive_sections(sections_ctx: list[dict]) -> list[dict]:
    _SECTION_GOALS = {
        "what_happened":    "State the verified announcement and what specifically changed.",
        "why_it_matters":   "Explain the practical developer or technical relevance.",
        "technical_context": "Describe the technical shift clearly, without overhyping.",
        "limitations":       "Clarify what is not yet proven or is early-stage.",
        "background":        "Provide context that helps viewers understand the announcement.",
        "final_takeaway":    "Give a balanced conclusion tied to the evidence.",
    }

    result = [{
        "section_id":              "sec_00",
        "section_key":             "hook",
        "target_duration_seconds": 30,
        "section_goal":            "Pose the central viewer question and create curiosity.",
        "story_id":                None,
        "segment_role":            "hook",
        "required_claim_ids":      [],
        "optional_claim_ids":      [],
        "cautious_claim_ids":      [],
        "writer_instructions":     [
            "Open with the central viewer question directly.",
            "Do not make claims yet — save evidence for content sections.",
            "Promise an evidence-first breakdown.",
        ],
    }]

    for i, sec in enumerate(sections_ctx, start=1):
        key          = sec.get("section_key", f"section_{i}")
        required_ids = [c["claim_id"] for c in sec.get("required_claims", [])]
        optional_ids = sec.get("optional_claim_ids", [])
        cautious_ids = sec.get("cautious_claim_ids", [])
        goal         = _SECTION_GOALS.get(key, sec.get("goal", f"Cover {key}."))

        result.append({
            "section_id":              f"sec_{i:02d}",
            "section_key":             key,
            "target_duration_seconds": sec.get("target_seconds", 90),
            "section_goal":            goal,
            "story_id":                sec.get("story_id"),
            "segment_role":            key,
            "required_claim_ids":      required_ids,
            "optional_claim_ids":      optional_ids,
            "cautious_claim_ids":      cautious_ids,
            "writer_instructions":     [],
        })

    n = len(sections_ctx)

    result.append({
        "section_id":              f"sec_{n+1:02d}",
        "section_key":             "final_takeaway",
        "target_duration_seconds": 45,
        "section_goal":            "Give a balanced conclusion tied to verified facts.",
        "story_id":                None,
        "segment_role":            "takeaway",
        "required_claim_ids":      [],
        "optional_claim_ids":      [],
        "cautious_claim_ids":      [],
        "writer_instructions":     _FINAL_TAKEAWAY_INSTRUCTIONS,
    })

    result.append({
        "section_id":              f"sec_{n+2:02d}",
        "section_key":             "cta",
        "target_duration_seconds": 15,
        "section_goal":            "Invite viewers to share their perspective on the central question.",
        "story_id":                None,
        "segment_role":            "cta",
        "required_claim_ids":      [],
        "optional_claim_ids":      [],
        "cautious_claim_ids":      [],
        "writer_instructions":     _CTA_INSTRUCTIONS,
    })

    return result


def plan(layer7_ctx: dict, narrative_plan: dict) -> list[dict]:
    packet_type  = layer7_ctx["packet_type"]
    sections_ctx = layer7_ctx.get("sections", [])

    if packet_type == "roundup":
        return _build_roundup_sections(sections_ctx)
    elif packet_type == "deep_dive":
        return _build_deep_dive_sections(sections_ctx)
    else:
        return []


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx      = load_packet(layer6_dir)
    strategy = refine(ctx)
    arc      = plan_arc(ctx, strategy)
    sections = plan(ctx, arc)

    total_seconds = sum(s["target_duration_seconds"] for s in sections)
    print(f"Sections built : {len(sections)}")
    print(f"Total duration : {total_seconds}s ({total_seconds/60:.1f} min)")
    print()
    for s in sections:
        req = len(s["required_claim_ids"])
        print(f"  {s['section_id']} | {s['section_key']:20s} | {s['target_duration_seconds']:3d}s | "
              f"required={req} | role={s['segment_role']}")
