"""
Layer 6 — Module 2: Roundup Packet Builder

Builds a format-specific roundup research packet from the brief context,
fact sheets, and verified claims. No LLM — pure dict assembly.

Enriches each segment with:
  - claim text resolved from verified_claims_by_id
  - one_line_summary from first high-importance claim in fact sheet
  - why_it_matters from segment's viewer_promise (first sentence)
  - source_span_ids deduplicated across all segment claims

Produces episode_flow with transition notes between consecutive stories.

Key function:
    build(brief_ctx, fact_sheets_by_id, verified_claims_by_id) → packet dict

Individual test:
    python roundup_packet_builder.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_HIGH_IMPORTANCE = {"high", "critical"}
_SUMMARY_CLAIM_TYPES = {"factual_statement", "feature_claim", "model_capability", "product_update"}
_IMPACT_CLAIM_TYPES  = {"business_impact", "user_impact", "interpretive_claim"}


def _first_sentence(text: str) -> str:
    for sep in (".", "!", "?"):
        idx = text.find(sep)
        if idx > 20:
            return text[: idx + 1].strip()
    return text[:200].strip()


def _one_line_summary(story_id: str, safe_facts: list) -> str:
    for fact in safe_facts:
        if (fact.get("importance") in _HIGH_IMPORTANCE and
                fact.get("claim_type") in _SUMMARY_CLAIM_TYPES):
            return fact["claim_text"]
    for fact in safe_facts:
        if fact.get("importance") in _HIGH_IMPORTANCE:
            return fact["claim_text"]
    return safe_facts[0]["claim_text"] if safe_facts else ""


def _why_it_matters(seg: dict, safe_facts: list) -> str:
    viewer_promise = seg.get("viewer_promise", "")
    if viewer_promise:
        return _first_sentence(viewer_promise)
    for fact in safe_facts:
        if fact.get("claim_type") in _IMPACT_CLAIM_TYPES:
            return fact["claim_text"]
    return ""


def _collect_span_ids(claim_ids: list, verified_claims_by_id: dict) -> list:
    seen = set()
    spans = []
    for cid in claim_ids:
        claim = verified_claims_by_id.get(cid, {})
        for sid in claim.get("source_span_ids", []):
            if sid not in seen:
                seen.add(sid)
                spans.append(sid)
    return spans


def build(
    brief_ctx:              dict,
    fact_sheets_by_id:      dict,
    verified_claims_by_id:  dict,
) -> dict:
    content_dir = brief_ctx["content_direction"]
    safe_ids     = brief_ctx["safe_claim_ids"]
    dnu_ids      = brief_ctx["do_not_use_claim_ids"]
    segs_raw     = brief_ctx["story_segment_guidance"]

    segments = []
    for order, seg in enumerate(segs_raw, start=1):
        story_id   = seg["story_id"]
        fs         = fact_sheets_by_id.get(story_id, {})
        safe_facts = fs.get("safe_facts", [])

        seg_safe_claim_ids = [
            cid for cid in seg.get("safe_claim_ids", [])
            if cid in safe_ids and cid not in dnu_ids
        ]
        cautious_claim_ids = [
            cid for cid in seg.get("cautious_claim_ids", [])
            if cid not in dnu_ids
        ]
        span_ids = _collect_span_ids(seg_safe_claim_ids, verified_claims_by_id)

        caution_notes = []
        if cautious_claim_ids:
            caution_notes.append(
                f"Use qualifying language ('may', 'suggests') for: {', '.join(cautious_claim_ids[:3])}"
            )

        segments.append({
            "story_id":               story_id,
            "segment_order":          order,
            "segment_role":           seg.get("segment_role", "quick_update"),
            "target_duration_seconds": seg.get("target_duration_seconds", 60),
            "story_title":            seg.get("story_title", fs.get("canonical_story_title", "")),
            "one_line_summary":       _one_line_summary(story_id, safe_facts),
            "why_it_matters":         _why_it_matters(seg, safe_facts),
            "safe_claim_ids":         seg_safe_claim_ids,
            "cautious_claim_ids":     cautious_claim_ids,
            "do_not_use_claim_ids":   [cid for cid in dnu_ids
                                       if cid.startswith(f"claim_{story_id[-6:]}")],
            "source_span_ids":        span_ids,
            "segment_caution_notes":  caution_notes,
        })

    # Episode flow — linear transitions between consecutive segments
    transitions = []
    for i in range(len(segments) - 1):
        cur  = segments[i]
        nxt  = segments[i + 1]
        transitions.append({
            "from_story_id":   cur["story_id"],
            "to_story_id":     nxt["story_id"],
            "transition_note": f"From {cur['story_title']} to {nxt['story_title']}.",
        })

    total_seconds = sum(s["target_duration_seconds"] for s in segments)

    episode_flow = {
        "intro_focus":     content_dir.get("opening_hook_idea", ""),
        "transition_logic": transitions,
        "final_takeaway":   _first_sentence(content_dir.get("viewer_promise", "")),
    }

    return {
        "packet_type":     "roundup",
        "selected_format": "roundup",
        "episode": {
            "episode_theme":            content_dir.get("episode_theme", ""),
            "viewer_promise":           content_dir.get("viewer_promise", ""),
            "tone_guidance":            content_dir.get("tone_guidance", ""),
            "target_duration_seconds":  total_seconds,
            "story_count":              len(segments),
        },
        "segments":     segments,
        "episode_flow": episode_flow,
    }


if __name__ == "__main__":
    from pipelines.layer_6_research_packets.brief_loader import load as load_brief

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

    packet = build(brief_ctx, fact_sheets_by_id, claims_by_id)

    print(f"Packet type   : {packet['packet_type']}")
    print(f"Stories       : {packet['episode']['story_count']}")
    print(f"Total seconds : {packet['episode']['target_duration_seconds']}")
    print(f"Episode theme : {packet['episode']['episode_theme'][:80]}...")
    print()
    for seg in packet["segments"]:
        print(f"  [{seg['segment_order']}] {seg['segment_role']:20s} | {seg['target_duration_seconds']}s | {len(seg['safe_claim_ids'])} claims | {seg['story_title'][:50]}")
        print(f"       Summary: {seg['one_line_summary'][:90]}")
        print(f"       Why matters: {seg['why_it_matters'][:90]}")
        print()
    print(f"Transitions   : {len(packet['episode_flow']['transition_logic'])}")
