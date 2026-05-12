"""
Layer 8 — Module 4: Deep Dive Script Writer

Writes script sections for deep_dive format videos. One async LLM call per
section, all dispatched concurrently via asyncio.gather().

Deep dive sections explore one topic in analytical depth:
  hook → what_happened → why_it_matters → technical_context →
  limitations → background → final_takeaway → cta

LLM returns JSON per section:
    {"script_text": "...", "used_claim_ids": ["claim_...", ...]}

Returns:
    list of section_script dicts (same structure as roundup_script_writer)

Individual test:
    python deep_dive_script_writer.py  (requires a deep_dive run)
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_8_script_generation.brief_loader             import load as load_brief
from pipelines.layer_8_script_generation.evidence_context_builder import build as build_evidence

_MODEL = "gpt-4o-mini"
_WPM   = 130

_ROLE_TONE = {
    "hook":              "Pose the central viewer question directly. Create curiosity. No facts yet.",
    "what_happened":     "State the announcement factually and precisely. Lead with the most striking verified fact.",
    "why_it_matters":    "Explain the practical developer or technical relevance. Be specific and concrete.",
    "technical_context": "Describe the technical shift clearly without overhyping. Reference specific mechanisms.",
    "limitations":       "Be honest about what is not yet proven, what is early-stage, what could go wrong.",
    "background":        "Provide context that helps viewers understand the announcement. Brief and relevant.",
    "final_takeaway":    "Give a balanced, evidence-grounded conclusion. Acknowledge uncertainty where it exists.",
    "cta":               "Invite viewers to share their perspective. Keep it short and genuine.",
}

_SYSTEM_PROMPT = """\
You are a script writer for "AI Signal Brief" — a YouTube channel that publishes
deep-dive analysis of AI announcements.

Style rules for deep dives:
- Analytical, precise, structured. More thorough than a roundup.
- Write in natural spoken language as if being read aloud. No bullet points, no headers.
- Every factual claim must be backed by a claim ID from the provided list.
- Do NOT introduce facts not in the provided claim list.
- Do NOT use the blocked phrases listed in the prompt.
- Cautious claims must use qualifying language: "may", "could", "suggests", "appears to".
- Each section has a specific analytical role — honour the role tone provided.

