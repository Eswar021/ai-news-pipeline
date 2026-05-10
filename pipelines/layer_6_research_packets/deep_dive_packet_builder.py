"""
Layer 6 — Module 3: Deep Dive Packet Builder

Builds a single-story deep-dive research packet organized into evidence-backed
sections. No LLM — maps claim_type → section, pulls timeline events, and
builds open_questions from evidence_gaps.

Sections produced:
  what_happened, background, technical_context, why_it_matters,
  limitations, open_questions

Key function:
    build(brief_ctx, fact_sheets_by_id, verified_claims_by_id,
          timelines_by_story, evidence_gaps_by_story) → packet dict

Individual test:
    python deep_dive_packet_builder.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_CLAIM_TYPE_TO_SECTION = {
    "factual_statement":  "what_happened",
    "feature_claim":      "what_happened",
    "product_update":     "what_happened",
    "model_capability":   "technical_context",
    "technical_claim":    "technical_context",
    "api_capability":     "technical_context",
    "business_impact":    "why_it_matters",
    "user_impact":        "why_it_matters",
    "market_claim":       "why_it_matters",
    "interpretive_claim": "limitations",
    "background":         "background",
    "background_claim":   "background",
    "historical_claim":   "background",
    "safety_claim":       "limitations",
    "limitation_claim":   "limitations",
    "research_claim":     "background",
}

_SECTION_GOALS = {
    "what_happened":    "Explain exactly what was announced or released.",
    "background":       "Give viewers the context they need to understand why this matters.",
    "technical_context": "Explain the technical details in clear, accessible terms.",
    "why_it_matters":   "Explain the practical impact for developers, enterprises, or the broader AI ecosystem.",
    "limitations":      "Be honest about what is unknown, unproven, or requires cautious interpretation.",
    "open_questions":   "Surface what remains unanswered after the announcement.",
}

_REQUIRED_SECTIONS = ["what_happened", "technical_context", "why_it_matters", "limitations"]


def _map_claims_to_sections(
    safe_facts:      list,
    cautious_facts:  list,
    safe_claim_ids:  set,
    cautious_ids:    set,
    dnu_ids:         set,
) -> dict:
    sections = {s: {"safe": [], "cautious": []} for s in _SECTION_GOALS}

    for fact in safe_facts:
        cid = fact["claim_id"]
        if cid in dnu_ids or cid not in safe_claim_ids:
            continue
        section = _CLAIM_TYPE_TO_SECTION.get(fact.get("claim_type", ""), "background")
        sections[section]["safe"].append(cid)

    for fact in cautious_facts:
        cid = fact["claim_id"]
        if cid in dnu_ids:
            continue
        section = _CLAIM_TYPE_TO_SECTION.get(fact.get("claim_type", ""), "limitations")
        sections[section]["cautious"].append(cid)

    return sections


def build(
    brief_ctx:               dict,
    fact_sheets_by_id:       dict,
    verified_claims_by_id:   dict,
    timelines_by_story:      dict,
    evidence_gaps_by_story:  dict,
) -> dict:
    primary_id  = brief_ctx.get("primary_story_id") or brief_ctx["selected_story_ids"][0]
    content_dir = brief_ctx["content_direction"]
    safe_ids    = brief_ctx["safe_claim_ids"]
    cautious_ids = brief_ctx["cautious_claim_ids"]
    dnu_ids     = brief_ctx["do_not_use_claim_ids"]

    fs            = fact_sheets_by_id.get(primary_id, {})
    safe_facts    = fs.get("safe_facts", [])
    cautious_facts = fs.get("cautious_facts", [])

    section_map = _map_claims_to_sections(
        safe_facts, cautious_facts, safe_ids, cautious_ids, dnu_ids
    )

    research_sections = []
    for section_key, goal in _SECTION_GOALS.items():
        safe_cids    = section_map[section_key]["safe"]
        cautious_cids = section_map[section_key]["cautious"]
        if not safe_cids and not cautious_cids and section_key not in _REQUIRED_SECTIONS:
            continue

        span_ids = []
        seen_spans = set()
        for cid in safe_cids + cautious_cids:
            claim = verified_claims_by_id.get(cid, {})
            for sid in claim.get("source_span_ids", []):
                if sid not in seen_spans:
                    seen_spans.add(sid)
                    span_ids.append(sid)

        notes = []
        if cautious_cids:
            notes.append(f"Use qualifying language for: {', '.join(cautious_cids[:3])}")
        if section_key == "limitations":
            notes.append("Do not present interpretive claims as established facts.")

        research_sections.append({
            "section_key":      section_key,
            "section_goal":     goal,
            "safe_claim_ids":   safe_cids,
            "cautious_claim_ids": cautious_cids,
            "source_span_ids":  span_ids,
            "notes_for_layer7": notes,
        })

    # Timeline
    story_timeline = timelines_by_story.get(primary_id, {})
    timeline_events = [
        {
            "event_order":          ev.get("event_order"),
            "event_time":           ev.get("event_time"),
            "event_label":          ev.get("event_label"),
            "canonical_document_id": ev.get("canonical_document_id"),
            "source_role":          ev.get("source_role"),
        }
        for ev in story_timeline.get("timeline", [])
    ]

    # Open questions from evidence gaps
    story_gaps = evidence_gaps_by_story.get(primary_id, [])
    open_questions = [
        {
            "question":              g.get("gap_description", g.get("gap_type", "Unknown gap")),
            "reason":                g.get("gap_reason", "Not addressed in current sources."),
            "related_evidence_gap_id": g.get("gap_id", ""),
        }
        for g in story_gaps
    ]

    return {
        "packet_type":     "deep_dive",
        "selected_format": "deep_dive",
        "story": {
            "story_id":          primary_id,
            "canonical_story_title": fs.get("canonical_story_title", ""),
            "story_type":        fs.get("story_type", ""),
            "primary_entities":  [],
            "topics":            [],
        },
        "editorial_direction": {
            "central_viewer_question": content_dir.get("central_viewer_question",
                                        content_dir.get("episode_theme", "")),
            "viewer_promise":          content_dir.get("viewer_promise", ""),
            "thesis_candidate":        content_dir.get("suggested_thesis",
                                        content_dir.get("working_angle", "")),
            "tone_guidance":           content_dir.get("tone_guidance", ""),
        },
        "research_sections": research_sections,
        "timeline":          timeline_events,
        "open_questions":    open_questions,
        "evidence_boundaries": {
            "safe_claim_ids":       list(safe_ids),
            "cautious_claim_ids":   list(cautious_ids),
            "do_not_use_claim_ids": list(dnu_ids),
        },
    }


if __name__ == "__main__":
    from pipelines.layer_6_research_packets.brief_loader import load as load_brief

    run_id     = sorted(RUNS_DIR.glob("*/layer_5/selected_video_brief.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)[0].parents[1].name
    layer3_dir = RUNS_DIR / run_id / "layer_3"
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

    with open(layer3_dir / "story_timeline.json") as f:
        raw_tl = json.load(f)
    timelines_by_story = {t["story_id"]: t for t in raw_tl["story_timelines"]}

    with open(layer4_dir / "evidence_gaps.json") as f:
        raw_gaps = json.load(f)
    gaps_by_story = {}
    gap_list = raw_gaps if isinstance(raw_gaps, list) else raw_gaps.get("evidence_gaps", [])
    for g in gap_list:
        sid = g.get("story_id", "")
        gaps_by_story.setdefault(sid, []).append(g)

    # Force deep_dive for test (current run is roundup)
    import copy
    test_ctx = copy.copy(brief_ctx)
    test_ctx["selected_format"] = "deep_dive"
    test_ctx["primary_story_id"] = brief_ctx["selected_story_ids"][0]

    packet = build(test_ctx, fact_sheets_by_id, claims_by_id, timelines_by_story, gaps_by_story)

    print(f"Packet type   : {packet['packet_type']}")
    print(f"Story         : {packet['story']['canonical_story_title']}")
    print(f"Thesis        : {packet['editorial_direction']['thesis_candidate'][:80]}")
    print(f"Sections      : {len(packet['research_sections'])}")
    for s in packet["research_sections"]:
        print(f"  {s['section_key']:20s} | safe={len(s['safe_claim_ids'])} cautious={len(s['cautious_claim_ids'])} spans={len(s['source_span_ids'])}")
    print(f"Timeline events : {len(packet['timeline'])}")
    print(f"Open questions  : {len(packet['open_questions'])}")
