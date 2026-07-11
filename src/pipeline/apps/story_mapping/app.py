from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .clusterer import cluster_records
from .contract import StoryMappingRequest, StoryMappingResponse, StoryMappingStatus
from .llm_client import make_llm
from .prompt_loader import load_system_prompt
from .ranker import rank_stories
from .story_label import attach_story_labels


IST = timezone(timedelta(hours=5, minutes=30))


def run(input_json: dict) -> dict:
    request = StoryMappingRequest.model_validate(input_json)
    run_id = request.run.run_id
    records = request.input.evidence_prep.data.records
    effective_max_pair_hours = _effective_max_pair_hours(request)
    cluster_cfg = _cluster_config(request, effective_max_pair_hours)

    llm_calls: list[dict[str, Any]] = []
    clusters: list[dict] = []
    cluster_stats = {
        "exact_match_edges": 0,
        "semantic_edges": 0,
        "dropped_singletons": 0,
    }

    if records:
        clusters, cluster_stats = cluster_records(records, cluster_cfg)

    llm_story_label_count = 0
    story_label_worker_count = 0
    if clusters and request.config.use_llm_story_labels:
        story_label_cfg = request.config.story_label
        if story_label_cfg is None:
            raise ValueError("story_label config is required when use_llm_story_labels is true")
        story_label_dict = story_label_cfg.model_dump(mode="json")
        story_label_worker_count = int(story_label_dict["worker_count"])
        prompt = load_system_prompt("story_label", story_label_dict["prompt_version"])
        llm = make_llm(
            provider=story_label_dict.get("provider", "openai"),
            model=story_label_dict["model"],
            temperature=float(story_label_dict["temperature"]),
            base_url=story_label_dict.get("base_url"),
        )
        clusters = attach_story_labels(
            clusters,
            story_label_cfg=story_label_dict,
            run_context={
                "collection_window": request.config.collection_window.model_dump(mode="json"),
                "effective_max_pair_hours": effective_max_pair_hours,
            },
            llm=llm,
            llm_calls=llm_calls,
            system_prompt=prompt,
        )
        llm_story_label_count = len(clusters)

    ranked_stories = rank_stories(clusters)
    generated_at = _iso_now()
    status = _overall_status(len(records), len(ranked_stories))
    summary = _build_summary(
        run_id=run_id,
        generated_at=generated_at,
        status=status,
        input_count=len(records),
        stories=ranked_stories,
        cluster_stats=cluster_stats,
        effective_max_pair_hours=effective_max_pair_hours,
        use_llm_story_labels=bool(request.config.use_llm_story_labels),
        story_label_provider=(request.config.story_label.provider if request.config.story_label else ""),
        story_label_model=(request.config.story_label.model if request.config.story_label else ""),
        story_label_prompt_version=(request.config.story_label.prompt_version if request.config.story_label else ""),
        llm_story_label_count=llm_story_label_count,
        story_label_worker_count=story_label_worker_count,
    )

    response = StoryMappingResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "story_count": len(ranked_stories),
            "stories": ranked_stories,
        },
        summary=summary,
        handoff={
            "story_count": len(ranked_stories),
            "ready_for_video_packaging": status == "ok" and len(ranked_stories) > 0,
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _effective_max_pair_hours(request: StoryMappingRequest) -> float:
    configured = request.config.clustering.max_pair_hours
    if configured is not None:
        return float(configured)
    return float(request.config.collection_window.lookback_hours)


def _cluster_config(request: StoryMappingRequest, effective_max_pair_hours: float) -> dict:
    clustering = request.config.clustering.model_dump(mode="json")
    return {
        "embedding_model": request.config.embedding_model,
        "effective_max_pair_hours": effective_max_pair_hours,
        "semantic_primary_threshold": clustering["semantic_primary_threshold"],
        "semantic_supported_threshold": clustering["semantic_supported_threshold"],
        "semantic_title_anchor_threshold": clustering["semantic_title_anchor_threshold"],
        "semantic_merge_groups": clustering["semantic_merge_groups"],
    }


def _overall_status(input_count: int, story_count: int) -> StoryMappingStatus:
    if input_count == 0 or story_count == 0:
        return "failed"
    return "ok"


def _build_summary(
    *,
    run_id: str,
    generated_at: str,
    status: StoryMappingStatus,
    input_count: int,
    stories: list[dict],
    cluster_stats: dict[str, int],
    effective_max_pair_hours: float,
    use_llm_story_labels: bool,
    story_label_provider: str,
    story_label_model: str,
    story_label_prompt_version: str,
    llm_story_label_count: int,
    story_label_worker_count: int,
) -> dict:
    bucket_counts: dict[str, int] = {}
    source_group_mix: dict[str, int] = {}
    for story in stories:
        bucket = story["priority_bucket"]
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        for group in story["source_groups"]:
            source_group_mix[group] = source_group_mix.get(group, 0) + 1

    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "status": status,
        "input_record_count": input_count,
        "story_count": len(stories),
        "single_record_story_count": sum(1 for story in stories if story["record_count"] == 1),
        "multi_record_story_count": sum(1 for story in stories if story["record_count"] > 1),
        "semantic_merge_count": cluster_stats["semantic_edges"],
        "dropped_singleton_count": cluster_stats["dropped_singletons"],
        "effective_max_pair_hours": effective_max_pair_hours,
        "priority_bucket_counts": bucket_counts,
        "source_group_mix": source_group_mix,
        "llm_runtime": {
            "use_llm_story_labels": use_llm_story_labels,
            "story_label_provider": story_label_provider,
            "story_label_model": story_label_model,
            "story_label_prompt_version": story_label_prompt_version,
            "story_label_worker_count": story_label_worker_count,
            "llm_story_label_count": llm_story_label_count,
            "parallelized_steps": ["story_label"] if use_llm_story_labels and stories else [],
            "serial_steps": [],
        },
        "top_story_quality_flags": _top_story_quality_flags(stories[:12]),
        "top_stories": [
            {
                "rank": story["rank"],
                "title": story["story_title"],
                "score": story["rank_score"],
                "record_count": story["record_count"],
                "quality_flags": _story_quality_flags(story),
            }
            for story in stories[:10]
        ],
    }


def _top_story_quality_flags(stories: list[dict]) -> dict:
    flags = {
        "low_editorial_value_count": 0,
        "tutorial_count": 0,
        "weak_content_count": 0,
        "event_update_count": 0,
    }
    for story in stories:
        story_flags = _story_quality_flags(story)
        for key in flags:
            if story_flags.get(key.removesuffix("_count"), False):
                flags[key] += 1
    return flags


def _story_quality_flags(story: dict) -> dict:
    identity = story.get("story_identity") or {}
    return {
        "low_editorial_value": identity.get("editorial_value") == "low",
        "tutorial": bool(identity.get("is_tutorial") or story.get("story_type_hint") == "tutorial_or_demo"),
        "weak_content": any(_record_has_weak_content(record) for record in story.get("records", [])),
        "event_update": bool(identity.get("is_event_update") or story.get("story_type_hint") == "event_update"),
    }


def _record_has_weak_content(record: dict) -> bool:
    content = str(record.get("content", ""))
    if record.get("content_status") != "full":
        return True
    if record.get("content_integrity_status") in {"wrong_article", "title_mismatch", "too_short"}:
        return True
    return record.get("source_group") in {"ai_company_blogs", "tech_news_apis"} and len(content) < 700


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
