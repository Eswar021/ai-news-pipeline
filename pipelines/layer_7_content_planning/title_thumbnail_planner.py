"""
Layer 7 — Module 10: Title + Thumbnail Angle Planner (LLM)

Generates 6-8 title options and 5 thumbnail text options.
Uses the shared async LLM runtime with the manifest-backed profile.

Each title has:
  title, angle_type, accuracy_risk, click_potential, supported_by_claim_ids

Thumbnail texts are 2-4 words (for overlay text).

Blocked titles: overclaiming angles listed with reason.

Key function:
    plan(layer7_ctx, hook_plan) → title_thumbnail_plan dict

Individual test:
    python title_thumbnail_planner.py
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths    import RUNS_DIR
from pipelines.runtime_manifest import get_llm_profile
from llm.async_llm_runtime import execute_chat_request
from llm.prompt_loader import load_prompt_bundle
from pipelines.layer_7_content_planning.packet_loader          import load as load_packet
from pipelines.layer_7_content_planning.viewer_promise_refiner  import refine
from pipelines.layer_7_content_planning.narrative_arc_planner   import plan as plan_arc
from pipelines.layer_7_content_planning.section_planner         import plan as plan_sections
from pipelines.layer_7_content_planning.hook_planner            import plan as plan_hook


def _build_prompt(layer7_ctx: dict, hook_plan: dict) -> str:
    prompt_bundle = load_prompt_bundle("title_thumbnail_planner", run_id=layer7_ctx.get("run_id"))
    editorial      = layer7_ctx.get("editorial", {})
    episode_theme  = editorial.get("episode_theme", "")
    viewer_promise = editorial.get("viewer_promise", "")
    packet_type    = layer7_ctx["packet_type"]
    sections_ctx   = layer7_ctx.get("sections", [])

    story_titles = []
    for sec in sections_ctx:
        goal = sec.get("goal", "").replace("Cover: ", "")
        if goal:
            story_titles.append(f"  - {goal}")
    stories_text = "\n".join(story_titles[:8]) or "  (roundup of AI news)"

    rec_hook = hook_plan.get("recommended_hook", {})
    hook_dir = rec_hook.get("hook_direction", "")

    dnu_ids = layer7_ctx.get("do_not_use_claim_ids", set())
    dnu_text = ", ".join(sorted(list(dnu_ids))[:4]) or "none"
    preamble = prompt_bundle.get("user_preamble", "")

    return (
        f"Video format: {packet_type}\n"
        f"Channel: AI Signal Brief (audience: AI developers, tech professionals)\n\n"
        f"Episode theme:\n{episode_theme}\n\n"
        f"Viewer promise:\n{viewer_promise[:200]}\n\n"
        f"Stories covered:\n{stories_text}\n\n"
        f"Recommended hook direction:\n{hook_dir}\n\n"
        f"Do-not-use claims (must NOT be implied in titles):\n{dnu_text}\n\n"
        f"{preamble}"
    )


async def _call_llm(run_id: str | None, prompt: str, packet_type: str) -> dict:
    prompt_bundle = load_prompt_bundle("title_thumbnail_planner", run_id=run_id)
    messages = [
        {"role": "system", "content": prompt_bundle["system"]},
        {"role": "user",   "content": prompt},
    ]
    return await execute_chat_request(
        module_name="title_thumbnail_planner",
        run_id=run_id,
        messages=messages,
        request_name=f"title_thumbnail_{packet_type}",
        metadata={"packet_type": packet_type},
        parse_json=True,
    )


def _validate(raw: dict) -> dict:
    titles   = raw.get("recommended_title_angles", [])[:8]
    thumbs   = raw.get("thumbnail_text_options", [])[:5]
    blocked  = raw.get("blocked_title_angles", [])[:2]

    # Ensure required fields
    for t in titles:
        t.setdefault("accuracy_risk", "low")
        t.setdefault("click_potential", "medium")
        t.setdefault("supported_by_claim_ids", [])

    for th in thumbs:
        th.setdefault("risk", "low")
        if not th.get("text", "").isupper():
            th["text"] = th.get("text", "").upper()

    return {
        "recommended_title_angles": titles,
        "thumbnail_text_options":   thumbs,
        "blocked_title_angles":     blocked,
        "title_count":              len(titles),
        "thumbnail_text_count":     len(thumbs),
    }


def plan(layer7_ctx: dict, hook_plan: dict) -> dict:
    prompt      = _build_prompt(layer7_ctx, hook_plan)

    async def _run():
        return await _call_llm(layer7_ctx.get("run_id"), prompt, layer7_ctx["packet_type"])

    raw = asyncio.run(_run())
    return _validate(raw)


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

    print(f"[hook_planner] Calling LLM...")
    hook_plan = plan_hook(ctx, sections)

    print(f"[title_thumbnail_planner] Calling LLM (profile: {get_llm_profile('title_thumbnail_planner', run_id=run_id)['model']})...")
    tt_plan = plan(ctx, hook_plan)

    print(f"\nTitle options ({tt_plan['title_count']}):")
    for t in tt_plan["recommended_title_angles"]:
        risk = t["accuracy_risk"]
        pot  = t["click_potential"]
        print(f"  [{t['angle_type']:15s}] [{risk:6s}] [{pot:12s}] {t['title']}")

    print(f"\nThumbnail texts ({tt_plan['thumbnail_text_count']}):")
    for th in tt_plan["thumbnail_text_options"]:
        print(f"  [{th['risk']:6s}] {th['text']}")

    print(f"\nBlocked angles ({len(tt_plan['blocked_title_angles'])}):")
    for b in tt_plan["blocked_title_angles"]:
        print(f"  {b.get('title','')[:60]} — {b.get('reason','')[:60]}")
