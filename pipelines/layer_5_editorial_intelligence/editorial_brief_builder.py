"""
Layer 5 — Module 10: Editorial Brief Builder (LLM)

Creates the selected_video_brief — the critical handoff from Layer 5 to Layer 6.
ONE LLM call total for the selected video (deep dive or roundup).

For deep dive: generates working_angle, suggested_thesis, tone_guidance,
  central_viewer_question (or adopts from viewer_value), required_sections.
For roundup: generates episode_theme, per-story segment_role and time budgets,
  viewer_promise, opening hook suggestion.

The brief carries forward Layer 4 evidence boundaries unchanged — no new claims
are invented. safe_claim_ids, cautious_claim_ids, do_not_use_claim_ids come
directly from the fact sheets.

Key function:
    build(editorial_decision, candidates_by_id, fact_sheets_by_id,
          viewer_values_by_id, format_config) → selected_video_brief dict

Usage:
    python editorial_brief_builder.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import asyncio
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from config.llm_config import get_profile

_MAX_SAFE_FACTS_IN_PROMPT = 6
_MAX_SEGMENT_STORIES = 8

_DEEP_DIVE_SYSTEM = """\
You are a senior editorial director for "AI Signal Brief," a YouTube channel for AI developers
and tech professionals. Evidence-first, practical, analytical, low-hype.

Given one selected story and its verified facts, generate the editorial direction for a
deep dive video. Your job is to define the editorial angle — NOT write the script.

Rules:
1. working_angle: a short, compelling editorial angle (1 sentence, present tense, active voice).
2. central_viewer_question: the question that structures the whole video.
3. suggested_thesis: what the video ultimately argues (grounded in the facts given, not hype).
4. tone_guidance: 3–4 words (e.g., "analytical, practical, skeptical").
5. required_sections: the logical sections of this video (4–6 sections from standard list).
6. opening_hook_idea: one sentence — a surprising fact or question to open with.
7. Never invent facts. Stay within what the verified facts show.

Standard sections: hook, what_happened, why_it_matters, technical_context,
  limitations, comparison, implications, final_takeaway

Return only valid JSON:
{
  "working_angle": "...",
  "central_viewer_question": "...",
  "suggested_thesis": "...",
  "tone_guidance": "...",
  "required_sections": ["..."],
  "opening_hook_idea": "..."
}"""

_ROUNDUP_SYSTEM = """\
You are a senior editorial director for "AI Signal Brief," a YouTube channel for AI developers
and tech professionals. Evidence-first, practical, analytical, low-hype.

Given a list of selected stories and their verified facts, generate the editorial structure
for a weekly AI news roundup video. Your job is to define the editorial structure — NOT write the script.

Rules:
1. episode_theme: one sentence tying all stories together with a real insight.
2. viewer_promise: what viewers understand/can do after watching (concrete, not generic).
3. opening_hook_idea: one sentence — the most surprising or counterintuitive thing across all stories.
4. story_order: reorder the stories from most to least impactful/surprising (return story_ids in order).
5. segment_guidance: for each story, assign segment_role and target_duration_seconds.
   - segment_roles: lead_story (90–110s), major_update (70–90s), short_update (50–70s), brief_mention (30–50s)
6. Total target: ~8 minutes = 480 seconds. Budget accordingly.
7. Never invent facts. Base everything on the story titles and verified facts provided.

