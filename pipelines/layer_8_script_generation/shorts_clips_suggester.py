"""
Layer 8 — Module 8: Shorts / Clips Suggester

Rule-based identifier of sections that make strong YouTube Shorts or
standalone clips. No LLM call — purely based on section structure.

Clip rules:
  intro_hook    → always a Short candidate (punchy, creates curiosity)
  story section → Short if ≤60s and has ≥2 required claims (standalone fact burst)
  final_takeaway → Short if ≤60s (quotable conclusion)
  high visual   → any section with ≥2 visual_notes (b-roll clip)

Returns:
    list of {section_id, section_key, clip_type, reason,
             suggested_duration_seconds, script_preview}

Individual test:
    python shorts_clips_suggester.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_8_script_generation.brief_loader             import load as load_brief
from pipelines.layer_8_script_generation.evidence_context_builder import build as build_evidence
from pipelines.layer_8_script_generation.roundup_script_writer    import write as write_roundup

_SCRIPT_PREVIEW_LEN = 120


def suggest(section_scripts: list, layer8_ctx: dict) -> list:
    brief_sections = {s["section_id"]: s for s in layer8_ctx["sections"]}
    suggestions    = []

    for sec_script in section_scripts:
        sid      = sec_script["section_id"]
        key      = sec_script["section_key"]
        role     = sec_script.get("segment_role", key)
        dur      = sec_script["target_seconds"]
        brief_sec = brief_sections.get(sid, {})
        req_count = len(brief_sec.get("required_claim_ids", []))
        vis_count = len(brief_sec.get("visual_notes", []))
        preview   = (sec_script.get("script_text", "")[:_SCRIPT_PREVIEW_LEN] + "…"
                     if len(sec_script.get("script_text", "")) > _SCRIPT_PREVIEW_LEN
                     else sec_script.get("script_text", ""))

        clip_type = None
        reason    = None

        if role in ("intro", "intro_hook"):
            clip_type = "short_hook"
            reason    = "Intro hook creates curiosity — ideal standalone Short."
        elif role in ("lead_story",) and dur <= 90 and req_count >= 2:
            clip_type = "short_story_burst"
            reason    = f"Lead story with {req_count} required claims in {dur}s — quotable fact burst."
        elif key.startswith("story_") and dur <= 60 and req_count >= 2:
            clip_type = "short_story_burst"
            reason    = f"{req_count} required claims in {dur}s — tight enough for a standalone Short."
        elif role in ("takeaway", "final_takeaway") and dur <= 60:
            clip_type = "short_takeaway"
            reason    = f"Final takeaway ({dur}s) — quotable conclusion for a Short."
        elif vis_count >= 2 and dur <= 90:
            clip_type = "broll_clip"
            reason    = f"{vis_count} visual cues in {dur}s — good b-roll package."

        if clip_type:
            suggestions.append({
                "section_id":               sid,
                "section_key":              key,
                "clip_type":                clip_type,
                "reason":                   reason,
                "suggested_duration_seconds": dur,
                "script_preview":           preview,
            })

    return suggestions


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_7/script_writer_brief.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name

    layer7_dir = RUNS_DIR / run_id / "layer_7"
    layer4_dir = RUNS_DIR / run_id / "layer_4"

    ctx             = load_brief(layer7_dir, layer4_dir)
    evidence        = build_evidence(ctx)
    section_scripts = write_roundup(ctx, evidence)
    clips           = suggest(section_scripts, ctx)

    print(f"Clip suggestions  : {len(clips)}")
    print()
    for c in clips:
        print(f"  [{c['clip_type']:20s}] {c['section_key']:20s} ({c['suggested_duration_seconds']}s)")
        print(f"    {c['reason']}")
        print(f"    Preview: {c['script_preview'][:80]}")
        print()
