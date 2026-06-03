from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from typing import Any, Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from .llm_logging import build_llm_call_log
from .utils import clean_text, dedupe, estimated_seconds, json_dumps, story_id, word_count


TASK_PROMPT = PromptTemplate.from_template(
    "{system_prompt}\n\n"
    "{user_preamble}\n\n"
    "Task payload:\n"
    "{task_payload}"
)


class StoryUsageCardOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    role: str
    story_promise: str = Field(description="What this story contributes to the video.")
    best_angle: str = Field(description="The best viewer-facing angle for this story.")
    key_beats: list[str] = Field(description="Concrete beats to use in narration.")
    nuance_or_caveat: str = Field(description="A concise caution, limitation, or watch item.")
    transition_hint: str = Field(description="How this story can connect to nearby stories.")
    viewer_takeaway: str = Field(description="One practical takeaway for the intended audience.")
    avoid_in_script: list[str] = Field(default_factory=list)
    source_record_keys: list[str] = Field(default_factory=list)


class ScriptSectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    section_type: Literal["intro", "story", "closing"]
    section_order: int
    story_id: str = ""
    narration_text: str
    used_story_ids: list[str] = Field(default_factory=list)
    used_source_record_keys: list[str] = Field(default_factory=list)
    analysis_sentences: list[str] = Field(default_factory=list)


class FullScriptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[ScriptSectionOutput]
    full_script: str = Field(description="Complete spoken narration assembled from the sections.")
    script_strategy: str = Field(description="Short explanation of the draft's YouTube storytelling strategy.")
    revision_notes_applied: list[str] = Field(default_factory=list)


class ReflectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_score: int = Field(description="1-10 score for YouTube script quality.")
    attention_score: int
    clarity_score: int
    flow_score: int
    pacing_score: int
    audience_fit_score: int
    should_revise: bool
    strengths: list[str] = Field(default_factory=list)
    priority_fixes: list[str] = Field(default_factory=list)
    rewrite_brief: str = Field(description="Concise instructions for improving the next draft.")


def generate_roundup_script(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    script_cfg: dict[str, Any],
    prompt_bundles: dict[str, dict[str, str]],
    llm,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    story_cards = analyze_story_usage(
        video_packet=video_packet,
        script_cfg=script_cfg,
        prompt_bundle=prompt_bundles["story_usage"],
        llm=llm,
        llm_calls=llm_calls,
    )
    current = draft_full_script(
        video_packet=video_packet,
        section_plan=section_plan,
        story_cards=story_cards,
        script_cfg=script_cfg,
        prompt_bundle=prompt_bundles["full_script"],
        llm=llm,
        llm_calls=llm_calls,
    )
    current["draft_id"] = "draft_00_initial"

    reflection_state = run_reflection_loop(
        video_packet=video_packet,
        section_plan=section_plan,
        story_cards=story_cards,
        initial_script=current,
        script_cfg=script_cfg,
        reflection_prompt_bundle=prompt_bundles["reflection"],
        revision_prompt_bundle=prompt_bundles["revision"],
        llm=llm,
        llm_calls=llm_calls,
    )
    final_script = reflection_state["final_script"]
    return {
        "story_usage_cards": story_cards,
        "sections": final_script["sections"],
        "script_strategy": final_script.get("script_strategy", ""),
        "revision_notes_applied": final_script.get("revision_notes_applied", []),
        "reflection": {
            "enabled": bool(script_cfg.get("reflection", {}).get("enabled", True)),
            "iterations": reflection_state["iterations"],
            "revision_count": reflection_state["revision_count"],
            "final_score": reflection_state["final_score"],
        },
    }


def analyze_story_usage(
    *,
    video_packet: dict[str, Any],
    script_cfg: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stories = list(video_packet.get("stories", []))
    structured_llm = llm.with_structured_output(StoryUsageCardOutput, include_raw=True)
    chain = TASK_PROMPT | structured_llm
    worker_count = int(script_cfg.get("worker_count", 1))

    if worker_count == 1:
        return [
            _analyze_one_story(
                story=story,
                video_packet=video_packet,
                script_cfg=script_cfg,
                prompt_bundle=prompt_bundle,
                chain=chain,
                llm_calls=llm_calls,
            )
            for story in stories
        ]

    ordered: list[dict[str, Any] | None] = [None] * len(stories)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _analyze_one_story,
                story=story,
                video_packet=video_packet,
                script_cfg=script_cfg,
                prompt_bundle=prompt_bundle,
                chain=chain,
                llm_calls=llm_calls,
            ): index
            for index, story in enumerate(stories)
        }
        for future in as_completed(future_to_index):
            ordered[future_to_index[future]] = future.result()

    if any(card is None for card in ordered):
        raise RuntimeError("Story usage analysis finished with missing cards")
    return [card for card in ordered if card is not None]


