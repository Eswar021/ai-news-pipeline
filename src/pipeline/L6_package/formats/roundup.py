from __future__ import annotations

from src.pipeline.L1_collection.common import clean_text


INTRO_SECONDS = 35
CLOSING_SECONDS = 20
REQUIRED_FACT_LIMITS = {
    "lead": 5,
    "major": 4,
    "brief": 3,
}
MIN_REQUIRED_FACTS = {
    "lead": 4,
    "major": 3,
    "brief": 2,
}
REQUIRED_FACT_TYPE_PRIORITY = {
    "product_fact": 0,
    "event_fact": 0,
    "timeline_fact": 0,
    "model_capability": 0,
    "feature_claim": 1,
    "limitation_claim": 1,
    "risk_claim": 1,
    "research_claim": 1,
    "statistic_claim": 1,
    "partnership_claim": 1,
    "business_claim": 2,
    "benchmark_claim": 2,
    "pricing_claim": 2,
    "prediction_claim": 3,
    "interpretive_claim": 4,
    "quote_claim": 5,
}
LOW_SCRIPT_VALUE_PHRASES = (
    "availability -",
    "availability –",
    "available in the ",
    "aws region",
    "button labeled",
    "download button",
    "download page",
    "click download",
    "to begin using",
    "you must execute",
    "designate your account",
    "review the documentation",
    "service-specific security configurations",
    "prerequisite",
    "setup",
    "install",
    "users can try",
    "available for download",
)


def build_roundup_package(brief: dict) -> dict:
    selected_video = brief["selected_video"]
    selected_by_id = {story["story_id"]: story for story in brief["selected_stories"]}
    candidate_by_id = {item["story_id"]: item for item in brief.get("candidate_evaluations", [])}
    story_order = selected_video.get("story_order", [])
    if not story_order:
        raise ValueError("L5 selected_video.story_order is empty; cannot build L6 roundup packet")
    _validate_story_order(story_order, brief["decision"].get("selected_story_ids", []))

    total_seconds = int(selected_video.get("target_duration_seconds") or brief["decision"]["target_duration_seconds"])
    segment_seconds = _allocate_segment_seconds(story_order, total_seconds)

    segments = []
    for index, order_item in enumerate(story_order, start=1):
        story_id = order_item["story_id"]
        story = selected_by_id.get(story_id)
        if not story:
            raise KeyError(f"L5 story_order references missing selected story: {story_id}")
        candidate = candidate_by_id.get(story_id, {})
        segments.append(
            _build_segment(
                story=story,
                candidate=candidate,
                order_item=order_item,
                order=index,
                target_seconds=segment_seconds[index - 1],
            )
        )

    return {
        "video": _build_video(selected_video, brief["decision"], segments),
        "segment_plan": segments,
        "layer7_handoff": _build_layer7_handoff(selected_video, brief["decision"], segments),
    }


def _build_segment(
    *,
    story: dict,
    candidate: dict,
    order_item: dict,
    order: int,
    target_seconds: int,
) -> dict:
    role = clean_text(order_item.get("role", "brief")) or "brief"
    safe_facts = list(story.get("safe_facts", []))
    cautious_facts = list(story.get("cautious_facts", []))
    required_facts = _required_facts(role, safe_facts, cautious_facts)
    required_ids = {fact["fact_id"] for fact in required_facts}
    optional_facts = [
        fact
        for fact in safe_facts + cautious_facts
        if fact["fact_id"] not in required_ids
    ]
    required_fact_ids = [fact["fact_id"] for fact in required_facts]
    required_cautious_fact_ids = [
        fact["fact_id"] for fact in required_facts if fact.get("status") == "cautious"
    ]
    optional_fact_ids = [fact["fact_id"] for fact in optional_facts]

    return {
        "segment_id": f"segment_{order:02d}_{story['story_id']}",
        "segment_order": order,
        "story_id": story["story_id"],
        "story_title": story["story_title"],
        "story_type_hint": story.get("story_type_hint", ""),
        "role": role,
        "target_seconds": target_seconds,
        "l5_target_seconds": int(order_item.get("target_seconds", target_seconds) or target_seconds),
        "guidance": clean_text(order_item.get("guidance", "")),
        "viewer_value": candidate.get("viewer_value", {}),
        "story_identity": story.get("story_identity", {}),
        "source_groups": story.get("source_groups", []),
        "readiness": story.get("readiness", ""),
        "safe_fact_ids": [fact["fact_id"] for fact in safe_facts],
        "cautious_fact_ids": [fact["fact_id"] for fact in cautious_facts],
        "required_fact_ids": required_fact_ids,
        "required_cautious_fact_ids": required_cautious_fact_ids,
        "optional_fact_ids": optional_fact_ids,
        "safe_facts": safe_facts,
        "cautious_facts": cautious_facts,
        "required_facts": required_facts,
        "optional_facts": optional_facts,
        "selected_supporting_records": story.get("selected_supporting_records", []),
        "caution_notes": _caution_notes(story, cautious_facts, required_facts),
    }


