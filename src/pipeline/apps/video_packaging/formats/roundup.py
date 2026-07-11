from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..config import ROUNDUP_FORMAT_CONTRACT, SCRIPT_APP_BY_FORMAT
from ..utils import clean_text, count_values, normalize_key, round_to_five, safe_int


def build_roundup_packet(stories: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    selected, selection_stats = select_roundup_stories(stories, config)
    roles = roundup_roles(len(selected))
    seconds = roundup_seconds(
        roles,
        target_duration_seconds=int(config["target_duration_seconds"]),
        intro_seconds=int(config["intro_seconds"]),
        closing_seconds=int(config["closing_seconds"]),
        role_weights=dict(config["role_weights"]),
    )
    packaged_stories = build_packaged_stories(selected, roles, seconds)

    packet = {
        "packet_type": "roundup",
        "selected_format": "roundup",
        "script_app": SCRIPT_APP_BY_FORMAT["roundup"],
        "target_duration_seconds": int(config["target_duration_seconds"]),
        "intro_seconds": int(config["intro_seconds"]),
        "closing_seconds": int(config["closing_seconds"]),
        "segment_seconds": sum(
            int(story["video_segment"]["target_seconds"])
            for story in packaged_stories
        ),
        "story_count": len(packaged_stories),
        "selected_story_ids": [_story_id(story) for story in packaged_stories],
        "stories": packaged_stories,
        "format_contract": dict(ROUNDUP_FORMAT_CONTRACT),
    }
    return {
        "packet": packet,
        "selection_stats": selection_stats,
        "role_counts": count_values([story["video_segment"]["role"] for story in packaged_stories]),
    }


def select_roundup_stories(stories: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict], dict[str, Any]]:
    sorted_stories = sorted(stories, key=lambda story: safe_int(story.get("rank"), 999999))
    candidate_limit = int(config["candidate_limit"])
    max_stories = int(config["max_stories"])
    candidates = sorted_stories[:candidate_limit]
    reason_counts: dict[str, int] = {}
    rejected_story_ids: dict[str, list[str]] = {}
    selected: list[dict] = []
    selected_ids: set[str] = set()
    entity_counts: dict[str, int] = {}
    product_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}

    outside_candidate_count = max(0, len(sorted_stories) - len(candidates))
    if outside_candidate_count:
        reason_counts["outside_candidate_limit"] = outside_candidate_count

    for story in candidates:
        story_id = _story_id(story)
        reasons = _rejection_reasons(
            story,
            config,
            selected_count=len(selected),
            max_stories=max_stories,
            entity_counts=entity_counts,
            product_counts=product_counts,
            event_counts=event_counts,
        )
        if reasons:
            rejected_story_ids[story_id] = reasons
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            continue

        selected.append(story)
        selected_ids.add(story_id)
        _increment_diversity_counts(story, entity_counts, product_counts, event_counts)

    for story in candidates:
        story_id = _story_id(story)
        if story_id in selected_ids or story_id in rejected_story_ids:
            continue
        rejected_story_ids[story_id] = ["not_selected"]
        reason_counts["not_selected"] = reason_counts.get("not_selected", 0) + 1

    return selected, {
        "input_story_count": len(stories),
        "candidate_story_count": len(candidates),
        "selected_story_count": len(selected),
        "rejected_story_count": max(0, len(stories) - len(selected)),
        "selection_reason_counts": reason_counts,
        "rejected_story_ids": rejected_story_ids,
        "selected_story_ids": [_story_id(story) for story in selected],
    }


def roundup_roles(count: int) -> list[str]:
    if count <= 0:
        return []
    if count == 1:
        return ["lead"]
    if count == 2:
        return ["lead", "major"]
    roles = ["lead"]
    major_count = min(2, count - 1)
    roles.extend(["major"] * major_count)
    roles.extend(["brief"] * (count - len(roles)))
    return roles


def roundup_seconds(
    roles: list[str],
    *,
    target_duration_seconds: int,
    intro_seconds: int,
    closing_seconds: int,
    role_weights: dict[str, float],
) -> list[int]:
    if not roles:
        return []
    story_budget = target_duration_seconds - intro_seconds - closing_seconds
    weights = [float(role_weights[role]) for role in roles]
    total_weight = sum(weights) or 1.0
    seconds = [round_to_five(story_budget * weight / total_weight) for weight in weights]
    drift = story_budget - sum(seconds)
    seconds[-1] += drift
    return seconds


def build_packaged_stories(stories: list[dict[str, Any]], roles: list[str], seconds: list[int]) -> list[dict[str, Any]]:
    packaged = []
    for index, story in enumerate(stories, start=1):
        packaged_story = deepcopy(story)
        story_id = _story_id(story)
        records = story.get("records", [])
        packaged_story["video_segment"] = {
            "segment_id": f"segment_{index:02d}_{story_id}",
            "segment_order": index,
            "role": roles[index - 1],
            "target_seconds": int(seconds[index - 1]),
            "source_record_keys": [
                clean_text(record.get("record_key", ""))
                for record in records
                if clean_text(record.get("record_key", ""))
            ],
        }
        packaged.append(packaged_story)
    return packaged


def _rejection_reasons(
    story: dict[str, Any],
    config: dict[str, Any],
    *,
    selected_count: int,
    max_stories: int,
    entity_counts: dict[str, int],
    product_counts: dict[str, int],
    event_counts: dict[str, int],
) -> list[str]:
    if selected_count >= max_stories:
        return ["after_max_stories"]

    reasons: list[str] = []
    allowed_buckets = {clean_text(value).lower() for value in config["allowed_priority_buckets"]}
    priority_bucket = clean_text(story.get("priority_bucket", "")).lower()
    identity = story.get("story_identity") or {}

    if priority_bucket not in allowed_buckets:
        reasons.append("priority_bucket_not_allowed")
    if bool(config["exclude_noise"]) and bool(identity.get("is_noise")):
        reasons.append("excluded_noise")
    if bool(config["exclude_tutorials"]) and bool(identity.get("is_tutorial")):
        reasons.append("excluded_tutorial")

    entity_key, product_key, event_key = _diversity_keys(story)
    if entity_key and entity_counts.get(entity_key, 0) >= int(config["max_per_entity"]):
        reasons.append("entity_diversity_cap")
    if product_key and product_counts.get(product_key, 0) >= int(config["max_per_product"]):
        reasons.append("product_diversity_cap")
    if event_key and event_counts.get(event_key, 0) >= int(config["max_per_event_family"]):
        reasons.append("event_family_diversity_cap")
    return reasons


def _increment_diversity_counts(
    story: dict[str, Any],
    entity_counts: dict[str, int],
    product_counts: dict[str, int],
    event_counts: dict[str, int],
) -> None:
    entity_key, product_key, event_key = _diversity_keys(story)
    if entity_key:
        entity_counts[entity_key] = entity_counts.get(entity_key, 0) + 1
    if product_key:
        product_counts[product_key] = product_counts.get(product_key, 0) + 1
    if event_key:
        event_counts[event_key] = event_counts.get(event_key, 0) + 1


def _diversity_keys(story: dict[str, Any]) -> tuple[str, str, str]:
    identity = story.get("story_identity") or {}
    return (
        normalize_key(identity.get("primary_entity", "")),
        normalize_key(identity.get("product_or_project", "")),
        normalize_key(identity.get("canonical_story_key", "")),
    )


def _story_id(story: dict[str, Any]) -> str:
    return clean_text(story.get("story_id", "")) or "unknown_story"