def draft_full_script(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    story_cards: list[dict[str, Any]],
    script_cfg: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    structured_llm = llm.with_structured_output(FullScriptOutput, include_raw=True)
    chain = TASK_PROMPT | structured_llm
    payload = _full_script_payload(
        video_packet=video_packet,
        section_plan=section_plan,
        story_cards=story_cards,
        script_cfg=script_cfg,
    )
    response = _invoke_chain(
        module_name="roundup_full_script_writer",
        output_model=FullScriptOutput,
        chain=chain,
        prompt_bundle=prompt_bundle,
        task_payload=payload,
        script_cfg=script_cfg,
        metadata={"draft_id": "draft_00_initial", "story_count": len(video_packet.get("stories", []))},
        llm_calls=llm_calls,
    )
    return _validate_full_script_output(response, section_plan, video_packet, script_cfg)


def run_reflection_loop(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    story_cards: list[dict[str, Any]],
    initial_script: dict[str, Any],
    script_cfg: dict[str, Any],
    reflection_prompt_bundle: dict[str, str],
    revision_prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    reflection_cfg = dict(script_cfg.get("reflection") or {})
    if not bool(reflection_cfg.get("enabled", True)):
        return {
            "final_script": initial_script,
            "iterations": [],
            "revision_count": 0,
            "final_score": None,
        }

    max_revision_passes = int(reflection_cfg.get("max_revision_passes", 1))
    target_score = int(reflection_cfg.get("target_score", 8))
    current = initial_script
    iterations: list[dict[str, Any]] = []
    revision_count = 0

    for pass_index in range(max_revision_passes + 1):
        reflection = reflect_on_script(
            video_packet=video_packet,
            section_plan=section_plan,
            story_cards=story_cards,
            script=current,
            script_cfg=script_cfg,
            prompt_bundle=reflection_prompt_bundle,
            llm=llm,
            llm_calls=llm_calls,
            pass_index=pass_index,
        )
        iterations.append(
            {
                "pass_index": pass_index,
                "draft_id": current["draft_id"],
                "reflection": reflection,
            }
        )

        if pass_index >= max_revision_passes:
            break
        if not reflection["should_revise"] and int(reflection["overall_score"]) >= target_score:
            break

        revision_count += 1
        current = revise_full_script(
            video_packet=video_packet,
            section_plan=section_plan,
            story_cards=story_cards,
            current_script=current,
            reflection=reflection,
            script_cfg=script_cfg,
            prompt_bundle=revision_prompt_bundle,
            llm=llm,
            llm_calls=llm_calls,
            revision_index=revision_count,
        )

    final_score = iterations[-1]["reflection"]["overall_score"] if iterations else None
    return {
        "final_script": current,
        "iterations": iterations,
        "revision_count": revision_count,
        "final_score": final_score,
    }


def reflect_on_script(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    story_cards: list[dict[str, Any]],
    script: dict[str, Any],
    script_cfg: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
    pass_index: int,
) -> dict[str, Any]:
    structured_llm = llm.with_structured_output(ReflectionOutput, include_raw=True)
    chain = TASK_PROMPT | structured_llm
    payload = {
        "task": "Critique the full roundup script as a YouTube video script.",
        "reflection_focus": [
            "strong hook",
            "clear viewer promise",
            "plain-language clarity",
            "story ordering and transitions",
            "pacing against target duration",
            "energy without hype",
            "memorable closing",
        ],
        "do_not_turn_this_into": [
            "a technical verification report",
            "a source checklist",
            "a list of compliance warnings",
        ],
        "target_score": int((script_cfg.get("reflection") or {}).get("target_score", 8)),
        "script_style": script_cfg["script_style"],
        "video_context": _video_context(video_packet),
        "section_plan": _compact_section_plan(section_plan),
        "story_usage_cards": story_cards,
        "current_script": _script_for_prompt(script),
    }
    response = _invoke_chain(
        module_name="roundup_script_reflector",
        output_model=ReflectionOutput,
        chain=chain,
        prompt_bundle=prompt_bundle,
        task_payload=json_dumps(payload),
        script_cfg=script_cfg,
        metadata={"pass_index": pass_index, "draft_id": script["draft_id"]},
        llm_calls=llm_calls,
    )
    return _validate_reflection_output(response)


def revise_full_script(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    story_cards: list[dict[str, Any]],
    current_script: dict[str, Any],
    reflection: dict[str, Any],
    script_cfg: dict[str, Any],
    prompt_bundle: dict[str, str],
    llm,
    llm_calls: list[dict[str, Any]],
    revision_index: int,
) -> dict[str, Any]:
    structured_llm = llm.with_structured_output(FullScriptOutput, include_raw=True)
    chain = TASK_PROMPT | structured_llm
    payload = {
        "task": "Revise the full roundup script using the reflection notes.",
        "revision_goal": (
            "Improve the YouTube viewing experience: stronger attention, clearer through-line, "
            "smoother transitions, tighter pacing, and a more satisfying closing."
        ),
        "script_style": script_cfg["script_style"],
        "video_context": _video_context(video_packet),
        "section_plan": _compact_section_plan(section_plan),
        "selected_stories_with_full_records": video_packet.get("stories", []),
        "story_usage_cards": story_cards,
        "current_script": _script_for_prompt(current_script),
        "reflection": reflection,
    }
    response = _invoke_chain(
        module_name="roundup_script_reviser",
        output_model=FullScriptOutput,
        chain=chain,
        prompt_bundle=prompt_bundle,
        task_payload=json_dumps(payload),
        script_cfg=script_cfg,
        metadata={"revision_index": revision_index, "previous_draft_id": current_script["draft_id"]},
        llm_calls=llm_calls,
    )
    revised = _validate_full_script_output(response, section_plan, video_packet, script_cfg)
    revised["draft_id"] = f"draft_{revision_index:02d}_revision"
    return revised


def _analyze_one_story(
    *,
    story: dict[str, Any],
    video_packet: dict[str, Any],
    script_cfg: dict[str, Any],
    prompt_bundle: dict[str, str],
    chain,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    sid = story_id(story)
    payload = {
        "task": "Analyze how this selected story should be used in the roundup script.",
        "script_style": script_cfg["script_style"],
        "video_context": _video_context(video_packet),
        "selected_story_with_full_records": story,
        "required_story_id": sid,
        "source_record_keys": _source_record_keys(story),
    }
    response = _invoke_chain(
        module_name="story_usage_analyzer",
        output_model=StoryUsageCardOutput,
        chain=chain,
        prompt_bundle=prompt_bundle,
        task_payload=json_dumps(payload),
        script_cfg=script_cfg,
        metadata={"story_id": sid},
        llm_calls=llm_calls,
    )
    return _validate_story_usage_card(response, story)


def _invoke_chain(
    *,
    module_name: str,
    output_model,
    chain,
    prompt_bundle: dict[str, str],
    task_payload: str,
    script_cfg: dict[str, Any],
    metadata: dict[str, Any],
    llm_calls: list[dict[str, Any]],
):
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": task_payload,
    }
    rendered_prompt = TASK_PROMPT.format(**prompt_inputs)
    started = time.time()
    result = chain.invoke(prompt_inputs)
    duration = time.time() - started

    raw = result.get("raw") if isinstance(result, dict) else None
    parsed = result.get("parsed") if isinstance(result, dict) else result
    parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
    provider = str(script_cfg.get("provider", ""))
    model = str(script_cfg.get("model", ""))

    if parsing_error is not None or parsed is None:
        llm_calls.append(
            build_llm_call_log(
                module_name=module_name,
                provider=provider,
                model=model,
                rendered_prompt=rendered_prompt,
                raw_response=raw,
                parsed_output=None,
                metadata=metadata,
                duration_seconds=duration,
                parse_error=str(parsing_error),
            )
        )
        error = ValueError(f"LLM structured output failed for {module_name}")
        if isinstance(parsing_error, BaseException):
            raise error from parsing_error
        raise error

    parsed_model = parsed if isinstance(parsed, output_model) else output_model.model_validate(parsed)
    parsed_output = parsed_model.model_dump(mode="json")
    llm_calls.append(
        build_llm_call_log(
            module_name=module_name,
            provider=provider,
            model=model,
            rendered_prompt=rendered_prompt,
            raw_response=raw,
            parsed_output=parsed_output,
            metadata=metadata,
            duration_seconds=duration,
        )
    )
    return parsed_model


def _validate_story_usage_card(response: StoryUsageCardOutput | BaseModel | dict[str, Any], story: dict[str, Any]) -> dict[str, Any]:
    raw = response.model_dump(mode="json") if isinstance(response, BaseModel) else dict(response)
    sid = story_id(story)
    if clean_text(raw.get("story_id", "")) != sid:
        raise ValueError(f"story_usage_analyzer returned the wrong story_id for {sid}")
    allowed_source_keys = set(_source_record_keys(story))
    source_keys = dedupe([clean_text(value) for value in raw.get("source_record_keys", [])])
    unknown_source_keys = sorted(set(source_keys) - allowed_source_keys)
    if unknown_source_keys:
        raise ValueError(f"story_usage_analyzer used source keys outside story {sid}: {unknown_source_keys}")
    raw["source_record_keys"] = source_keys
    raw["role"] = clean_text(raw.get("role", "")) or clean_text((story.get("video_segment") or {}).get("role", ""))
    return raw


def _validate_full_script_output(
    response: FullScriptOutput | BaseModel | dict[str, Any],
    section_plan: list[dict[str, Any]],
    video_packet: dict[str, Any],
    script_cfg: dict[str, Any],
) -> dict[str, Any]:
    raw = response.model_dump(mode="json") if isinstance(response, BaseModel) else dict(response)
    raw_sections = list(raw.get("sections", []))
    expected = _expected_section_index(section_plan)
    if len(raw_sections) != len(section_plan):
        raise ValueError(f"Full script returned {len(raw_sections)} sections; expected {len(section_plan)}")

    sections = []
    for raw_section, plan in zip(raw_sections, section_plan):
        section = _normalize_section(raw_section, plan, video_packet, script_cfg)
        expected_section = expected[section["section_id"]]
        if section["section_order"] != expected_section["section_order"]:
            raise ValueError(f"{section['section_id']} has unexpected section_order")
        sections.append(section)

    return {
        "sections": sections,
        "script_strategy": clean_text(raw.get("script_strategy", "")),
        "revision_notes_applied": dedupe([clean_text(value) for value in raw.get("revision_notes_applied", [])]),
    }


def _normalize_section(
    raw_section: dict[str, Any],
    plan: dict[str, Any],
    video_packet: dict[str, Any],
    script_cfg: dict[str, Any],
) -> dict[str, Any]:
    section_id = clean_text(raw_section.get("section_id", ""))
    if section_id != plan["section_id"]:
        raise ValueError(f"Full script returned section_id {section_id!r}; expected {plan['section_id']!r}")
    section_type = clean_text(raw_section.get("section_type", ""))
    if section_type != plan["section_type"]:
        raise ValueError(f"{section_id} returned section_type {section_type!r}; expected {plan['section_type']!r}")

    narration = clean_text(raw_section.get("narration_text", ""))
    if not narration:
        raise ValueError(f"{section_id} returned empty narration_text")

    allowed_story_ids = set(plan.get("allowed_story_ids", []))
    used_story_ids = dedupe([clean_text(value) for value in raw_section.get("used_story_ids", [])])
    unknown_story_ids = sorted(set(used_story_ids) - allowed_story_ids)
    if unknown_story_ids:
        raise ValueError(f"{section_id} used story IDs outside its allowed set: {unknown_story_ids}")
    if section_type == "story" and plan.get("story_id") not in used_story_ids:
        raise ValueError(f"{section_id} must include its assigned story_id in used_story_ids")

    allowed_source_keys = set(plan.get("allowed_source_record_keys", []))
    used_source_keys = dedupe([clean_text(value) for value in raw_section.get("used_source_record_keys", [])])
    unknown_source_keys = sorted(set(used_source_keys) - allowed_source_keys)
    if unknown_source_keys:
        raise ValueError(f"{section_id} used source keys outside its section: {unknown_source_keys}")
    if section_type == "story" and allowed_source_keys and not used_source_keys:
        raise ValueError(f"{section_id} must include at least one used_source_record_key")

    words_per_minute = int(script_cfg["words_per_minute"])
    return {
        "section_id": section_id,
        "section_type": section_type,
        "section_order": int(plan["section_order"]),
        "story_id": plan.get("story_id", ""),
        "story_title": plan.get("story_title", ""),
        "role": plan.get("role", ""),
        "target_seconds": int(plan["target_seconds"]),
        "word_budget": int(plan["word_budget"]),
        "narration_text": narration,
        "word_count": word_count(narration),
        "estimated_seconds": estimated_seconds(narration, words_per_minute),
        "used_story_ids": used_story_ids,
        "used_source_record_keys": used_source_keys,
        "analysis_sentences": dedupe([clean_text(value) for value in raw_section.get("analysis_sentences", [])]),
    }


def _validate_reflection_output(response: ReflectionOutput | BaseModel | dict[str, Any]) -> dict[str, Any]:
    raw = response.model_dump(mode="json") if isinstance(response, BaseModel) else dict(response)
    for key in ("overall_score", "attention_score", "clarity_score", "flow_score", "pacing_score", "audience_fit_score"):
        value = int(raw.get(key, 0))
        if value < 1 or value > 10:
            raise ValueError(f"roundup_script_reflector {key} must be between 1 and 10")
        raw[key] = value
    raw["should_revise"] = bool(raw.get("should_revise", False))
    raw["strengths"] = dedupe([clean_text(value) for value in raw.get("strengths", [])])
    raw["priority_fixes"] = dedupe([clean_text(value) for value in raw.get("priority_fixes", [])])
    raw["rewrite_brief"] = clean_text(raw.get("rewrite_brief", ""))
    return raw


def _full_script_payload(
    *,
    video_packet: dict[str, Any],
    section_plan: list[dict[str, Any]],
    story_cards: list[dict[str, Any]],
    script_cfg: dict[str, Any],
) -> str:
    payload = {
        "task": "Write the complete roundup video script in one coherent pass.",
        "script_style": script_cfg["script_style"],
        "video_context": _video_context(video_packet),
        "section_plan": _compact_section_plan(section_plan),
        "selected_stories_with_full_records": video_packet.get("stories", []),
        "story_usage_cards": story_cards,
        "required_output_schema": _full_script_schema_hint(),
    }
    return json_dumps(payload)


def _full_script_schema_hint() -> dict[str, Any]:
    return {
        "sections": "exactly one intro, one section per selected story, and one closing, matching section_plan order",
        "full_script": "complete spoken narration assembled from sections",
        "script_strategy": "short note on hook, flow, and ending strategy",
        "revision_notes_applied": "empty for initial drafts; filled for revised drafts",
    }


def _video_context(video_packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_type": video_packet.get("packet_type", ""),
        "selected_format": video_packet.get("selected_format", ""),
        "target_duration_seconds": video_packet.get("target_duration_seconds", 0),
        "intro_seconds": video_packet.get("intro_seconds", 0),
        "closing_seconds": video_packet.get("closing_seconds", 0),
        "segment_seconds": video_packet.get("segment_seconds", 0),
        "story_count": video_packet.get("story_count", len(video_packet.get("stories", []))),
        "selected_story_ids": list(video_packet.get("selected_story_ids", [])),
        "format_contract": video_packet.get("format_contract", {}),
    }


def _compact_section_plan(section_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "section_id": section["section_id"],
            "section_type": section["section_type"],
            "section_order": section["section_order"],
            "story_id": section.get("story_id", ""),
            "story_title": section.get("story_title", ""),
            "role": section.get("role", ""),
            "target_seconds": section["target_seconds"],
            "word_budget": section["word_budget"],
            "allowed_story_ids": section["allowed_story_ids"],
            "allowed_source_record_keys": section["allowed_source_record_keys"],
            "section_goal": section.get("prompt_payload", {}).get("section_goal", ""),
        }
        for section in section_plan
    ]


def _script_for_prompt(script: dict[str, Any]) -> dict[str, Any]:
    sections = list(script.get("sections", []))
    return {
        "draft_id": script.get("draft_id", ""),
        "script_strategy": script.get("script_strategy", ""),
        "revision_notes_applied": script.get("revision_notes_applied", []),
        "sections": [
            {
                "section_id": section["section_id"],
                "section_type": section["section_type"],
                "section_order": section["section_order"],
                "story_id": section.get("story_id", ""),
                "target_seconds": section.get("target_seconds", 0),
                "word_budget": section.get("word_budget", 0),
                "word_count": section.get("word_count", 0),
                "estimated_seconds": section.get("estimated_seconds", 0),
                "narration_text": section.get("narration_text", ""),
            }
            for section in sections
        ],
    }


def _expected_section_index(section_plan: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {section["section_id"]: section for section in section_plan}


def _source_record_keys(story: dict[str, Any]) -> list[str]:
    keys = list((story.get("video_segment") or {}).get("source_record_keys") or [])
    if not keys:
        keys = [clean_text(record.get("record_key", "")) for record in story.get("records", [])]
    return dedupe(keys)