def _required_facts(role: str, safe_facts: list[dict], cautious_facts: list[dict]) -> list[dict]:
    limit = REQUIRED_FACT_LIMITS.get(role, REQUIRED_FACT_LIMITS["brief"])
    minimum = MIN_REQUIRED_FACTS.get(role, MIN_REQUIRED_FACTS["brief"])
    if safe_facts:
        return _script_worthy_required_facts(_sort_facts(safe_facts), limit, minimum)
    return _script_worthy_required_facts(_sort_facts(cautious_facts), limit, minimum)


def _script_worthy_required_facts(facts: list[dict], limit: int, minimum: int) -> list[dict]:
    high_value = [fact for fact in facts if not _is_low_script_value_fact(fact)]
    if len(high_value) >= minimum:
        return high_value[:limit]
    return facts[:limit]


def _sort_facts(facts: list[dict]) -> list[dict]:
    return sorted(
        facts,
        key=lambda fact: (
            REQUIRED_FACT_TYPE_PRIORITY.get(fact.get("fact_type", ""), 9),
            _script_value_penalty(fact),
            -int(fact.get("usefulness_score", 0) or 0),
            fact.get("fact_id", ""),
        ),
    )


def _script_value_penalty(fact: dict) -> int:
    return 4 if _is_low_script_value_fact(fact) else 0


def _is_low_script_value_fact(fact: dict) -> bool:
    text = clean_text(fact.get("fact_text", "")).lower()
    return any(phrase in text for phrase in LOW_SCRIPT_VALUE_PHRASES)


def _caution_notes(story: dict, cautious_facts: list[dict], required_facts: list[dict]) -> list[str]:
    notes = []
    required_cautious = [fact for fact in required_facts if fact.get("status") == "cautious"]
    if story.get("readiness") != "ready":
        notes.append("Evidence status is cautious; attribute claims to the cited source and avoid stronger certainty.")
    if cautious_facts:
        notes.append("Cautious facts must be phrased as reported, suggested, or according to the cited source.")
    if required_cautious and not story.get("safe_facts"):
        notes.append("This segment has no safe facts, so every core claim needs explicit attribution.")
    return notes


def _validate_story_order(story_order: list[dict], selected_story_ids: list[str]) -> None:
    ordered_ids = [item.get("story_id", "") for item in story_order]
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ValueError("L5 selected_video.story_order contains duplicate story_id values")
    if set(ordered_ids) != set(selected_story_ids):
        raise ValueError("L5 selected_video.story_order must contain exactly the selected story IDs")


def _build_video(selected_video: dict, decision: dict, segments: list[dict]) -> dict:
    total_segment_seconds = sum(segment["target_seconds"] for segment in segments)
    return {
        "selected_format": decision["selected_format"],
        "target_duration_seconds": int(selected_video.get("target_duration_seconds", 0)),
        "intro_seconds": INTRO_SECONDS,
        "closing_seconds": CLOSING_SECONDS,
        "segment_seconds": total_segment_seconds,
        "viewer_promise": selected_video.get("viewer_promise", ""),
        "editorial_angle": selected_video.get("editorial_angle", ""),
        "thesis_or_theme": selected_video.get("thesis_or_theme", ""),
        "opening_hook_direction": selected_video.get("opening_hook_direction", ""),
        "tone": selected_video.get("tone", ""),
        "blocked_angles": selected_video.get("blocked_angles", []),
    }


def _build_layer7_handoff(selected_video: dict, decision: dict, segments: list[dict]) -> dict:
    required_fact_ids = []
    cautious_fact_ids = []
    required_cautious_fact_ids = []
    source_record_keys = []
    for segment in segments:
        required_fact_ids.extend(segment["required_fact_ids"])
        required_cautious_fact_ids.extend(segment["required_cautious_fact_ids"])
        cautious_fact_ids.extend(segment["cautious_fact_ids"])
        source_record_keys.extend(
            record.get("record_key", "")
            for record in segment.get("selected_supporting_records", [])
            if record.get("record_key")
        )

    return {
        "ready_for_layer_7": decision["action"] == "create_video" and bool(segments),
        "selected_format": decision["selected_format"],
        "packet_type": "roundup",
        "target_duration_seconds": selected_video.get("target_duration_seconds", 0),
        "intro_seconds": INTRO_SECONDS,
        "closing_seconds": CLOSING_SECONDS,
        "segment_count": len(segments),
        "segment_ids": [segment["segment_id"] for segment in segments],
        "required_fact_ids": _dedupe(required_fact_ids),
        "required_cautious_fact_ids": _dedupe(required_cautious_fact_ids),
        "cautious_fact_ids": _dedupe(cautious_fact_ids),
        "source_record_keys": _dedupe(source_record_keys),
    }


def _allocate_segment_seconds(story_order: list[dict], total_seconds: int) -> list[int]:
    reserved = INTRO_SECONDS + CLOSING_SECONDS
    available = max(0, total_seconds - reserved)
    l5_seconds = [max(0, int(item.get("target_seconds", 0) or 0)) for item in story_order]
    l5_total = sum(l5_seconds)
    if l5_total <= 0:
        base = available // len(story_order)
        seconds = [base for _ in story_order]
    else:
        seconds = [_round_to_five(value * available / l5_total) for value in l5_seconds]

    if seconds:
        seconds[-1] += available - sum(seconds)
    return [max(20, value) for value in seconds]


def _round_to_five(value: float) -> int:
    return int(round(value / 5) * 5)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    kept = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        kept.append(value)
    return kept
