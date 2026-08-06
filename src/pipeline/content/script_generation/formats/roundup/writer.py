from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ...shared.invocation import invoke_runtime_chain
from ...shared.research import beat_support_context, research_story_sources, validate_story_segment
from ...shared.review_acceptance import bookend_review_beat_ids, story_review_beat_ids
from ...shared.source_truth import truth_item_map
from ...shared.utils import clean_text, dedupe, json_dumps, source_record_keys, story_id, story_title
from .models import (
    BookendOutput,
    BookendReviewOutput,
    EpisodeDirectorOutput,
    StoryReviewOutput,
    StorySegmentOutput,
)


def generate_roundup_script(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    script_cfg: dict[str, Any],
    prompt_bundles: dict[str, dict[str, str]],
    llm_runtimes: dict[str, dict[str, Any]],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    stories = _ordered_stories(video_packet)
    source_briefs, truth_indexes, context_packets = research_story_sources(
        stories=stories,
        script_cfg=script_cfg,
        prompt_bundle=prompt_bundles["source_researcher"],
        llm_runtime=llm_runtimes["source_researcher"],
        llm_calls=llm_calls,
        module_name="roundup_source_researcher",
    )
    director = direct_episode(
        video_packet=video_packet,
        section_plan=section_plan,
        script_cfg=script_cfg,
        prompt_bundle=prompt_bundles["director"],
        llm_runtime=llm_runtimes["director"],
        llm_calls=llm_calls,
        context_packets=context_packets,
    )
    story_segments, story_reviews = write_story_segments(
        video_packet=video_packet,
        section_plan=section_plan,
        director=director,
        script_cfg=script_cfg,
        writer_prompt_bundle=prompt_bundles["story_writer"],
        reviewer_prompt_bundle=prompt_bundles["story_reviewer"],
        writer_llm_runtime=llm_runtimes["story_writer"],
        reviewer_llm_runtime=llm_runtimes["story_reviewer"],
        llm_calls=llm_calls,
        context_packets=context_packets,
    )
    bookends, bookend_reviews = write_bookends(
        video_packet=video_packet,
        section_plan=section_plan,
        director=director,
        story_segments=story_segments,
        script_cfg=script_cfg,
        writer_prompt_bundle=prompt_bundles["bookend_writer"],
        reviewer_prompt_bundle=prompt_bundles["bookend_reviewer"],
        writer_llm_runtime=llm_runtimes["bookend_writer"],
        reviewer_llm_runtime=llm_runtimes["bookend_reviewer"],
        llm_calls=llm_calls,
    )
    story_review_passes = [
        review_pass
        for story_review in story_reviews
        for review_pass in story_review.get("passes", [])
    ]
    all_review_passes = [*story_review_passes, *bookend_reviews]
    return {
        "director": director,
        "story_segments": story_segments,
        "story_truth_indexes": truth_indexes,
        "story_context_packets": context_packets,
        "story_source_briefs": source_briefs,
        "bookends": bookends,
        "review": {
            "enabled": bool(script_cfg.get("review", {}).get("enabled", True)),
            "max_revision_passes": int(script_cfg.get("review", {}).get("max_revision_passes", 1)),
            "story_reviews": story_reviews,
            "bookend_reviews": bookend_reviews,
            "review_call_count": len(all_review_passes),
            "revision_count": sum(bool(item.get("applied")) for item in all_review_passes),
        },
    }


def direct_episode(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    script_cfg: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    context_packets: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "task": "Create the editorial through-line for one roundup episode without writing narration.",
        "script_style": script_cfg["script_style"],
        "channel_voice": script_cfg["channel_voice"],
        "storytelling_policy": script_cfg["storytelling"],
        "video_context": _video_context(video_packet),
        "required_story_order": [story_id(story) for story in _ordered_stories(video_packet)],
        "selected_story_summaries": [_director_story(story) for story in _ordered_stories(video_packet)],
        "story_context_packets": context_packets,
        "section_guidance": _compact_section_plan(section_plan),
    }
    required_ids = [story_id(story) for story in _ordered_stories(video_packet)]
    truth_by_story = {
        clean_text(packet.get("story_id")): set(truth_item_map(packet.get("story_truth_index") or {}))
        for packet in context_packets
    }
    response = invoke_runtime_chain(
        module_name="roundup_director",
        output_model=EpisodeDirectorOutput,
        llm_runtime=llm_runtime,
        prompt_bundle=prompt_bundle,
        task_payload=json_dumps(payload),
        metadata={
            "story_count": len(video_packet.get("stories", [])),
            "truth_item_count": sum(
                len((packet.get("story_truth_index") or {}).get("items", [])) for packet in context_packets
            ),
            "source_record_count": sum(int(packet.get("record_count", 0)) for packet in context_packets),
            "source_context_char_count": sum(
                int((packet.get("telemetry") or {}).get("serialized_char_count", 0)) for packet in context_packets
            ),
            "source_context_mode": "complete_records_plus_semantic_brief",
        },
        llm_calls=llm_calls,
        # Run the structural checks INSIDE the retry/fallback loop: a director that
        # mixes up per-story truth IDs (a common DeepSeek slip on the multi-story
        # task) gets retried, then routed to the fallback model — instead of a hard
        # ValueError that discards the whole run.
        output_validator=lambda model: _validate_director_output(
            model, required_ids=required_ids, truth_by_story=truth_by_story
        ),
    )
    return response.model_dump(mode="json")


def _validate_director_output(
    response,
    *,
    required_ids: list[str],
    truth_by_story: dict[str, set[str]],
) -> None:
    raw = response.model_dump(mode="json")
    if raw["ordered_story_ids"] != required_ids:
        raise ValueError(
            "roundup_director must preserve the deterministic video packet story order: "
            f"{raw['ordered_story_ids']} != {required_ids}"
        )
    brief_ids = [clean_text(item.get("story_id")) for item in raw["story_briefs"]]
    if brief_ids != required_ids:
        raise ValueError(f"roundup_director returned invalid story briefs: {brief_ids} != {required_ids}")
    for brief in raw["story_briefs"]:
        sid = clean_text(brief.get("story_id"))
        available = truth_by_story.get(sid, set())
        required_truth = set(brief.get("must_communicate_truth_ids") or [])
        optional_truth = set(brief.get("optional_truth_ids") or [])
        unknown = sorted((required_truth | optional_truth) - available)
        if unknown:
            raise ValueError(f"roundup_director used unknown truth IDs for {sid}: {unknown}")


def write_story_segments(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    director: dict[str, Any],
    script_cfg: dict[str, Any],
    writer_prompt_bundle: dict[str, str],
    reviewer_prompt_bundle: dict[str, str],
    writer_llm_runtime: dict[str, Any],
    reviewer_llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    context_packets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stories = _ordered_stories(video_packet)
    story_plans = {clean_text(item.get("story_id")): item for item in section_plan if item.get("section_type") == "story"}
    briefs = {clean_text(item.get("story_id")): item for item in director.get("story_briefs", [])}
    packet_by_story = {clean_text(item.get("story_id")): item for item in context_packets}
    worker_count = min(max(1, int(script_cfg.get("worker_count", 1))), len(stories))

    call_logs_by_index: list[list[dict[str, Any]]] = [[] for _ in stories]

    def generate(index: int, story: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, Any]]:
        local_calls = call_logs_by_index[index]
        sid = story_id(story)
        brief = briefs[sid]
        context_packet = packet_by_story[sid]
        segment, review = _write_one_story(
            story=story,
            plan=story_plans[sid],
            brief=brief,
            previous_story=stories[index - 1] if index else None,
            next_story=stories[index + 1] if index + 1 < len(stories) else None,
            script_cfg=script_cfg,
            writer_prompt_bundle=writer_prompt_bundle,
            reviewer_prompt_bundle=reviewer_prompt_bundle,
            writer_llm_runtime=writer_llm_runtime,
            reviewer_llm_runtime=reviewer_llm_runtime,
            llm_calls=local_calls,
            context_packet=context_packet,
        )
        return index, segment, review

    ordered: list[tuple[dict[str, Any], dict[str, Any]] | None] = [None] * len(stories)
    try:
        if worker_count == 1:
            for index, story in enumerate(stories):
                _, segment, review = generate(index, story)
                ordered[index] = (segment, review)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {executor.submit(generate, index, story): index for index, story in enumerate(stories)}
                for future in as_completed(future_map):
                    index, segment, review = future.result()
                    ordered[index] = (segment, review)
    finally:
        for calls in call_logs_by_index:
            llm_calls.extend(calls)

    if any(item is None for item in ordered):
        raise RuntimeError("Story generation completed with missing story segments")
    segments: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for item in ordered:
        if item is None:
            continue
        segment, review = item
        segments.append(segment)
        reviews.append(review)
    return segments, reviews


def _write_one_story(
    *,
    story: dict[str, Any],
    plan: dict[str, Any],
    brief: dict[str, Any],
    previous_story: dict[str, Any] | None,
    next_story: dict[str, Any] | None,
    script_cfg: dict[str, Any],
    writer_prompt_bundle: dict[str, str],
    reviewer_prompt_bundle: dict[str, str],
    writer_llm_runtime: dict[str, Any],
    reviewer_llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    context_packet: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    sid = story_id(story)
    truth_index = dict(context_packet.get("story_truth_index") or {})
    context_telemetry = dict(context_packet.get("telemetry") or {})
    payload = {
        "task": "Write only this story's body as spoken narration beats.",
        "required_story_id": sid,
        "story_role": plan.get("role", ""),
        "writing_guidance": plan.get("writing_guidance", {}),
        "script_style": script_cfg["script_style"],
        "channel_voice": script_cfg["channel_voice"],
        "storytelling_policy": script_cfg["storytelling"],
        "director_brief": brief,
        "story_context_packet": context_packet,
        "allowed_source_record_keys": source_record_keys(story),
        "previous_story_preview": _story_preview(previous_story),
        "next_story_preview": _story_preview(next_story),
        "rules": [
            "Do not write the episode intro, conclusion, or transition into this story.",
            "Treat suggested_words as soft guidance, never as a quota.",
            "Finish when the story is clear; do not add repetition, filler, or generic commentary to make it longer.",
            "Each beat must be a coherent spoken unit.",
            "A beat is usually one or two spoken sentences and roughly 8-12 seconds, but this is creative guidance rather than a quota.",
            "Split a beat when the editorial job changes, such as moving from setup to mechanism, comparison, reaction, or payoff.",
            "Use only source_record_keys from this assigned story.",
            "Do not put camera directions inside narration_text.",
            "Use support_truth_ids and source_record_keys as invisible production metadata; never speak those IDs aloud.",
            "Stay materially faithful to the assigned records while adding a clear creator viewpoint, analogy, humor, or prediction when it helps.",
            "Build the mini-story around tension, explanation, and payoff instead of reading the records in source order.",
        ],
    }
    response = invoke_runtime_chain(
        module_name="roundup_story_writer",
        output_model=StorySegmentOutput,
        llm_runtime=writer_llm_runtime,
        prompt_bundle=writer_prompt_bundle,
        task_payload=json_dumps(payload),
        metadata={
            "story_id": sid,
            "story_role": plan.get("role", ""),
            "truth_item_count": len(truth_index.get("items", [])),
            "source_record_count": len(story.get("records", [])),
            "source_context_mode": "complete_records_plus_semantic_brief",
            "source_context_char_count": int(context_telemetry.get("serialized_char_count", 0)),
            "source_record_keys": list(context_telemetry.get("record_keys", [])),
        },
        llm_calls=llm_calls,
        # A segment that cites another story's truth IDs / source keys, or grounds in
        # none, retries and falls back inside the loop instead of hard-failing the run.
        output_validator=lambda model: validate_story_segment(
            model.model_dump(mode="json"), story=story, truth_index=truth_index
        ),
    )
    current = validate_story_segment(
        response.model_dump(mode="json"),
        story=story,
        truth_index=truth_index,
    )
    passes: list[dict[str, Any]] = []
    review_config = dict(script_cfg.get("review", {}))
    max_passes = int(review_config.get("max_revision_passes", 1))
    if not bool(review_config.get("enabled", True)):
        max_passes = 0

    for pass_index in range(1, max_passes + 1):
        review_payload = {
            "task": "Review and, only when useful, improve this story segment without touching another section.",
            "required_story_id": sid,
            "writing_guidance": plan.get("writing_guidance", {}),
            "review_beat_ids": story_review_beat_ids(current),
            "quality_criteria": list(review_config.get("quality_criteria", [])),
            "script_style": script_cfg["script_style"],
            "channel_voice": script_cfg["channel_voice"],
            "storytelling_policy": script_cfg["storytelling"],
            "director_brief": brief,
            "story_context_packet": context_packet,
            "beat_support_context": beat_support_context(current, truth_index),
            "allowed_source_record_keys": source_record_keys(story),
            "current_segment": current,
        }
        review_response = invoke_runtime_chain(
            module_name="roundup_story_reviewer",
            output_model=StoryReviewOutput,
            llm_runtime=reviewer_llm_runtime,
            prompt_bundle=reviewer_prompt_bundle,
            task_payload=json_dumps(review_payload),
            metadata={
                "story_id": sid,
                "pass_index": pass_index,
                "truth_item_count": len(truth_index.get("items", [])),
                "source_context_mode": "complete_records_plus_semantic_brief",
                "source_context_char_count": int(context_telemetry.get("serialized_char_count", 0)),
                "source_record_keys": list(context_telemetry.get("record_keys", [])),
            },
            llm_calls=llm_calls,
        ).model_dump(mode="json")
        review_issues = list(review_response.get("issues") or [])
        if not bool(review_response["rewrite_required"]):
            passes.append(
                {
                    "pass_index": pass_index,
                    "decision": "keep",
                    "issues": [],
                    "model_recommended_rewrite": False,
                    "revision_contract_errors": [],
                    "applied": False,
                }
            )
            break

        revision: dict[str, Any] | None = None
        contract_errors: list[str] = []
        try:
            revision = validate_story_segment(
                review_response["revised_segment"],
                story=story,
                truth_index=truth_index,
            )
        except (TypeError, ValueError) as exc:
            contract_errors = [f"revision_contract_failed:{exc}"]
        applied = revision is not None and not contract_errors
        if applied and revision is not None:
            current = revision
        passes.append(
            {
                "pass_index": pass_index,
                "decision": "rewrite_applied" if applied else "rewrite_rejected",
                "issues": review_issues,
                "model_recommended_rewrite": True,
                "revision_contract_errors": contract_errors,
                "applied": applied,
            }
        )
        if not applied:
            break

    return current, {
        "story_id": sid,
        "passes": passes,
        "writing_guidance": plan.get("writing_guidance", {}),
    }


def write_bookends(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    director: dict[str, Any],
    story_segments: list[dict[str, Any]],
    script_cfg: dict[str, Any],
    writer_prompt_bundle: dict[str, str],
    reviewer_prompt_bundle: dict[str, str],
    writer_llm_runtime: dict[str, Any],
    reviewer_llm_runtime: dict[str, Any],
    llm_calls: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    intro_plan = next(item for item in section_plan if item["section_type"] == "intro")
    closing_plan = next(item for item in section_plan if item["section_type"] == "closing")
    payload = {
        "task": "Write the episode intro, story connectors, title-card copy, and conclusion after story bodies are fixed.",
        "script_style": script_cfg["script_style"],
        "channel_voice": script_cfg["channel_voice"],
        "channel_brand": script_cfg.get("channel_brand", {}),
        "episode_direction": director,
        "intro_writing_guidance": intro_plan.get("writing_guidance", {}),
        "closing_writing_guidance": closing_plan.get("writing_guidance", {}),
        "connector_writing_guidance": script_cfg.get("writing_guidance", {}).get("connector", {}),
        "required_story_ids": [story_id(story) for story in _ordered_stories(video_packet)],
        "connector_targets": _connector_targets(video_packet),
        "story_sequence": _segments_for_bookends(video_packet, story_segments),
        "rules": [
            "Do not rewrite or repeat the story bodies.",
            "Every connector is owned by target_story_id and must introduce that exact target story while its matching title card appears.",
            "Never attach a transition about the following story to the current target_story_id.",
            "The first connector introduces the first story after the intro; later connectors introduce their own target story after the previous story ends.",
            "Connector lines should be short and spoken while their target story title card appears.",
            "Do not force unrelated stories into a universal thesis; an honest roundup promise is enough.",
            "The conclusion should leave one useful thought or a clean signoff, not introduce a new reported fact.",
            "Treat suggested word counts as soft guidance, never as quotas.",
            "Finish each bookend when it has done its editorial job; never pad it with filler or repetition.",
            "Vary connector shapes; do not march through First, Next, Now, Then, and Finally.",
            "Avoid generic technology-collides, AI-is-reshaping-everything, and whirlwind-tour language.",
            "Do not place a paraphrase inside quotation marks. Use quotation marks only for exact wording already present in the completed story bodies.",
            "Do not repeat a completed story body's opening sentence verbatim in the intro.",
            "Follow channel_voice.language.profanity_mode.",
        ],
    }
    response = invoke_runtime_chain(
        module_name="roundup_bookend_writer",
        output_model=BookendOutput,
        llm_runtime=writer_llm_runtime,
        prompt_bundle=writer_prompt_bundle,
        task_payload=json_dumps(payload),
        metadata={"story_count": len(story_segments)},
        llm_calls=llm_calls,
        # Connector-order / missing-beats violations retry and fall back in the loop.
        output_validator=lambda model: _validate_bookends(model.model_dump(mode="json"), video_packet),
    )
    current = _validate_bookends(response.model_dump(mode="json"), video_packet)
    passes: list[dict[str, Any]] = []
    review_config = dict(script_cfg.get("review", {}))
    max_passes = int(review_config.get("max_revision_passes", 1))
    if not bool(review_config.get("enabled", True)):
        max_passes = 0

    for pass_index in range(1, max_passes + 1):
        review_payload = {
            "task": "Review and, only when useful, improve the bookends and connectors for a stronger YouTube episode.",
            "script_style": script_cfg["script_style"],
            "channel_voice": script_cfg["channel_voice"],
            "storytelling_policy": script_cfg["storytelling"],
            "quality_criteria": list(review_config.get("quality_criteria", [])),
            "episode_direction": {
                key: director.get(key, "")
                for key in ("episode_thesis", "viewer_promise", "hook_strategy", "pacing_strategy")
            },
            "intro_writing_guidance": intro_plan.get("writing_guidance", {}),
            "closing_writing_guidance": closing_plan.get("writing_guidance", {}),
            "connector_writing_guidance": script_cfg.get("writing_guidance", {}).get("connector", {}),
            "required_story_ids": payload["required_story_ids"],
            "connector_targets": payload["connector_targets"],
            "story_sequence": payload["story_sequence"],
            "review_beat_ids": bookend_review_beat_ids(current),
            "current_bookends": current,
            "rules": [
                "Apply a revision only when it materially improves hook, continuity, clarity, pacing, or concision.",
                "Do not lengthen a section merely to approach a suggested word count.",
                "Preserve the required story order and keep the language faithful to the completed story bodies.",
                "Verify each connector transition_line and display_title both introduce its target_story_id, not the next item in the list.",
                "Reject invented or inexact quotations and verbatim intro repetition from a story body.",
            ],
        }
        review_response = invoke_runtime_chain(
            module_name="roundup_bookend_reviewer",
            output_model=BookendReviewOutput,
            llm_runtime=reviewer_llm_runtime,
            prompt_bundle=reviewer_prompt_bundle,
            task_payload=json_dumps(review_payload),
            metadata={
                "pass_index": pass_index,
            },
            llm_calls=llm_calls,
        ).model_dump(mode="json")
        review_issues = list(review_response.get("issues") or [])
        if not bool(review_response["rewrite_required"]):
            passes.append(
                {
                    "pass_index": pass_index,
                    "decision": "keep",
                    "issues": [],
                    "model_recommended_rewrite": False,
                    "revision_contract_errors": [],
                    "applied": False,
                }
            )
            break

        revision: dict[str, Any] | None = None
        contract_errors: list[str] = []
        try:
            revision = _validate_bookends(review_response["revised_bookends"], video_packet)
        except (TypeError, ValueError) as exc:
            contract_errors = [f"revision_contract_failed:{exc}"]
        applied = revision is not None and not contract_errors
        if applied and revision is not None:
            current = revision
        passes.append(
            {
                "pass_index": pass_index,
                "decision": "rewrite_applied" if applied else "rewrite_rejected",
                "issues": review_issues,
                "model_recommended_rewrite": True,
                "revision_contract_errors": contract_errors,
                "applied": applied,
            }
        )
        if not applied:
            break
    return current, passes


def _validate_bookends(bookends: dict[str, Any], video_packet: dict[str, Any]) -> dict[str, Any]:
    raw = BookendOutput.model_validate(bookends).model_dump(mode="json")
    required_ids = [story_id(story) for story in _ordered_stories(video_packet)]
    connector_ids = [clean_text(item.get("target_story_id")) for item in raw["story_connectors"]]
    if connector_ids != required_ids:
        raise ValueError(
            "Bookend writer connector target IDs must match story order: "
            f"{connector_ids} != {required_ids}"
        )
    if not raw["intro_beats"] or not raw["closing_beats"]:
        raise ValueError("Bookend writer must return intro and closing beats")
    return raw


def _ordered_stories(video_packet: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        list(video_packet.get("stories", [])),
        key=lambda story: int((story.get("video_segment") or {}).get("segment_order", 999999)),
    )


def _video_context(video_packet: dict[str, Any]) -> dict[str, Any]:
    duration_policy = dict(video_packet.get("duration_policy") or {})
    if not duration_policy:
        legacy_ceiling = video_packet.get("target_duration_seconds")
        duration_policy = {
            "mode": "content_driven",
            "configured_ceiling_seconds": legacy_ceiling,
            "timing_source_of_truth": "voiceover",
        }
    return {
        "selected_format": video_packet.get("selected_format", ""),
        "duration_policy": duration_policy,
        "story_count": len(video_packet.get("stories", [])),
    }


def _compact_section_plan(section_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "section_id": item["section_id"],
            "section_type": item["section_type"],
            "story_id": item.get("story_id", ""),
            "story_title": item.get("story_title", ""),
            "role": item.get("role", ""),
            "writing_guidance": item.get("writing_guidance", {}),
        }
        for item in section_plan
    ]


def _director_story(story: dict[str, Any]) -> dict[str, Any]:
    identity = story.get("story_identity") or {}
    segment = story.get("video_segment") or {}
    return {
        "story_id": story_id(story),
        "story_title": story_title(story),
        "role": segment.get("role", ""),
        "primary_entity": identity.get("primary_entity", ""),
        "product_or_project": identity.get("product_or_project", ""),
        "story_action": identity.get("story_action", ""),
        "one_sentence_story": identity.get("one_sentence_story", ""),
        "why_it_matters": identity.get("why_it_matters", ""),
    }


def _story_preview(story: dict[str, Any] | None) -> dict[str, Any]:
    return _director_story(story) if story else {}


def _segments_for_bookends(video_packet: dict[str, Any], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {clean_text(item.get("story_id")): item for item in segments}
    output: list[dict[str, Any]] = []
    for story in _ordered_stories(video_packet):
        sid = story_id(story)
        segment = by_id[sid]
        output.append(
            {
                **_director_story(story),
                "display_title": segment.get("display_title", ""),
                "story_thesis": segment.get("story_thesis", ""),
                "viewer_takeaway": segment.get("viewer_takeaway", ""),
                "beat_summaries": [
                    {
                        "beat_type": beat.get("beat_type", ""),
                        "beat_function": beat.get("beat_function", ""),
                        "creative_device": beat.get("creative_device", "none"),
                        "narration_text": clean_text(beat.get("narration_text", "")),
                    }
                    for beat in segment.get("beats", [])
                ],
            }
        )
    return output


def _connector_targets(video_packet: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    previous_story: dict[str, Any] | None = None
    for order, story in enumerate(_ordered_stories(video_packet), start=1):
        identity = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
        targets.append(
            {
                "connector_order": order,
                "target_story_id": story_id(story),
                "target_story_title": story_title(story),
                "target_primary_entity": clean_text(identity.get("primary_entity")),
                "previous_story_id": story_id(previous_story) if previous_story else "",
                "previous_story_title": story_title(previous_story) if previous_story else "episode_intro",
            }
        )
        previous_story = story
    return targets