Return only valid JSON:
{
  "episode_theme": "...",
  "viewer_promise": "...",
  "opening_hook_idea": "...",
  "story_order": ["story_id_1", "story_id_2", ...],
  "segment_guidance": {
    "story_id": {"segment_role": "...", "target_duration_seconds": 0}
  }
}"""


def _facts_snippet(safe_facts: list[dict], limit: int) -> str:
    lines = [f"- {f['claim_text']}" for f in safe_facts[:limit]]
    return "\n".join(lines) if lines else "(no facts)"


def _build_create_kwargs(model: str, temperature: float, messages: list) -> dict:
    kwargs: dict = {
        "model":           model,
        "response_format": {"type": "json_object"},
        "messages":        messages,
    }
    if "nano" not in model:
        kwargs["temperature"] = temperature
    return kwargs


def _make_openai_client():
    import openai
    from dotenv import load_dotenv
    import os
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_A_C_C")
    return openai.AsyncOpenAI(api_key=api_key)


async def _call_deep_dive(client, model: str, temperature: float,
                          cand: dict, viewer_value: dict) -> dict:
    facts_text = _facts_snippet(cand.get("safe_facts", []), _MAX_SAFE_FACTS_IN_PROMPT)
    vq = viewer_value.get("primary_viewer_question", "")

    user_msg = (
        f"Story: {cand['story_title']}\n"
        f"Type: {cand.get('story_type', 'unknown')}\n"
        f"Topics: {', '.join(cand.get('topics', []))}\n"
        f"Viewer question (from analysis): {vq}\n\n"
        f"Verified facts:\n{facts_text}\n\n"
        "Generate the editorial direction for a 10-minute deep dive video."
    )
    messages = [
        {"role": "system", "content": _DEEP_DIVE_SYSTEM},
        {"role": "user",   "content": user_msg},
    ]
    resp = await client.chat.completions.create(
        **_build_create_kwargs(model, temperature, messages)
    )
    return json.loads(resp.choices[0].message.content)


async def _call_roundup(client, model: str, temperature: float,
                        selected_cands: list[dict],
                        viewer_values_by_id: dict,
                        episode_theme: str) -> dict:
    stories_text = []
    for cand in selected_cands[:_MAX_SEGMENT_STORIES]:
        vv = viewer_values_by_id.get(cand["story_id"], {})
        facts = _facts_snippet(cand.get("safe_facts", []), 3)
        stories_text.append(
            f"Story ID: {cand['story_id']}\n"
            f"Title: {cand['story_title']}\n"
            f"Type: {cand.get('story_type', '')}\n"
            f"Viewer value: {vv.get('viewer_promise', '')}\n"
            f"Top facts:\n{facts}"
        )

    user_msg = (
        f"Roundup episode with {len(selected_cands)} stories.\n"
        f"Working theme: {episode_theme}\n\n"
        + "\n\n---\n\n".join(stories_text) +
        "\n\nGenerate the editorial structure for an 8-minute roundup video."
    )
    messages = [
        {"role": "system", "content": _ROUNDUP_SYSTEM},
        {"role": "user",   "content": user_msg},
    ]
    resp = await client.chat.completions.create(
        **_build_create_kwargs(model, temperature, messages)
    )
    return json.loads(resp.choices[0].message.content)


def _build_evidence_boundaries(candidates: list[dict]) -> dict:
    safe_ids      = []
    cautious_ids  = []
    dnu_ids       = []
    for cand in candidates:
        safe_ids.extend(cand.get("safe_claim_ids", []))
        cautious_ids.extend(cand.get("cautious_claim_ids", []))
        dnu_ids.extend(cand.get("do_not_use_claim_ids", []))
    return {
        "safe_claim_ids":     safe_ids,
        "cautious_claim_ids": cautious_ids,
        "do_not_use_claim_ids": dnu_ids,
        "contradiction_ids":  [],
        "evidence_gap_ids":   [],
    }


def _fallback_brief_deep_dive(cand: dict, viewer_value: dict) -> dict:
    return {
        "working_angle":          f"What {cand['story_title']} means for AI practitioners.",
        "central_viewer_question": viewer_value.get("primary_viewer_question",
                                                    "What changed and why does it matter?"),
        "suggested_thesis":       "This development signals a meaningful shift worth understanding.",
        "tone_guidance":          "analytical, practical, evidence-first",
        "required_sections":      ["hook", "what_happened", "why_it_matters", "limitations", "final_takeaway"],
        "opening_hook_idea":      "Start with the most surprising verified fact from this story.",
    }


def _fallback_brief_roundup(selected_cands: list[dict], episode_theme: str) -> dict:
    order = [c["story_id"] for c in selected_cands]
    guidance = {}
    for i, cand in enumerate(selected_cands):
        if i == 0:
            role, secs = "lead_story", 100
        elif i < 3:
            role, secs = "major_update", 80
        else:
            role, secs = "short_update", 60
        guidance[cand["story_id"]] = {"segment_role": role, "target_duration_seconds": secs}
    return {
        "episode_theme":       episode_theme,
        "viewer_promise":      "Viewers will understand the most important AI updates of the week.",
        "opening_hook_idea":   "Start with the most impactful headline from this week.",
        "story_order":         order,
        "segment_guidance":    guidance,
    }


async def _build_async(editorial_decision: dict,
                       candidates_by_id: dict,
                       viewer_values_by_id: dict,
                       format_config: dict) -> dict:
    profile     = get_profile("editorial_brief_builder")
    client      = _make_openai_client()
    model       = profile["model"]
    temperature = profile["temperature"]

    selected_format = editorial_decision.get("selected_format")
    video_id = f"video_brief_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{selected_format[:2]}_001"

    if selected_format == "deep_dive":
        primary_sid = editorial_decision["primary_story_id"]
        cand        = candidates_by_id[primary_sid]
        vv          = viewer_values_by_id.get(primary_sid, {})
        roundup_cfg = format_config.get("deep_dive", {})

        try:
            llm_result = await _call_deep_dive(client, model, temperature, cand, vv)
        except Exception:
            llm_result = _fallback_brief_deep_dive(cand, vv)

        content_direction = {
            "working_angle":            llm_result.get("working_angle", ""),
            "central_viewer_question":  llm_result.get("central_viewer_question",
                                                        vv.get("primary_viewer_question", "")),
            "viewer_promise":           vv.get("viewer_promise", ""),
            "suggested_thesis":         llm_result.get("suggested_thesis", ""),
            "tone_guidance":            llm_result.get("tone_guidance", "analytical, practical"),
            "opening_hook_idea":        llm_result.get("opening_hook_idea", ""),
        }
        format_guidance = {
            "target_duration_minutes": int(roundup_cfg.get("target_duration_minutes", 10)),
            "required_packet_type":    "deep_dive_packet",
            "required_sections":       llm_result.get("required_sections", [
                "hook", "what_happened", "why_it_matters", "limitations", "final_takeaway"
            ]),
        }
        evidence_boundaries = _build_evidence_boundaries([cand])

        return {
            "selected_video_id":     video_id,
            "run_id":                editorial_decision.get("run_id", ""),
            "selected_format":       "deep_dive",
            "primary_story_id":      primary_sid,
            "supporting_story_ids":  [],
            "content_direction":     content_direction,
            "evidence_boundaries":   evidence_boundaries,
            "format_guidance":       format_guidance,
            "handoff": {
                "next_layer":              "layer_6_format_specific_research_packets",
                "packet_type_to_build":    "deep_dive_packet",
                "ready_for_layer_6":       True,
            },
        }

    else:  # roundup
        selected_ids   = editorial_decision.get("selected_story_ids", [])
        selected_cands = [candidates_by_id[sid] for sid in selected_ids if sid in candidates_by_id]
        episode_theme  = editorial_decision.get("episode_theme", "")
        roundup_cfg    = format_config.get("roundup", {})

        try:
            llm_result = await _call_roundup(client, model, temperature,
                                             selected_cands, viewer_values_by_id, episode_theme)
        except Exception:
            llm_result = _fallback_brief_roundup(selected_cands, episode_theme)

        # Use LLM story order if valid, else keep original
        llm_order = llm_result.get("story_order", [])
        ordered_ids = [sid for sid in llm_order if sid in set(selected_ids)]
        remaining   = [sid for sid in selected_ids if sid not in set(ordered_ids)]
        final_order = ordered_ids + remaining

        seg_guidance_raw = llm_result.get("segment_guidance", {})
        story_segment_guidance = []
        for sid in final_order:
            cand = candidates_by_id.get(sid, {})
            seg  = seg_guidance_raw.get(sid, {})
            story_segment_guidance.append({
                "story_id":              sid,
                "story_title":           cand.get("story_title", ""),
                "segment_role":          seg.get("segment_role", "short_update"),
                "target_duration_seconds": int(seg.get("target_duration_seconds", 70)),
                "safe_claim_ids":        cand.get("safe_claim_ids", []),
                "viewer_promise":        viewer_values_by_id.get(sid, {}).get("viewer_promise", ""),
            })

        evidence_boundaries = _build_evidence_boundaries(selected_cands)

        return {
            "selected_video_id":     video_id,
            "run_id":                editorial_decision.get("run_id", ""),
            "selected_format":       "roundup",
            "selected_story_ids":    final_order,
            "primary_story_id":      None,
            "content_direction": {
                "episode_theme":    llm_result.get("episode_theme", episode_theme),
                "viewer_promise":   llm_result.get("viewer_promise", ""),
                "opening_hook_idea": llm_result.get("opening_hook_idea", ""),
                "tone_guidance":    "fast, clear, analytical, evidence-first",
            },
            "story_segment_guidance": story_segment_guidance,
            "evidence_boundaries":   evidence_boundaries,
            "format_guidance": {
                "target_duration_minutes": int(roundup_cfg.get("target_duration_minutes", 8)),
                "required_packet_type":   "roundup_packet",
                "max_stories":            int(roundup_cfg.get("max_stories", 8)),
            },
            "handoff": {
                "next_layer":           "layer_6_format_specific_research_packets",
                "packet_type_to_build": "roundup_packet",
                "ready_for_layer_6":    True,
            },
        }


def build(editorial_decision: dict, candidates_by_id: dict,
          viewer_values_by_id: dict, format_config: dict) -> dict:
    """Build the selected_video_brief. Runs one LLM call total."""
    return asyncio.run(
        _build_async(editorial_decision, candidates_by_id, viewer_values_by_id, format_config)
    )


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_4" / "story_fact_sheets.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    import yaml
    from pipelines.layer_5_editorial_intelligence.editorial_candidate_loader import load
    from pipelines.layer_5_editorial_intelligence.evidence_safety_gate       import gate_all
    from pipelines.layer_5_editorial_intelligence.audience_fit_analyzer      import analyze_all as af_all
    from pipelines.layer_5_editorial_intelligence.viewer_value_analyzer      import analyze_all as vv_all
    from pipelines.layer_5_editorial_intelligence.novelty_checker            import check_all
    from pipelines.layer_5_editorial_intelligence.format_fit_scorer          import score_all as ffs_all
    from pipelines.layer_5_editorial_intelligence.format_router              import route_all
    from pipelines.layer_5_editorial_intelligence.video_opportunity_scorer   import score_all as opp_all
    from pipelines.layer_5_editorial_intelligence.editorial_decision_maker   import decide

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result     = load(run_id, layer3_dir, layer4_dir)
    candidates = result["editorial_candidates"]

    safety  = gate_all(candidates)
    af      = af_all(candidates)
    print("  Running LLM for viewer value...")
    vv      = vv_all(candidates)
    novelty = check_all(candidates)
    ffs     = ffs_all(candidates, safety, af, vv, novelty)
    routing = route_all(candidates, ffs, safety, novelty)
    opp     = opp_all(candidates, safety, af, vv, novelty)

    with open("config/format_config.yaml") as f:
        fmt_cfg = yaml.safe_load(f)["formats"]

    ed = decide(candidates, routing, opp, fmt_cfg)
    ed["run_id"] = run_id

    cands_by_id  = {c["story_id"]: c for c in candidates}
    vv_by_id     = {v["story_id"]: v for v in vv}

    print("  Building editorial brief (1 LLM call)...")
    brief = build(ed, cands_by_id, vv_by_id, fmt_cfg)

    print(f"\nEditorial Brief Builder — {run_id}")
    print(f"  Format           : {brief['selected_format']}")
    if brief["selected_format"] == "roundup":
        print(f"  Stories selected : {len(brief.get('selected_story_ids', []))}")
        print(f"  Episode theme    : {brief['content_direction']['episode_theme'][:80]}")
        print(f"  Viewer promise   : {brief['content_direction']['viewer_promise'][:80]}")
        print(f"  Opening hook     : {brief['content_direction'].get('opening_hook_idea', '')[:80]}")
        print(f"  Segment plan     :")
        for sg in brief.get("story_segment_guidance", []):
            print(f"    [{sg['target_duration_seconds']:3d}s] {sg['segment_role']:<14}  {sg['story_title'][:50]}")
    else:
        cd = brief["content_direction"]
        print(f"  Primary story    : {brief.get('primary_story_id', '')[-20:]}")
        print(f"  Working angle    : {cd.get('working_angle', '')[:80]}")
        print(f"  Viewer question  : {cd.get('central_viewer_question', '')[:80]}")
        print(f"  Thesis candidate : {cd.get('suggested_thesis', '')[:80]}")
        print(f"  Required sections: {brief['format_guidance']['required_sections']}")
    print(f"  Safe claim count : {len(brief['evidence_boundaries']['safe_claim_ids'])}")
    print(f"  Ready for L6     : {brief['handoff']['ready_for_layer_6']}")
