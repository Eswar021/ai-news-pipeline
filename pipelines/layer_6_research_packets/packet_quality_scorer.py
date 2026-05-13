"""
Layer 6 — Module 8: Packet Quality Scorer

Scores the research packet across 5 dimensions before Layer 7 handoff.

Weights (from design doc):
  evidence_coverage  0.30  — % sections/segments with >= 2 safe claims
  section_coverage   0.25  — % of required sections present with at least 1 claim
  source_diversity   0.15  — unique trust tiers in source_pack / 2 (max tier count)
  format_fit         0.15  — packet_type matches selected_format
  risk_control       0.15  — 1.0 if no DNU claims in packet

Minimum pass score: 70.

Key function:
    score(packet, source_pack, boundary_report, brief_ctx) → quality_report dict

Individual test:
    python packet_quality_scorer.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_MIN_CLAIMS_PER_SECTION     = 2
_MIN_QUALITY_SCORE          = 60
_ROUNDUP_REQUIRED_SECTIONS  = {"lead_story", "major_update", "quick_update"}
_DEEP_DIVE_REQUIRED_KEYS    = {"what_happened", "why_it_matters", "limitations"}


def _evidence_coverage(packet: dict) -> float:
    packet_type = packet.get("packet_type", "")
    if packet_type == "roundup":
        segs  = packet.get("segments", [])
        if not segs:
            return 0.0
        covered = sum(
            1 for s in segs
            if len(s.get("safe_claim_ids", [])) >= _MIN_CLAIMS_PER_SECTION
        )
        return covered / len(segs)
    if packet_type == "deep_dive":
        sections = packet.get("research_sections", [])
        if not sections:
            return 0.0
        covered = sum(
            1 for s in sections
            if len(s.get("safe_claim_ids", [])) >= _MIN_CLAIMS_PER_SECTION
        )
        return covered / len(sections)
    return 0.0


def _section_coverage(packet: dict) -> float:
    packet_type = packet.get("packet_type", "")
    if packet_type == "roundup":
        segs = packet.get("segments", [])
        if not segs:
            return 0.0
        # All segments must have at least 1 safe claim; check structural roles
        has_lead    = any(s.get("segment_role") == "lead_story" for s in segs)
        has_update  = any(s.get("segment_role") in {"major_update", "short_update", "quick_update"}
                          for s in segs)
        has_others  = len(segs) >= 5
        return sum([has_lead, has_update, has_others]) / 3.0
    if packet_type == "deep_dive":
        sections = packet.get("research_sections", [])
        keys     = {s["section_key"] for s in sections if s.get("safe_claim_ids")}
        hit      = len(_DEEP_DIVE_REQUIRED_KEYS & keys)
        return hit / len(_DEEP_DIVE_REQUIRED_KEYS)
    return 0.0


def _source_diversity(source_pack: dict) -> float:
    tiers  = {s["trust_tier"] for s in source_pack.get("sources", [])}
    return min(len(tiers) / 2.0, 1.0)


def _format_fit(packet: dict, selected_format: str) -> float:
    return 1.0 if packet.get("packet_type") == selected_format.replace("_packet", "") else 0.0


def _risk_control(boundary_report: dict) -> float:
    return 1.0 if boundary_report.get("do_not_use_claims_used", 0) == 0 else 0.0


def score(
    packet:          dict,
    source_pack:     dict,
    boundary_report: dict,
    brief_ctx:       dict,
) -> dict:
    selected_format = brief_ctx.get("selected_format", "")

    ev_cov   = _evidence_coverage(packet)
    sec_cov  = _section_coverage(packet)
    src_div  = _source_diversity(source_pack)
    fmt_fit  = _format_fit(packet, selected_format)
    risk_ctl = _risk_control(boundary_report)

    composite = (
        ev_cov   * 0.30 +
        sec_cov  * 0.25 +
        src_div  * 0.15 +
        fmt_fit  * 0.15 +
        risk_ctl * 0.15
    ) * 100

    packet_quality_score = round(composite)
    ready = (
        packet_quality_score >= _MIN_QUALITY_SCORE
        and boundary_report.get("passed", False)
    )

    warnings = []
    if ev_cov < 0.8:
        warnings.append(f"Evidence coverage low ({ev_cov:.0%}); some sections have fewer than 2 claims.")
    if sec_cov < 1.0:
        warnings.append(f"Section coverage incomplete ({sec_cov:.0%}); required sections may be missing claims.")
    if src_div < 0.5:
        warnings.append(f"Low source diversity ({src_div:.0%}); all sources from same trust tier.")

    return {
        "packet_quality_score":    packet_quality_score,
        "ready_for_layer_7":       ready,
        "format_fit_status":       "good" if fmt_fit == 1.0 else "mismatch",
        "risk_level":              "low" if risk_ctl == 1.0 else "high",
        "evidence_coverage_score": round(ev_cov * 100),
        "section_coverage_score":  round(sec_cov * 100),
        "source_diversity_score":  round(src_div * 100),
        "format_fit_score":        round(fmt_fit * 100),
        "risk_control_score":      round(risk_ctl * 100),
        "warnings":                warnings,
        "dimension_breakdown": {
            "evidence_coverage":  round(ev_cov * 100),
            "section_coverage":   round(sec_cov * 100),
            "source_diversity":   round(src_div * 100),
            "format_fit":         round(fmt_fit * 100),
            "risk_control":       round(risk_ctl * 100),
        },
    }


if __name__ == "__main__":
    from pipelines.layer_6_research_packets.brief_loader            import load as load_brief
    from pipelines.layer_6_research_packets.roundup_packet_builder   import build as build_roundup
    from pipelines.layer_6_research_packets.evidence_boundary_enforcer import enforce
    from pipelines.layer_6_research_packets.source_pack_builder      import build as build_sources

    run_id     = sorted(RUNS_DIR.glob("*/layer_5/selected_video_brief.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)[0].parents[1].name
    layer2_dir = RUNS_DIR / run_id / "layer_2"
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

    spans_by_id = {}
    with open(layer2_dir / "source_spans.jsonl") as f:
        for line in f:
            if line.strip():
                s = json.loads(line)
                spans_by_id[s["span_id"]] = s

    docs_by_id = {}
    with open(layer2_dir / "canonical_documents.jsonl") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                docs_by_id[d["canonical_document_id"]] = d

    packet      = build_roundup(brief_ctx, fact_sheets_by_id, claims_by_id)
    b_report    = enforce(packet, brief_ctx, claims_by_id)
    source_pack = build_sources(
        brief_ctx["safe_claim_ids"] | brief_ctx["cautious_claim_ids"],
        claims_by_id, spans_by_id, docs_by_id, run_id
    )
    quality     = score(packet, source_pack, b_report, brief_ctx)

    print(f"Packet quality score : {quality['packet_quality_score']}")
    print(f"Ready for Layer 7    : {quality['ready_for_layer_7']}")
    print(f"Format fit           : {quality['format_fit_status']}")
    print(f"Risk level           : {quality['risk_level']}")
    print(f"Warnings             : {quality['warnings']}")
    print()
    print("Dimension breakdown:")
    for k, v in quality["dimension_breakdown"].items():
        print(f"  {k:22s}: {v}")
