from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from pathlib import Path

from src.llm.client import OpenAIJSONClient
from src.pipeline.L1_collection.common import clean_text
from src.pipeline.L3_story_map.fingerprint import build_fingerprint_text


VALID_ACTIONS = {
    "adopted",
    "disproved",
    "expanded",
    "launched",
    "updated",
    "partnered",
    "reported",
    "benchmarked",
    "researched",
    "funded",
    "criticized",
    "explained",
    "tutorial",
    "event_update",
    "unknown",
}
VALID_STORY_TYPES = {
    "official_update",
    "industry_news",
    "research_result",
    "community_product_launch",
    "community_repository",
    "tutorial_or_demo",
    "event_update",
    "reaction_or_opinion",
    "unknown",
}
VALID_EDITORIAL_VALUES = {"high", "medium", "low"}


def attach_story_labels(
    stories: list[dict],
    *,
    layer3_cfg: dict,
    llm_client: OpenAIJSONClient,
    system_prompt: str,
    log_path: Path,
) -> list[dict]:
    worker_count = int(layer3_cfg["story_label_worker_count"])
    if worker_count < 1:
        raise ValueError("layer_3.story_label_worker_count must be at least 1")

    total = len(stories)
    print(f"[L3] Story-label workers: {worker_count}")
    if worker_count == 1:
        labeled: list[dict] = []
        for index, story in enumerate(stories, start=1):
            result = _label_one_story(
                index=index,
                total=total,
                story=story,
                llm_client=llm_client,
                system_prompt=system_prompt,
                log_path=log_path,
            )
            labeled.append(result)
            print(f"[L3] Story label {index:>3}/{total} done — {result.get('story_title', '')[:70]}")
        return labeled

    ordered: list[dict | None] = [None] * total
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _label_one_story,
                index=index,
                total=total,
                story=story,
                llm_client=llm_client,
                system_prompt=system_prompt,
                log_path=log_path,
            ): index - 1
            for index, story in enumerate(stories, start=1)
        }
        completed = 0
        for future in as_completed(future_to_index):
            result = future.result()
            result_index = future_to_index[future]
            ordered[result_index] = result
            completed += 1
            print(f"[L3] Story label {completed:>3}/{total} done — {result.get('story_title', '')[:70]}")

    if any(story is None for story in ordered):
        raise RuntimeError("L3 story labeling finished with missing story outputs")
    return [story for story in ordered if story is not None]


def _label_one_story(
    *,
    index: int,
    total: int,
    story: dict,
    llm_client: OpenAIJSONClient,
    system_prompt: str,
    log_path: Path,
) -> dict:
    response_json = llm_client.generate_json(
        module_name="story_label",
        system_prompt=system_prompt,
        user_prompt=_build_user_prompt(story),
        log_path=log_path,
        metadata={
            "story_id": story.get("story_id", ""),
            "story_title": story.get("story_title", ""),
            "record_count": story.get("record_count", 0),
            "story_index": index,
            "story_total": total,
        },
    )
    label = _validate_story_label(response_json, story)
    next_story = dict(story)
    next_story["story_identity"] = label
    if label["story_type"] != "unknown":
        next_story["story_type_hint"] = label["story_type"]
    return next_story


def _build_user_prompt(story: dict) -> str:
    story_lines = [
        f"story_id: {clean_text(story.get('story_id', ''))}",
        f"story_title: {clean_text(story.get('story_title', ''))}",
        f"record_count: {story.get('record_count', 0)}",
        f"source_groups: {', '.join(story.get('source_groups', []))}",
        f"match_reasons: {', '.join(story.get('match_reasons', []))}",
    ]
    record_blocks = []
    for index, record in enumerate(story.get("records", [])[:6], start=1):
        source_name = record.get("source_name") or record.get("provider") or record.get("channel_name", "")
        header = "\n".join(
            [
                f"record_{index}_key: {clean_text(record.get('record_key', ''))}",
                f"record_{index}_source_group: {clean_text(record.get('source_group', ''))}",
                f"record_{index}_source: {clean_text(record.get('source', ''))}",
                f"record_{index}_source_name: {clean_text(source_name)}",
                f"record_{index}_title: {clean_text(record.get('title', ''))}",
                f"record_{index}_url: {clean_text(record.get('url', ''))}",
                f"record_{index}_published_at: {clean_text(record.get('published_at', ''))}",
            ]
        )
        record_text = build_fingerprint_text(record)[:1800]
        record_blocks.append(f"{header}\nrecord_{index}_text:\n{record_text}")

    return "\n".join(story_lines) + "\n\nSupporting records:\n\n" + "\n\n---\n\n".join(record_blocks)


def _validate_story_label(raw: dict, story: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"Story label response must be a JSON object for {story.get('story_id', '')}")

    primary_entity = _short_text(raw.get("primary_entity", "unknown")) or "unknown"
    owning_org = _short_text(raw.get("owning_org", "unknown")) or "unknown"
    product_or_project = _short_text(raw.get("product_or_project", "unknown")) or "unknown"
    story_action = _enum(raw.get("story_action"), VALID_ACTIONS, "unknown")
    story_type = _enum(raw.get("story_type"), VALID_STORY_TYPES, "unknown")
    editorial_value = _enum(raw.get("editorial_value"), VALID_EDITORIAL_VALUES, "medium")
    is_tutorial = _bool(raw.get("is_tutorial", False))
    is_event_update = _bool(raw.get("is_event_update", False))

    if story_type in {"community_product_launch", "official_update", "industry_news", "research_result"}:
        is_tutorial = story_action == "tutorial"
    if story_type != "event_update":
        is_event_update = story_action == "event_update"

    canonical_story_key = _normalize_key(raw.get("canonical_story_key", raw.get("merge_identity", "")))
    if not canonical_story_key:
        canonical_story_key = _fallback_story_key(
            primary_entity=primary_entity,
            product_or_project=product_or_project,
            story_action=story_action,
            story_type=story_type,
            story=story,
        )

    return {
        "primary_entity": primary_entity,
        "owning_org": owning_org,
        "product_or_project": product_or_project,
        "story_action": story_action,
        "story_type": story_type,
        "canonical_story_key": canonical_story_key,
        "merge_identity": canonical_story_key,
        "one_sentence_story": _short_text(raw.get("one_sentence_story", ""))[:360],
        "editorial_value": editorial_value,
        "is_tutorial": is_tutorial,
        "is_event_update": is_event_update,
        "is_noise": _bool(raw.get("is_noise", False)),
        "why_it_matters": _short_text(raw.get("why_it_matters", ""))[:360],
    }


def _enum(value, allowed: set[str], default: str) -> str:
    cleaned = clean_text(str(value or "")).lower()
    return cleaned if cleaned in allowed else default


def _short_text(value) -> str:
    return clean_text(str(value or ""))[:180]


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned == "true":
            return True
        if cleaned == "false":
            return False
    return bool(value)


def _normalize_key(value) -> str:
    cleaned = clean_text(str(value or "")).lower()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[^a-z0-9|_\- ]+", "", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = re.sub(r"_*\|_*", "|", cleaned)
    return cleaned[:140]


def _fallback_story_key(
    *,
    primary_entity: str,
    product_or_project: str,
    story_action: str,
    story_type: str,
    story: dict,
) -> str:
    entity = product_or_project if product_or_project != "unknown" else primary_entity
    if entity == "unknown":
        entity = clean_text(story.get("story_title", ""))[:80] or clean_text(story.get("story_id", "unknown"))
    return _normalize_key(f"{entity}|{story_action}|{story_type}")
