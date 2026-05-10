"""
Layer 6 — Module 6: Claim-to-Section Mapper

Produces a flat list mapping each packet section to its required, optional,
and cautious claim IDs. Layer 7 reads this to plan which claims belong where.

For roundup: one entry per story segment.
For deep_dive: one entry per research section.

Key function:
    map_claims(packet) → list of section-claim mapping dicts

Individual test:
    python claim_section_mapper.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

# For roundup, at most this many claims are 'required' per segment;
# the rest are 'optional' (available but not mandatory)
_ROUNDUP_REQUIRED_CLAIMS = 3


def map_claims(packet: dict) -> list:
    packet_type = packet.get("packet_type", "")

    if packet_type == "roundup":
        return _map_roundup(packet)
    if packet_type == "deep_dive":
        return _map_deep_dive(packet)
    raise ValueError(f"Unsupported packet_type: {packet_type}")


def _map_roundup(packet: dict) -> list:
    result = []
    for seg in packet.get("segments", []):
        story_id    = seg["story_id"]
        safe_ids    = seg.get("safe_claim_ids", [])
        cautious    = seg.get("cautious_claim_ids", [])
        dnu         = seg.get("do_not_use_claim_ids", [])

        required = safe_ids[:_ROUNDUP_REQUIRED_CLAIMS]
        optional = safe_ids[_ROUNDUP_REQUIRED_CLAIMS:]

        notes = []
        if cautious:
            notes.append(f"Cautious claims require qualifying language: {', '.join(cautious[:3])}")

        result.append({
            "section_key":        f"segment_{seg['segment_order']}",
            "story_id":           story_id,
            "segment_role":       seg.get("segment_role", ""),
            "target_seconds":     seg.get("target_duration_seconds", 0),
            "section_goal":       f"Cover: {seg.get('story_title', story_id)}",
            "required_claim_ids": required,
            "optional_claim_ids": optional,
            "cautious_claim_ids": cautious,
            "blocked_claim_ids":  dnu,
            "language_guidance":  notes,
        })
    return result


def _map_deep_dive(packet: dict) -> list:
    result = []
    for sec in packet.get("research_sections", []):
        safe_ids = sec.get("safe_claim_ids", [])
        cautious = sec.get("cautious_claim_ids", [])
        notes    = sec.get("notes_for_layer7", [])

        result.append({
            "section_key":        sec["section_key"],
            "story_id":           packet.get("story", {}).get("story_id", ""),
            "section_goal":       sec.get("section_goal", ""),
            "required_claim_ids": safe_ids[:3],
            "optional_claim_ids": safe_ids[3:],
            "cautious_claim_ids": cautious,
            "blocked_claim_ids":  [],
            "language_guidance":  notes if isinstance(notes, list) else [notes],
        })
    return result


if __name__ == "__main__":
    from pipelines.layer_6_research_packets.brief_loader           import load as load_brief
    from pipelines.layer_6_research_packets.roundup_packet_builder  import build as build_roundup

    run_id     = sorted(RUNS_DIR.glob("*/layer_5/selected_video_brief.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)[0].parents[1].name
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    layer5_dir = RUNS_DIR / run_id / "layer_5"

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

    packet  = build_roundup(brief_ctx, fact_sheets_by_id, claims_by_id)
    mapping = map_claims(packet)

    print(f"Sections mapped : {len(mapping)}")
    print()
    for m in mapping:
        print(f"  {m['section_key']:12s} | {m['segment_role']:15s} | {m['target_seconds']}s "
              f"| required={len(m['required_claim_ids'])} optional={len(m['optional_claim_ids'])} cautious={len(m['cautious_claim_ids'])}")
        print(f"     Goal   : {m['section_goal'][:70]}")
        print(f"     Req IDs: {m['required_claim_ids']}")
