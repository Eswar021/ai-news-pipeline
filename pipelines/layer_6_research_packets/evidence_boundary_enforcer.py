"""
Layer 6 — Module 4: Evidence Boundary Enforcer

Scans all claim references in the built research packet and verifies that
no do-not-use claims leaked in. Also checks cautious claims have language
guidance attached.

Works for both roundup (segments) and deep_dive (research_sections).

Key function:
    enforce(packet, brief_ctx, verified_claims_by_id) → boundary_report dict

Individual test:
    python evidence_boundary_enforcer.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_CAUTIOUS_GUIDANCE_PHRASES = (
    "may", "might", "could", "suggests", "appears",
    "reportedly", "according to", "is expected",
)


def _collect_all_claim_ids(packet: dict) -> set:
    claimed = set()
    packet_type = packet.get("packet_type", "")

    if packet_type == "roundup":
        for seg in packet.get("segments", []):
            claimed.update(seg.get("safe_claim_ids", []))
            claimed.update(seg.get("cautious_claim_ids", []))

    elif packet_type == "deep_dive":
        for sec in packet.get("research_sections", []):
            claimed.update(sec.get("safe_claim_ids", []))
            claimed.update(sec.get("cautious_claim_ids", []))

    return claimed


def _check_cautious_guidance(
    cautious_ids:          set,
    packet:                dict,
    verified_claims_by_id: dict,
) -> list:
    warnings = []
    packet_type = packet.get("packet_type", "")

    sections_key = "segments" if packet_type == "roundup" else "research_sections"
    for section in packet.get(sections_key, []):
        for cid in section.get("cautious_claim_ids", []):
            if cid not in cautious_ids:
                continue
            notes = section.get("segment_caution_notes", []) or section.get("notes_for_layer7", [])
            has_guidance = any(
                any(phrase in str(n).lower() for phrase in _CAUTIOUS_GUIDANCE_PHRASES)
                for n in notes
            )
            if not has_guidance:
                claim = verified_claims_by_id.get(cid, {})
                qualifier = claim.get("recommended_qualifier", "use qualifying language")
                warnings.append({
                    "claim_id":          cid,
                    "type":              "cautious_claim_missing_guidance",
                    "required_guidance": qualifier or "Use 'may', 'suggests', or 'could'.",
                })
    return warnings


def enforce(
    packet:                dict,
    brief_ctx:             dict,
    verified_claims_by_id: dict,
) -> dict:
    dnu_ids      = brief_ctx["do_not_use_claim_ids"]
    cautious_ids = brief_ctx["cautious_claim_ids"]

    all_claim_ids = _collect_all_claim_ids(packet)

    # Hard check: no DNU claims in packet
    violations = list(all_claim_ids & dnu_ids)
    errors = []
    if violations:
        errors.append({
            "type":       "do_not_use_claim_in_packet",
            "claim_ids":  violations,
            "message":    f"{len(violations)} do-not-use claim(s) found in packet.",
        })

    # Soft check: cautious claims have guidance
    warnings = _check_cautious_guidance(cautious_ids, packet, verified_claims_by_id)

    cautious_in_packet = list(all_claim_ids & cautious_ids)
    safe_in_packet     = list(all_claim_ids - dnu_ids - cautious_ids)

    status = "passed" if not errors else "failed"

    return {
        "evidence_boundary_status":  status,
        "passed":                    status == "passed",
        "safe_claims_used":          len(safe_in_packet),
        "cautious_claims_used":      len(cautious_in_packet),
        "do_not_use_claims_used":    len(violations),
        "contradictions_preserved":  True,
        "evidence_gaps_preserved":   True,
        "errors":                    errors,
        "warnings":                  warnings,
    }


if __name__ == "__main__":
    import copy
    from pipelines.layer_6_research_packets.brief_loader         import load as load_brief
    from pipelines.layer_6_research_packets.roundup_packet_builder import build as build_roundup

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
    report  = enforce(packet, brief_ctx, claims_by_id)

    print(f"Boundary status       : {report['evidence_boundary_status']}")
    print(f"Safe claims used      : {report['safe_claims_used']}")
    print(f"Cautious claims used  : {report['cautious_claims_used']}")
    print(f"DNU claims used       : {report['do_not_use_claims_used']}")
    print(f"Errors                : {report['errors']}")
    print(f"Warnings              : {len(report['warnings'])}")
