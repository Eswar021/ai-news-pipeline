"""
Layer 5 — Module 4: Viewer Value Analyzer (LLM)

Determines what viewers gain from watching a video about each story.
One LLM call per story, all stories run concurrently via asyncio.gather().

Generates editorial language that cannot be produced by rule-based logic:
  primary_viewer_question — the central question the video answers
  viewer_promise          — what viewers understand by the end
  value_types             — which value categories apply
  viewer_value_score      — 0–100

Value types:
  understand_what_happened, understand_why_it_matters, decide_whether_to_use_tool,
  avoid_hype, learn_technical_context, track_industry_shift, assess_business_impact

Key function:
    analyze_all(candidates) → list of viewer_value dicts

Usage:
    python viewer_value_analyzer.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from config.llm_config import get_profile

MAX_CONCURRENT   = 10
MAX_FACTS_IN_PROMPT = 5

_VALID_VALUE_TYPES = {
    "understand_what_happened",
    "understand_why_it_matters",
    "decide_whether_to_use_tool",
    "avoid_hype",
    "learn_technical_context",
    "track_industry_shift",
    "assess_business_impact",
}

_SYSTEM_PROMPT = """\
You are an editorial strategist for "AI Signal Brief," a YouTube channel explaining AI news
to software developers and tech professionals. The channel is evidence-first, practical, and low-hype.

Given a story with verified facts, generate the viewer value package that tells us why
this story is worth covering and what viewers will actually get from watching.

Rules:
1. primary_viewer_question must be a real question a developer or tech professional would ask.
2. viewer_promise must be specific and concrete — what they will KNOW or be able to DO after watching.
3. Never use hype language. Stay grounded in what the facts actually show.
4. value_types: pick 2–4 from the allowed list only.
5. viewer_value_score: 0–100 based on how much practical/intellectual value the story delivers.
   70+ = worth covering, 50–69 = borderline, <50 = low value for this audience.

Allowed value_types:
  understand_what_happened, understand_why_it_matters, decide_whether_to_use_tool,
  avoid_hype, learn_technical_context, track_industry_shift, assess_business_impact

Return only valid JSON:
{"primary_viewer_question": "...", "viewer_promise": "...", "value_types": ["..."], "viewer_value_score": 0}"""


def _facts_to_bullets(safe_facts: list[dict], limit: int) -> str:
    lines = []
    for f in safe_facts[:limit]:
        lines.append(f"- {f['claim_text']}")
    return "\n".join(lines) if lines else "(no verified facts available)"


def _build_create_kwargs(model: str, temperature: float, messages: list) -> dict:
    kwargs: dict = {
        "model":           model,
        "response_format": {"type": "json_object"},
        "messages":        messages,
    }
    if "nano" not in model:
        kwargs["temperature"] = temperature
    return kwargs


async def _call_llm(client, model: str, temperature: float,
                    candidate: dict, semaphore) -> dict:
    story_title = candidate["story_title"]
    story_type  = candidate.get("story_type", "unknown")
    topics      = ", ".join(candidate.get("topics", [])) or "general AI"
    facts_text  = _facts_to_bullets(candidate.get("safe_facts", []), MAX_FACTS_IN_PROMPT)

    user_msg = (
        f"Channel: AI Signal Brief (audience: AI developers and tech professionals)\n\n"
        f"Story: {story_title}\n"
        f"Type: {story_type}\n"
        f"Topics: {topics}\n\n"
        f"Verified facts:\n{facts_text}\n\n"
        "Generate the viewer value package for this story."
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]

    async with semaphore:
        resp = await client.chat.completions.create(
            **_build_create_kwargs(model, temperature, messages)
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        return data


def _validate_result(raw: dict, story_id: str) -> dict:
    question = (raw.get("primary_viewer_question") or "").strip()
    promise  = (raw.get("viewer_promise") or "").strip()
    vtypes   = [vt for vt in (raw.get("value_types") or []) if vt in _VALID_VALUE_TYPES]
    score    = int(raw.get("viewer_value_score") or 65)
    score    = max(0, min(100, score))

    if not question:
        question = "What does this story mean for AI developers?"
    if not promise:
        promise = "Viewers will understand the practical implications of this development."
    if not vtypes:
        vtypes = ["understand_why_it_matters"]

    return {
        "story_id":               story_id,
        "primary_viewer_question": question,
        "viewer_promise":          promise,
        "value_types":             vtypes,
        "viewer_value_score":      score,
    }


def _make_openai_client():
    import openai
    from dotenv import load_dotenv
    import os
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_A_C_C")
    return openai.AsyncOpenAI(api_key=api_key)


def analyze_all(candidates: list[dict]) -> list[dict]:
    """
    Analyze viewer value for all candidates concurrently.
    Returns list of viewer_value dicts in same order as candidates.
    """
    profile     = get_profile("viewer_value_analyzer")
    client      = _make_openai_client()
    model       = profile["model"]
    temperature = profile["temperature"]
    semaphore   = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run():
        tasks = [
            _call_llm(client, model, temperature, cand, semaphore)
            for cand in candidates
        ]
        raw_results = await asyncio.gather(*tasks)
        return [
            _validate_result(raw, cand["story_id"])
            for raw, cand in zip(raw_results, candidates)
        ]

    return asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    parser.add_argument("--story-index", type=int, default=None,
                        help="Test a single story (0-based index)")
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_4" / "story_fact_sheets.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_5_editorial_intelligence.editorial_candidate_loader import load
    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result     = load(run_id, layer3_dir, layer4_dir)
    candidates = result["editorial_candidates"]

    if args.story_index is not None:
        candidates = [candidates[args.story_index]]

    print(f"\nViewer Value Analyzer — {run_id}")
    print(f"  Model  : {get_profile('viewer_value_analyzer')['model']}")
    print(f"  Stories: {len(candidates)}")
    print("  Analyzing...\n")

    vv_results = analyze_all(candidates)
    for cand, vv in zip(candidates, vv_results):
        print(f"  [{vv['viewer_value_score']:3d}] {cand['story_title'][:50]:50s}")
        print(f"         Q: {vv['primary_viewer_question'][:80]}")
        print(f"         P: {vv['viewer_promise'][:80]}")
        print(f"         types: {vv['value_types']}")
        print()
