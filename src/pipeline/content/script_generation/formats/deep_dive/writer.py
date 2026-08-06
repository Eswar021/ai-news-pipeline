from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ...shared.invocation import invoke_runtime_chain
from ...shared.research import beat_support_context, research_story_sources, validate_story_segment
from ...shared.utils import clean_text, json_dumps, story_id, story_title
from .models import (
    DeepDiveBookendOutput,
    DeepDiveBookendReviewOutput,
    DeepDiveDirectorOutput,
    StoryReviewOutput,
    StorySegmentOutput,
)
from .sections import build_deep_dive_section_inputs


def generate_deep_dive_script(
    *,
    video_packet: dict[str, Any],
    story: dict[str, Any],
    config: dict[str, Any],
    prompt_bundles: dict[str, dict[str, str]],
    llm_runtimes: dict[str, dict[str, Any]],
    llm_calls: list[dict[str, Any]],
    research_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    briefs, truth_indexes, packets = research_story_sources(
        stories=[story],
        script_cfg=config,
        prompt_bundle=prompt_bundles["source_researcher"],
        llm_runtime=llm_runtimes["source_researcher"],
        llm_calls=llm_calls,
        module_name="deep_dive_source_researcher",
    )
    source_brief, truth_index, context_packet = briefs[0], truth_indexes[0], packets[0]

    director = _direct_deep_dive(
        story=story,
        source_brief=source_brief,
        truth_index=truth_index,
        config=config,
        prompt_bundle=prompt_bundles["director"],
        llm_runtime=llm_runtimes["director"],
        llm_calls=llm_calls,
        research_brief=research_brief,
    )
    section_plan = build_deep_dive_section_inputs(story, director, config)

    angle_segments, angle_reviews = _write_angle_sections(
        section_plan=section_plan,
        story=story,
        truth_index=truth_index,
        config=config,
        writer_prompt_bundle=prompt_bundles["section_writer"],
        reviewer_prompt_bundle=prompt_bundles["section_reviewer"],
        writer_runtime=llm_runtimes["section_writer"],
        reviewer_runtime=llm_runtimes["section_reviewer"],
        llm_calls=llm_calls,
    )
    bookends, bookend_reviews = _write_bookends(
        section_plan=section_plan,
        story=story,
        director=director,
        angle_segments=angle_segments,
        config=config,
        writer_prompt_bundle=prompt_bundles["bookend_writer"],
        reviewer_prompt_bundle=prompt_bundles["bookend_reviewer"],
        writer_runtime=llm_runtimes["bookend_writer"],
        reviewer_runtime=llm_runtimes["bookend_reviewer"],
        llm_calls=llm_calls,
    )
    review_enabled = bool((config.get("review") or {}).get("enabled", True))
    return {
        "director": director,
        "section_plan": section_plan,
        "angle_segments": angle_segments,
        "bookends": bookends,
        "source_brief": source_brief,
        "story_truth_index": truth_index,
        "story_context_packet": context_packet,
        "review": {
            "enabled": review_enabled,
            "angle_reviews": angle_reviews,
            "bookend_reviews": bookend_reviews,
            "review_call_count": sum(len(r.get("passes", [])) for r in angle_reviews) + len(bookend_reviews),
            "revision_count": sum(
                1 for r in angle_reviews for p in r.get("passes", []) if p.get("rewrite_required")
            )
            + sum(1 for p in bookend_reviews if p.get("rewrite_required")),
        },
    }


def _direct_deep_dive(
    *,
    story: dict[str, Any],
    source_brief: dict[str, Any],
    truth_index: dict[str, Any],
    config: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    research_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    min_angles = int(config.get("min_angle_sections", 3))
    max_angles = int(config.get("max_angle_sections", 6))
    payload = {
        "task": "Plan a single-topic deep dive: choose the angle sections and brief each one.",
        "topic_story_id": story_id(story),
        "topic_title": story_title(story),
        "angle_count_range": {"min": min_angles, "max": max_angles},
        "source_brief": source_brief,
        "truth_index": truth_index,
        "script_style": config["script_style"],
        "channel_voice": config.get("channel_voice", {}),
        "identity_rule": (
            "Copy topic_story_id and truth IDs exactly from this payload. Give each angle a unique "
            "angle_id like 'angle_01', 'angle_02'. Order angles so they build one coherent explanation."
        ),
    }
    # Web-research framing (present only for researched deep-dives): a structural aid
    # for choosing/ordering angles — NOT a source. Every fact still grounds in the
    # truth_index above; suggested_angles/summary/timeline are never cited directly.
    if research_brief:
        payload["research_brief"] = research_brief
    def _validate(model) -> None:
        # Runs inside the retry/fallback loop: a director that plans the wrong
        # number of angles gets retried, then falls back, instead of hard-failing.
        count = len(model.model_dump(mode="json").get("angle_briefs", []))
        if not min_angles <= count <= max_angles:
            raise ValueError(f"deep-dive director planned {count} angles; expected {min_angles}..{max_angles}")

    director = invoke_runtime_chain(
        module_name="deep_dive_director",
        output_model=DeepDiveDirectorOutput,
        llm_runtime=llm_runtime,
        prompt_bundle=prompt_bundle,
        task_payload=json_dumps(payload),
        metadata={"story_id": story_id(story)},
        llm_calls=llm_calls,
        output_validator=_validate,
    ).model_dump(mode="json")
    return director


def _write_angle_sections(
    *,
    section_plan: list[dict[str, Any]],
    story: dict[str, Any],
    truth_index: dict[str, Any],
    config: dict[str, Any],
    writer_prompt_bundle: dict[str, str],
    reviewer_prompt_bundle: dict[str, str],
    writer_runtime: dict[str, Any],
    reviewer_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    angle_plans = [plan for plan in section_plan if plan["section_type"] == "story"]
    worker_count = min(max(1, int(config.get("worker_count", 1))), max(1, len(angle_plans)))
    call_logs: list[list[dict[str, Any]]] = [[] for _ in angle_plans]
    results: list[dict[str, Any] | None] = [None] * len(angle_plans)

    def write(index: int, plan: dict[str, Any]):
        return index, _write_one_angle(
            plan=plan,
            story=story,
            truth_index=truth_index,
            config=config,
            writer_prompt_bundle=writer_prompt_bundle,
            reviewer_prompt_bundle=reviewer_prompt_bundle,
            writer_runtime=writer_runtime,
            reviewer_runtime=reviewer_runtime,
            llm_calls=call_logs[index],
        )

    try:
        if worker_count == 1:
            for index, plan in enumerate(angle_plans):
                _, result = write(index, plan)
                results[index] = result
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {executor.submit(write, index, plan): index for index, plan in enumerate(angle_plans)}
                for future in as_completed(futures):
                    index, result = future.result()
                    results[index] = result
    finally:
        for logs in call_logs:
            llm_calls.extend(logs)

    if any(result is None for result in results):
        raise RuntimeError("deep-dive angle writing completed with a missing section")
    segments = [result["segment"] for result in results if result]
    reviews = [result["review"] for result in results if result]
    return segments, reviews


def _write_one_angle(
    *,
    plan: dict[str, Any],
    story: dict[str, Any],
    truth_index: dict[str, Any],
    config: dict[str, Any],
    writer_prompt_bundle: dict[str, str],
    reviewer_prompt_bundle: dict[str, str],
    writer_runtime: dict[str, Any],
    reviewer_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    angle_id = clean_text(plan.get("angle_id"))
    payload = dict(plan["prompt_payload"])
    payload["required_story_id"] = story_id(story)
    payload["allowed_source_record_keys"] = plan["allowed_source_record_keys"]
    payload["truth_index"] = truth_index
    payload["identity_rule"] = (
        "Set story_id to required_story_id exactly. Ground every factual beat in allowed_source_record_keys "
        "and support_truth_ids from the truth_index; never invent identifiers."
    )
    segment_model = invoke_runtime_chain(
        module_name="deep_dive_section_writer",
        output_model=StorySegmentOutput,
        llm_runtime=writer_runtime,
        prompt_bundle=writer_prompt_bundle,
        task_payload=json_dumps(payload),
        metadata={"story_id": story_id(story), "angle_id": angle_id},
        llm_calls=llm_calls,
        # Retry + fall back inside the loop on a segment that mis-cites truth/source
        # IDs, instead of hard-failing the run.
        output_validator=lambda model: validate_story_segment(
            model.model_dump(mode="json"), story=story, truth_index=truth_index
        ),
    )
    segment = validate_story_segment(segment_model.model_dump(mode="json"), story=story, truth_index=truth_index)
    segment["angle_id"] = angle_id

    review_config = config.get("review") or {}
    if not bool(review_config.get("enabled", True)) or int(review_config.get("max_revision_passes", 1)) < 1:
        return {"segment": segment, "review": {"enabled": False, "passes": []}}

    review_payload = {
        "task": "Review one deep-dive angle segment; keep it or return a full rewrite in revised_segment.",
        "required_story_id": story_id(story),
        "quality_criteria": review_config.get("quality_criteria", []),
        "beat_support_context": beat_support_context(segment, truth_index),
        "other_angles": plan["prompt_payload"].get("other_angles", []),
        "segment": segment,
    }
    review = invoke_runtime_chain(
        module_name="deep_dive_section_reviewer",
        output_model=StoryReviewOutput,
        llm_runtime=reviewer_runtime,
        prompt_bundle=reviewer_prompt_bundle,
        task_payload=json_dumps(review_payload),
        metadata={"story_id": story_id(story), "angle_id": angle_id},
        llm_calls=llm_calls,
    ).model_dump(mode="json")
    passes = [{"rewrite_required": review["rewrite_required"], "issue_codes": [issue["code"] for issue in review.get("issues", [])]}]
    if review["rewrite_required"] and review.get("revised_segment"):
        revised = validate_story_segment(review["revised_segment"], story=story, truth_index=truth_index)
        revised["angle_id"] = angle_id
        segment = revised
    return {"segment": segment, "review": {"enabled": True, "passes": passes}}


def _write_bookends(
    *,
    section_plan: list[dict[str, Any]],
    story: dict[str, Any],
    director: dict[str, Any],
    angle_segments: list[dict[str, Any]],
    config: dict[str, Any],
    writer_prompt_bundle: dict[str, str],
    reviewer_prompt_bundle: dict[str, str],
    writer_runtime: dict[str, Any],
    reviewer_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    guidance = config.get("writing_guidance") or {}
    payload = {
        "task": "Write the intro and closing beats for a single-topic deep-dive video.",
        "topic_title": story_title(story),
        "episode_direction": director,
        "angle_previews": [
            {
                "angle_label": clean_text(segment.get("display_title")),
                "thesis": clean_text(segment.get("story_thesis")),
                "takeaway": clean_text(segment.get("viewer_takeaway")),
            }
            for segment in angle_segments
        ],
        "script_style": config["script_style"],
        "channel_brand": config.get("channel_brand", {}),
        "writing_guidance": {"intro": guidance.get("intro", {}), "closing": guidance.get("closing", {})},
        "rules": [
            "The intro must not merely list the angles; it should hook on the topic's most striking detail.",
            "The closing lands one honest takeaway and a short natural signoff.",
        ],
    }
    bookends = invoke_runtime_chain(
        module_name="deep_dive_bookend_writer",
        output_model=DeepDiveBookendOutput,
        llm_runtime=writer_runtime,
        prompt_bundle=writer_prompt_bundle,
        task_payload=json_dumps(payload),
        metadata={"story_id": story_id(story)},
        llm_calls=llm_calls,
    ).model_dump(mode="json")

    review_config = config.get("review") or {}
    if not bool(review_config.get("enabled", True)) or int(review_config.get("max_revision_passes", 1)) < 1:
        return bookends, []

    review_payload = {
        "task": "Review the deep-dive intro and closing; keep them or return a full rewrite in revised_bookends.",
        "quality_criteria": review_config.get("quality_criteria", []),
        "bookends": bookends,
        "topic_title": story_title(story),
    }
    review = invoke_runtime_chain(
        module_name="deep_dive_bookend_reviewer",
        output_model=DeepDiveBookendReviewOutput,
        llm_runtime=reviewer_runtime,
        prompt_bundle=reviewer_prompt_bundle,
        task_payload=json_dumps(review_payload),
        metadata={"story_id": story_id(story)},
        llm_calls=llm_calls,
    ).model_dump(mode="json")
    passes = [{"rewrite_required": review["rewrite_required"], "issue_codes": [issue["code"] for issue in review.get("issues", [])]}]
    if review["rewrite_required"] and review.get("revised_bookends"):
        bookends = review["revised_bookends"]
    return bookends, passes
