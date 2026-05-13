"""
Layer 8 — Module 3: Roundup Script Writer

Writes one section of script per LLM call, all sections dispatched concurrently
via asyncio.gather(). The writer receives each section's evidence bundle (required
claim texts + source URLs), word budget, writer instructions, and visual notes.

LLM returns JSON per section:
    {"narration_text": "...", "used_claim_ids": ["claim_...", ...], "analysis_sentences": []}

Returns:
    list of section_script dicts:
        {section_id, section_key, narration_text, visual_notes, word_count,
         estimated_seconds, used_claim_ids, analysis_sentences}

Individual test:
    python roundup_script_writer.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.runtime_manifest import get_llm_profile
from pipelines.layer_8_script_generation.brief_loader          import load as load_brief
from pipelines.layer_8_script_generation.evidence_context_builder import build as build_evidence
from llm.async_llm_runtime import execute_chat_request
from llm.prompt_loader import load_prompt_bundle

_WPM   = 130
_ANALYSIS_ALLOWED_SECTIONS = {"final_takeaway", "outro"}

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


def _analysis_allowed(sec: dict) -> bool:
    key = sec.get("section_key", "")
    role = sec.get("segment_role", key)
    return key in _ANALYSIS_ALLOWED_SECTIONS or role in _ANALYSIS_ALLOWED_SECTIONS


def _build_section_prompt(sec: dict, evidence: dict, blocked_phrases: list,
                          hook_instruction: dict = None, prompt_bundle: dict | None = None) -> str:
    ev    = evidence[sec["section_id"]]
    wbgt  = _word_budget(sec["target_duration_seconds"])
    analysis_allowed = _analysis_allowed(sec)
    parts = [
        f"SECTION: {sec['section_key']}",
        f"GOAL: {sec['section_goal']}",
        f"WORD BUDGET: ~{wbgt} words ({sec['target_duration_seconds']}s at {_WPM} wpm)",
        f"SEGMENT ROLE: {sec.get('segment_role', sec['section_key'])}",
        f"ANALYSIS ALLOWED: {'yes' if analysis_allowed else 'no'}",
        "",
    ]

    if hook_instruction and sec["section_key"] == "intro_hook":
        parts += [
            "HOOK DIRECTION:",
            f"  Type: {hook_instruction.get('hook_type', '')}",
            f"  Direction: {hook_instruction.get('direction', '')}",
            f"  Why it works: {hook_instruction.get('why_it_works', '')}",
            "",
        ]

    parts += [
        "REQUIRED CLAIMS (must reference all):",
        _format_claims(ev["required"]),
        "",
        "OPTIONAL CLAIMS (use 1-2 if they strengthen the section):",
        _format_claims(ev["optional"]),
        "",
    ]

    if ev["cautious"]:
        parts += [
            "CAUTIOUS CLAIMS (use qualifying language: may/could/suggests):",
            _format_claims(ev["cautious"]),
            "",
        ]

    if sec.get("visual_notes"):
        parts.append("VISUAL NOTES (editor-facing only; DO NOT read these aloud):")
        for v in sec["visual_notes"]:
            txt = f" | on-screen: '{v['on_screen_text']}'" if v.get("on_screen_text") else ""
            parts.append(f"  {v['visual_type']}: {v['visual_goal']}{txt}")
        parts.append("")

    if sec.get("writer_instructions"):
        parts.append("WRITER INSTRUCTIONS:")
        for instr in sec["writer_instructions"]:
            parts.append(f"  - {instr}")
        parts.append("")

    parts += [
        f"BLOCKED PHRASES (never use): {', '.join(blocked_phrases)}",
        "",
        (prompt_bundle or {}).get("user_preamble", "").strip(),
    ]

    return "\n".join(part for part in parts if part != "")


async def _write_section(
    run_id:         str | None,
    sec:            dict,
    evidence:       dict,
    blocked_phrases: list,
    hook_instruction: dict,
) -> dict:
    prompt_bundle = load_prompt_bundle("roundup_script_writer", run_id=run_id)
    prompt = _build_section_prompt(sec, evidence, blocked_phrases, hook_instruction, prompt_bundle)
    data = await execute_chat_request(
        module_name="roundup_script_writer",
        run_id=run_id,
        messages=[
            {"role": "system", "content": prompt_bundle["system"]},
            {"role": "user",   "content": prompt},
        ],
        request_name=sec["section_key"],
        metadata={
            "section_id": sec["section_id"],
            "section_key": sec["section_key"],
            "segment_role": sec.get("segment_role", sec["section_key"]),
            "target_seconds": sec["target_duration_seconds"],
        },
        parse_json=True,
    )

    narration_text = (data.get("narration_text") or data.get("script_text") or "").strip()
    used_claim_ids = data.get("used_claim_ids", [])
    analysis_sentences = data.get("analysis_sentences", [])
    if not _analysis_allowed(sec):
        analysis_sentences = []
    word_count     = len(narration_text.split())

    return {
        "section_id":        sec["section_id"],
        "section_key":       sec["section_key"],
        "segment_role":      sec.get("segment_role", sec["section_key"]),
        "target_seconds":    sec["target_duration_seconds"],
        "narration_text":    narration_text,
        "visual_notes":      sec.get("visual_notes", []),
        "word_count":        word_count,
        "estimated_seconds": round(word_count / _WPM * 60),
        "used_claim_ids":    used_claim_ids,
        "analysis_sentences": [s.strip() for s in analysis_sentences if isinstance(s, str) and s.strip()],
    }


async def _write_all(layer8_ctx: dict, evidence: dict) -> list:
    blocked_phrases = layer8_ctx["evidence_rules"].get("blocked_phrases", [])
    hook_instruction = layer8_ctx.get("hook_instruction", {})

    tasks = [
        _write_section(
            layer8_ctx.get("run_id"),
            sec,
            evidence,
            blocked_phrases,
            hook_instruction,
        )
        for sec in layer8_ctx["sections"]
    ]
    return await asyncio.gather(*tasks)


def write(layer8_ctx: dict, evidence: dict) -> list:
    results = asyncio.run(_write_all(layer8_ctx, evidence))
    # Restore original section order (gather preserves order, but confirm)
    order = {sec["section_id"]: i for i, sec in enumerate(layer8_ctx["sections"])}
    return sorted(results, key=lambda r: order.get(r["section_id"], 99))


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_7/script_writer_brief.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name

    layer7_dir = RUNS_DIR / run_id / "layer_7"
    layer4_dir = RUNS_DIR / run_id / "layer_4"

    ctx      = load_brief(layer7_dir, layer4_dir)
    evidence = build_evidence(ctx)

    print("[roundup_script_writer] Dispatching LLM calls for all sections...")
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
    print()
    print("=== intro_hook script ===")
    print(section_scripts[0]["narration_text"])
    print()
    print("=== story_1 script ===")
    print(section_scripts[1]["narration_text"])