Output format — return ONLY valid JSON:
{
  "script_text": "<script for this section only, plain spoken prose>",
  "used_claim_ids": ["claim_id_1", "claim_id_2"]
}
"""


def _build_create_kwargs(model: str, **kwargs) -> dict:
    kw = {"model": model, **kwargs}
    if "nano" in model.lower():
        kw.pop("temperature", None)
    return kw


def _make_openai_client():
    import openai
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_A_C_C")
    return openai.AsyncOpenAI(api_key=api_key)


def _word_budget(target_seconds: int) -> int:
    return max(20, int(target_seconds / 60 * _WPM))


def _format_claims(claims: list) -> str:
    if not claims:
        return "  (none)"
    lines = []
    for c in claims:
        url = f" | source: {c['source_url']}" if c["source_url"] else ""
        lines.append(f"  [{c['claim_id']}] {c['claim_text']}{url}")
    return "\n".join(lines)


def _build_section_prompt(sec: dict, evidence: dict, blocked_phrases: list) -> str:
    ev      = evidence[sec["section_id"]]
    wbgt    = _word_budget(sec["target_duration_seconds"])
    role    = sec.get("segment_role", sec["section_key"])
    tone    = _ROLE_TONE.get(role, f"Cover {role} analytically.")

    parts = [
        f"SECTION: {sec['section_key']}",
        f"ROLE: {role}",
        f"ROLE TONE: {tone}",
        f"GOAL: {sec['section_goal']}",
        f"WORD BUDGET: ~{wbgt} words ({sec['target_duration_seconds']}s at {_WPM} wpm)",
        "",
        "REQUIRED CLAIMS (must reference all):",
        _format_claims(ev["required"]),
        "",
        "OPTIONAL CLAIMS (use 1-2 if they deepen the analysis):",
        _format_claims(ev["optional"]),
        "",
    ]

    if ev["cautious"]:
        parts += [
            "CAUTIOUS CLAIMS (use qualifying language: may/could/suggests):",
            _format_claims(ev["cautious"]),
            "",
        ]

    if sec.get("writer_instructions"):
        parts.append("WRITER INSTRUCTIONS:")
        for instr in sec["writer_instructions"]:
            parts.append(f"  - {instr}")
        parts.append("")

    parts += [
        f"BLOCKED PHRASES (never use): {', '.join(blocked_phrases)}",
        "",
        "Return JSON only. Script text in plain spoken analytical prose. No bullets, no headers.",
    ]

    return "\n".join(parts)


async def _write_section(
    client:          object,
    sec:             dict,
    evidence:        dict,
    blocked_phrases: list,
) -> dict:
    prompt = _build_section_prompt(sec, evidence, blocked_phrases)
    kwargs = _build_create_kwargs(
        _MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.35,
        response_format={"type": "json_object"},
    )
    resp = await client.chat.completions.create(**kwargs)
    raw  = resp.choices[0].message.content.strip()
    data = json.loads(raw)

    script_text    = data.get("script_text", "").strip()
    used_claim_ids = data.get("used_claim_ids", [])
    word_count     = len(script_text.split())

    return {
        "section_id":        sec["section_id"],
        "section_key":       sec["section_key"],
        "segment_role":      sec.get("segment_role", sec["section_key"]),
        "target_seconds":    sec["target_duration_seconds"],
        "script_text":       script_text,
        "word_count":        word_count,
        "estimated_seconds": round(word_count / _WPM * 60),
        "used_claim_ids":    used_claim_ids,
    }


async def _write_all(layer8_ctx: dict, evidence: dict) -> list:
    client          = _make_openai_client()
    blocked_phrases = layer8_ctx["evidence_rules"].get("blocked_phrases", [])

    tasks = [
        _write_section(client, sec, evidence, blocked_phrases)
        for sec in layer8_ctx["sections"]
    ]
    return await asyncio.gather(*tasks)


def write(layer8_ctx: dict, evidence: dict) -> list:
    results = asyncio.run(_write_all(layer8_ctx, evidence))
    order   = {sec["section_id"]: i for i, sec in enumerate(layer8_ctx["sections"])}
    return sorted(results, key=lambda r: order.get(r["section_id"], 99))


if __name__ == "__main__":
    # Find a deep_dive run; fall back to latest run for structure check
    candidates = sorted(
        RUNS_DIR.glob("*/layer_7/script_writer_brief.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    run_id = None
    for c in candidates:
        rid = c.parents[1].name
        import json as _json
        with open(c) as f:
            brief = _json.load(f)
        if brief.get("video_identity", {}).get("selected_format") == "deep_dive":
            run_id = rid
            break

    if not run_id:
        print("No deep_dive run found. Run a deep_dive pipeline first.")
        print("Showing module structure is intact (no LLM call).")
        print("Functions: write(layer8_ctx, evidence) -> list[dict]")
        sys.exit(0)

    layer7_dir = RUNS_DIR / run_id / "layer_7"
    layer4_dir = RUNS_DIR / run_id / "layer_4"

    ctx      = load_brief(layer7_dir, layer4_dir)
    evidence = build_evidence(ctx)

    print(f"[deep_dive_script_writer] Run: {run_id}")
    print("[deep_dive_script_writer] Dispatching LLM calls for all sections...")
    section_scripts = write(ctx, evidence)

    total_words = sum(s["word_count"] for s in section_scripts)
    total_secs  = sum(s["estimated_seconds"] for s in section_scripts)
    print(f"\nTotal words       : {total_words}")
    print(f"Estimated duration: {total_secs}s ({total_secs/60:.1f} min)")
    print()
    for s in section_scripts:
        print(f"  {s['section_id']} | {s['section_key']:20s} | "
              f"{s['word_count']:4d}w | ~{s['estimated_seconds']}s | "
              f"claims_used={len(s['used_claim_ids'])}")
