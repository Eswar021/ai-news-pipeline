"""
Layer 7 — Module 9: Hook Planner (LLM)

Generates 3 hook directions for the video opening.
Uses the shared async LLM runtime with the manifest-backed profile.

Hook types for roundup:
  roundup_speed_hook, tension_hook, contrast_hook, question_hook, stakes_hook

Output per hook:
  hook_type, hook_direction, supported_by_claim_ids, risk_level, why_it_works

Also produces blocked_hook_angles (angles that would require unsupported claims).

Key function:
    plan(layer7_ctx, section_plan) → hook_plan dict

Individual test:
    python hook_planner.py
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
from pipelines.layer_7_content_planning.section_planner         import plan as plan_sections
from pipelines.layer_7_content_planning.viewer_promise_refiner  import refine
from pipelines.layer_7_content_planning.narrative_arc_planner   import plan as plan_arc


def _build_prompt(layer7_ctx: dict, section_plan: list[dict]) -> str:
    prompt_bundle = load_prompt_bundle("hook_planner", run_id=layer7_ctx.get("run_id"))
    editorial    = layer7_ctx.get("editorial", {})
    episode_theme = editorial.get("episode_theme", "")
    viewer_promise = editorial.get("viewer_promise", "")
    dnu_ids      = layer7_ctx.get("do_not_use_claim_ids", set())
    packet_type  = layer7_ctx["packet_type"]

    # Collect story titles and first required claim for context
    story_lines = []
    sample_claims = []
    for sec in section_plan:
        key = sec["section_key"]
        if key.startswith("story_"):
            goal = sec["section_goal"].replace("Cover: ", "").replace("Cover story", "Story")
            story_lines.append(f"  - {goal} ({sec['target_duration_seconds']}s)")
            for cid in sec["required_claim_ids"][:1]:
                sample_claims.append(cid)

    stories_text  = "\n".join(story_lines) or "  (no stories)"
    dnu_text      = ", ".join(sorted(list(dnu_ids))[:6]) or "none"
    claims_sample = ", ".join(sample_claims[:6]) if sample_claims else "none"
    preamble      = prompt_bundle.get("user_preamble", "")

    return (
        f"Video format: {packet_type}\n"
        f"Channel: AI Signal Brief (audience: AI developers, tech professionals)\n\n"
        f"Episode theme:\n{episode_theme}\n\n"
        f"Viewer promise:\n{viewer_promise[:200]}\n\n"
        f"Stories covered:\n{stories_text}\n\n"
        f"Sample verified claim IDs (safe to use):\n{claims_sample}\n\n"
        f"Do-not-use claim IDs (must NOT appear in hook):\n{dnu_text}\n\n"
        f"{preamble}"
    )


async def _call_llm(run_id: str | None, prompt: str, packet_type: str) -> dict:
    prompt_bundle = load_prompt_bundle("hook_planner", run_id=run_id)
    messages = [
        {"role": "system", "content": prompt_bundle["system"]},
        {"role": "user",   "content": prompt},
    ]
    return await execute_chat_request(
        module_name="hook_planner",
        run_id=run_id,
        messages=messages,
        request_name=f"hook_{packet_type}",
        metadata={"packet_type": packet_type},
        parse_json=True,
    )


def _validate_hook_plan(raw: dict) -> dict:
    rec = raw.get("recommended_hook", {})
    if not rec.get("hook_type"):
        rec["hook_type"] = "roundup_speed_hook"
    if not rec.get("risk_level"):
        rec["risk_level"] = "low"

    alts = raw.get("alternative_hooks", [])[:2]
    blocked = raw.get("blocked_hook_angles", [])[:2]

    return {
        "recommended_hook":    rec,
        "alternative_hooks":   alts,
        "blocked_hook_angles": blocked,
    }


def plan(layer7_ctx: dict, section_plan: list[dict]) -> dict:
    prompt      = _build_prompt(layer7_ctx, section_plan)

    async def _run():
        return await _call_llm(layer7_ctx.get("run_id"), prompt, layer7_ctx["packet_type"])

    raw = asyncio.run(_run())
    return _validate_hook_plan(raw)


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

    print(f"[hook_planner] Calling LLM (profile: {get_llm_profile('hook_planner', run_id=run_id)['model']})...")
    hook_plan = plan(ctx, sections)

    rec = hook_plan["recommended_hook"]
    print(f"\nRecommended hook:")
    print(f"  Type      : {rec['hook_type']}")
    print(f"  Direction : {rec['hook_direction']}")
    print(f"  Risk      : {rec['risk_level']}")
    print(f"  Why works : {rec.get('why_it_works','')}")
    print(f"  Claims    : {rec.get('supported_by_claim_ids', [])}")

    print(f"\nAlternative hooks ({len(hook_plan['alternative_hooks'])}):")
    for h in hook_plan["alternative_hooks"]:
        print(f"  [{h['hook_type']}] {h['hook_direction'][:80]}")

    print(f"\nBlocked angles ({len(hook_plan['blocked_hook_angles'])}):")
    for b in hook_plan["blocked_hook_angles"]:
        print(f"  Angle : {b.get('angle','')[:60]}")
        print(f"  Reason: {b.get('reason','')[:80]}")
