"""
Layer 6 — Module 7: Packet Context Builder

Creates the compressed packet_context_for_layer7.json — a lean handoff
that includes claim IDs + resolved claim text so Layer 7 can plan sections
without opening any Layer 4 files directly.

Contains: editorial direction, per-section claim summaries, warnings,
and lookup paths for the full packet and source pack.

No raw span text. Every claim links back to its claim_id + source_ref.

Key function:
    build(packet, claim_section_map, verified_claims_by_id,
          brief_ctx, layer6_dir) → context dict

Individual test:
    python packet_context_builder.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_MAX_CLAIM_TEXT_CHARS = 180


def _compact_claim(cid: str, verified_claims_by_id: dict) -> dict:
    claim = verified_claims_by_id.get(cid, {})
    text  = claim.get("claim_text", "")
    if len(text) > _MAX_CLAIM_TEXT_CHARS:
        text = text[:_MAX_CLAIM_TEXT_CHARS].rstrip() + "…"
    return {
        "claim_id":   cid,
        "claim_text": text,
        "confidence": claim.get("confidence", ""),
        "source_ref": (claim.get("source_span_ids") or [""])[0],
    }


def build(
    packet:                dict,
    claim_section_map:     list,
    verified_claims_by_id: dict,
    brief_ctx:             dict,
    layer6_dir:            Path,
) -> dict:
    content_dir  = brief_ctx["content_direction"]
    packet_type  = packet.get("packet_type", "")
    dnu_ids      = brief_ctx["do_not_use_claim_ids"]
    cautious_ids = brief_ctx["cautious_claim_ids"]

    # Compact sections: required claims with text, optional just IDs
    compact_sections = []
    for sec in claim_section_map:
        required_claims = [
            _compact_claim(cid, verified_claims_by_id)
            for cid in sec["required_claim_ids"]
        ]
        compact_sections.append({
            "section_key":     sec["section_key"],
            "story_id":        sec.get("story_id", ""),
            "segment_role":    sec.get("segment_role", ""),
            "target_seconds":  sec.get("target_seconds", 0),
            "goal":            sec["section_goal"],
            "required_claims": required_claims,
            "optional_claim_ids": sec["optional_claim_ids"],
            "cautious_claim_ids": sec["cautious_claim_ids"],
            "language_guidance":  sec.get("language_guidance", []),
        })

    # Warnings: DNU blocked phrases + cautious reminders
    warnings = []
    if dnu_ids:
        warnings.append(
            f"Do NOT use: {', '.join(sorted(dnu_ids)[:5])} "
            f"({'and more' if len(dnu_ids) > 5 else ''})."
        )
    if cautious_ids:
        warnings.append(
            f"{len(cautious_ids)} cautious claim(s) require qualifying language ('may', 'suggests')."
        )

    # Episode/editorial summary at top
    if packet_type == "roundup":
        editorial = {
            "episode_theme":  content_dir.get("episode_theme", ""),
            "viewer_promise": content_dir.get("viewer_promise", ""),
            "tone_guidance":  content_dir.get("tone_guidance", ""),
            "opening_hook":   content_dir.get("opening_hook_idea", ""),
        }
    else:
        editorial = {
            "central_viewer_question": content_dir.get("central_viewer_question",
                                        content_dir.get("episode_theme", "")),
            "viewer_promise":          content_dir.get("viewer_promise", ""),
            "thesis_candidate":        content_dir.get("suggested_thesis",
                                        content_dir.get("working_angle", "")),
            "tone_guidance":           content_dir.get("tone_guidance", ""),
        }

    return {
        "packet_type":       packet_type,
        "selected_format":   packet.get("selected_format", ""),
        "selected_video_id": brief_ctx.get("selected_video_id", ""),
        "editorial":         editorial,
        "sections":          compact_sections,
        "warnings":          warnings,
        "lookup_paths": {
            "full_research_packet": str(layer6_dir / "research_packet.json"),
            "source_pack":          str(layer6_dir / "source_pack.json"),
            "claim_section_map":    str(layer6_dir / "claim_section_map.json"),
            "evidence_boundary":    str(layer6_dir / "evidence_boundary_report.json"),
        },
    }


if __name__ == "__main__":
    from pipelines.layer_6_research_packets.brief_loader            import load as load_brief
    from pipelines.layer_6_research_packets.roundup_packet_builder   import build as build_roundup
    from pipelines.layer_6_research_packets.claim_section_mapper     import map_claims

    run_id     = sorted(RUNS_DIR.glob("*/layer_5/selected_video_brief.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)[0].parents[1].name
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    layer5_dir = RUNS_DIR / run_id / "layer_5"
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    brief_ctx = load_brief(layer5_dir)

    with open(layer4_dir / "story_fact_sheets.json") as f:
        raw = json.load(f)
    fact_sheets_by_id = {fs["story_id"]: fs for fs in raw["story_fact_sheets"]}

    claims_by_id = {}
    with open(layer4_dir / "verified_claims.jsonl") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                claims_by_id[c["claim_id"]] = c

    packet    = build_roundup(brief_ctx, fact_sheets_by_id, claims_by_id)
    csm       = map_claims(packet)
    ctx       = build(packet, csm, claims_by_id, brief_ctx, layer6_dir)

    print(f"Packet type   : {ctx['packet_type']}")
    print(f"Sections      : {len(ctx['sections'])}")
    print(f"Warnings      : {len(ctx['warnings'])}")
    print()
    print("Editorial direction:")
    for k, v in ctx["editorial"].items():
        print(f"  {k}: {str(v)[:80]}")
    print()
    print("First section:")
    sec = ctx["sections"][0]
    print(f"  {sec['section_key']} | {sec['segment_role']} | {sec['target_seconds']}s")
    print(f"  Goal: {sec['goal'][:70]}")
    for rc in sec["required_claims"]:
        print(f"  CLAIM [{rc['confidence']}]: {rc['claim_text'][:80]}")
    print()
    print("Warnings:", ctx["warnings"])
    print("Lookup paths:")
    for k, v in ctx["lookup_paths"].items():
        print(f"  {k}: {v}")
