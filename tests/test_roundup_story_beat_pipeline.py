from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool

from src.pipeline.content.script_generation.formats.roundup import app as script_app
from src.pipeline.content.script_generation.formats.roundup import writer as script_writer
from src.pipeline.content.script_generation.formats.roundup.checks import check_script_package
from src.pipeline.content.script_generation.formats.roundup.contract import (
    ReviewConfig,
    ScriptGenerationResponse,
)
from src.pipeline.content.script_generation.formats.roundup.models import (
    BookendOutput,
    BookendReviewOutput,
    EpisodeDirectorOutput,
    StoryReviewOutput,
    StorySegmentOutput,
    StorySourceBriefOutput,
    story_source_brief_output_model,
)
from src.pipeline.content.script_generation.formats.roundup.source_truth import (
    build_story_truth_index,
    compact_truth_index,
)
from src.pipeline.content.script_generation.formats.roundup.sections import build_roundup_section_inputs
from src.pipeline.content.video_packaging.formats.roundup import build_roundup_packet
from src.pipeline.contracts import (
    build_artifact_provenance,
    validate_artifact_provenance,
    visual_plan_artifact_payload,
    voiceover_artifact_payload,
)
from src.pipeline.handoffs.chatgpt_script_parser import run as parse_chatgpt_script
from src.pipeline.handoffs.chatgpt_visual_plan_parser import run as parse_chatgpt_visual_plan
from src.pipeline.visuals.common import voiceover_chunks
from src.pipeline.visuals.planner.app import (
    _build_script_units,
    _compact_scene_timeline,
    _sections_from_script_generation_sections,
    _unit_time_slices,
)
from src.pipeline.voiceover.contract import VoiceoverRequest
from src.pipeline.voiceover import script_units as voice_script_units
from src.pipeline.voiceover import app as voice_app


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "media_roundup_reference"


def _json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _canonical_manual_script() -> dict:
    return parse_chatgpt_script(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {
                "diagnostic_words_per_minute": 150,
                "title_card_seconds": 2.8,
            },
            "input": {
                "response_text": (FIXTURE_DIR / "chatgpt_response.txt").read_text(encoding="utf-8"),
                "video_packaging": _json("video_packaging_result.json"),
                "script_source": "fixture",
            },
        }
    )


def _strict_schema_failures(schema: dict, path: str = "root") -> list[str]:
    failures: list[str] = []
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        if schema.get("additionalProperties") is not False:
            failures.append(f"{path}: additionalProperties")
        for field_name in sorted(set(properties) - required):
            failures.append(f"{path}.{field_name}: optional")
        for field_name, field_schema in properties.items():
            failures.extend(_strict_schema_failures(field_schema, f"{path}.{field_name}"))
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        failures.extend(_strict_schema_failures(schema["items"], f"{path}[]"))
    for composition in ("anyOf", "oneOf", "allOf"):
        for index, item in enumerate(schema.get(composition, [])):
            if isinstance(item, dict):
                failures.extend(_strict_schema_failures(item, f"{path}.{composition}[{index}]"))
    return failures


def test_script_llm_models_are_openai_strict_schema_compatible() -> None:
    models = (
        EpisodeDirectorOutput,
        StorySegmentOutput,
        StoryReviewOutput,
        BookendOutput,
        BookendReviewOutput,
        StorySourceBriefOutput,
    )
    for model in models:
        schema = convert_to_openai_tool(model, strict=True)["function"]["parameters"]
        assert _strict_schema_failures(schema) == [], model.__name__


def test_source_research_schema_binds_story_and_record_identifiers() -> None:
    model = story_source_brief_output_model(
        required_story_id="story_kimi",
        allowed_record_keys=["record_e053ca81a1e2", "record_second"],
    )
    schema = convert_to_openai_tool(model, strict=True)["function"]["parameters"]

    assert _strict_schema_failures(schema) == []
    assert schema["properties"]["story_id"]["const"] == "story_kimi"

    valid_payload = {
        "story_id": "story_kimi",
        "source_synopsis": "Two assigned records describe the same event.",
        "central_event": "The event occurred.",
        "source_relationship_summary": "The records provide complementary coverage.",
        "distinctive_details": [
            {
                "record_key": "record_e053ca81a1e2",
                "detail_type": "event",
                "source_note": "The assigned source reports the event.",
                "value_text": "",
                "claim_frame": "reported_fact",
                "editorial_use": "Explain what happened.",
                "visual_role": "source_proof",
                "visual_opportunity": "Show the source page.",
            }
        ],
        "meaning_boundaries": [
            {
                "record_keys": ["record_second"],
                "subject": "Release status",
                "established_state": "The source describes a planned release.",
                "must_not_be_upgraded_to": "Already released",
                "attribution": "The assigned source",
            }
        ],
        "tensions_and_caveats": [],
        "creator_opportunities": [],
        "visual_opportunities": [],
    }
    assert model.model_validate(valid_payload).story_id == "story_kimi"

    invalid_detail = json.loads(json.dumps(valid_payload))
    invalid_detail["distinctive_details"][0]["record_key"] = "record_e053ca81a2"
    with pytest.raises(ValueError):
        model.model_validate(invalid_detail)

    invalid_boundary = json.loads(json.dumps(valid_payload))
    invalid_boundary["meaning_boundaries"][0]["record_keys"] = ["record_unknown"]
    with pytest.raises(ValueError):
        model.model_validate(invalid_boundary)


def test_truth_compaction_preserves_semantic_source_notes_and_values() -> None:
    story = {
            "story_id": "story_metrics",
            "records": [
                {
                    "record_key": "record_metrics",
                    "title": "Measured repair results",
                    "url": "https://example.com/results",
                    "source_name": "Example Lab",
                    "content": (
                        "The tool responded in 0.1 ms across 2,568 queries with zero false alarms, "
                        "found an 8× bug, and completed 10/10 repairs. "
                        "The researcher called it “surprisingly practical in production.”"
                    ),
                }
            ],
        }
    source_sentence = story["records"][0]["content"].split(" The researcher", 1)[0]
    index = build_story_truth_index(
        story,
        {
            "story_id": "story_metrics",
            "source_synopsis": "A tool reports measured query-analysis and repair results.",
            "central_event": "The project published a small benchmark.",
            "source_relationship_summary": "One project-authored source reports every result.",
            "distinctive_details": [
                {
                    "record_key": "record_metrics",
                    "detail_type": "metric",
                    "source_note": source_sentence,
                    "value_text": value,
                    "claim_frame": "source_claim",
                    "editorial_use": "A concrete project-reported benchmark detail.",
                    "visual_role": "counter",
                    "visual_opportunity": "Show the exact reported value.",
                }
                for value in ("0.1 ms", "2,568 queries", "zero false alarms", "8×", "10/10")
            ]
            + [
                {
                    "record_key": "record_metrics",
                    "detail_type": "quote",
                    "source_note": "The researcher called it surprisingly practical in production.",
                    "value_text": "surprisingly practical in production.",
                    "claim_frame": "opinion",
                    "editorial_use": "Memorable source wording.",
                    "visual_role": "quote",
                    "visual_opportunity": "Show the exact phrase.",
                }
            ],
            "meaning_boundaries": [],
            "tensions_and_caveats": ["The results are project-reported."],
            "creator_opportunities": ["Contrast speed with the small test scope."],
            "visual_opportunities": ["Animate the reported values."],
        },
    )

    compact = compact_truth_index(index)
    metric_values = [
        item["value_text"]
        for item in compact["items"]
        if item["truth_type"] == "metric"
    ]

    assert set(metric_values) == {"0.1 ms", "2,568 queries", "zero false alarms", "8×", "10/10"}
    semantic_items = [item for item in compact["items"] if item["source_field"] == "semantic_source_brief"]
    assert all(item["classification_basis"] == "llm_semantic_brief" for item in semantic_items)
    assert [item["value_text"] for item in semantic_items if item["truth_type"] == "quote"] == [
        "surprisingly practical in production."
    ]


def test_truth_index_does_not_compare_semantic_notes_with_article_wording() -> None:
    story = {
        "story_id": "story_scraper_spacing",
        "records": [
            {
                "record_key": "record_scraper_spacing",
                "title": "A code migration",
                "url": "https://example.com/migration",
                "source_name": "Example Lab",
                "content": (
                    "Jarred used Claude Code to migrate Bun from Zig to Rust . "
                    "A million lines of code were produced in less than two weeks."
                ),
            }
        ],
    }
    index = build_story_truth_index(
        story,
        {
            "story_id": "story_scraper_spacing",
            "source_synopsis": "The source describes a code migration.",
            "central_event": "Bun was migrated from Zig to Rust.",
            "source_relationship_summary": "One assigned source describes the migration.",
            "distinctive_details": [
                {
                    "record_key": "record_scraper_spacing",
                    "detail_type": "metric",
                    "source_note": (
                        "Jarred used Claude Code to migrate Bun from Zig to Rust. "
                        "A million lines of code were produced in less than two weeks."
                    ),
                    "value_text": "A million lines of code",
                    "claim_frame": "source_claim",
                    "editorial_use": "Use the scale and speed as the concrete story anchor.",
                    "visual_role": "counter",
                    "visual_opportunity": "Show the source-reported scale.",
                }
            ],
            "meaning_boundaries": [],
            "tensions_and_caveats": [],
            "creator_opportunities": ["Contrast the old migration timeline with this source claim."],
            "visual_opportunities": ["Show the source passage."],
        },
    )

    assert len(index.items) == 1
    assert "Rust. A million lines" in index.items[0].source_text
    assert index.items[0].source_field == "semantic_source_brief"


def test_truth_index_preserves_llm_selected_quote_without_punctuation_matching() -> None:
    source_quote = (
        "“Every nation and every company should own and control its intelligence infrastructure. "
        "Open models make that possible,” said Jensen Huang."
    )
    story = {
        "story_id": "story_embedded_quote",
        "records": [
            {
                "record_key": "record_embedded_quote",
                "title": "Open models",
                "url": "https://example.com/open-models",
                "source_name": "Example Lab",
                "content": source_quote,
            }
        ],
    }
    index = build_story_truth_index(
        story,
        {
            "story_id": "story_embedded_quote",
            "source_synopsis": "The source argues for controllable intelligence infrastructure.",
            "central_event": "The organization published new open models.",
            "source_relationship_summary": "One organization-authored source contains the quote.",
            "distinctive_details": [
                {
                    "record_key": "record_embedded_quote",
                    "detail_type": "quote",
                    "source_note": source_quote,
                    "value_text": (
                        '"Every nation and every company should own and control its intelligence '
                        'infrastructure. Open models make that possible."'
                    ),
                    "claim_frame": "opinion",
                    "editorial_use": "Use the speaker's framing as memorable source wording.",
                    "visual_role": "quote",
                    "visual_opportunity": "Show the source-owned quote.",
                }
            ],
            "meaning_boundaries": [],
            "tensions_and_caveats": [],
            "creator_opportunities": ["Explain why infrastructure ownership matters."],
            "visual_opportunities": ["Show the article quote."],
        },
    )

    assert index.items[0].value_text == (
        '"Every nation and every company should own and control its intelligence infrastructure. '
        'Open models make that possible."'
    )


def test_truth_index_does_not_apply_metric_text_matching() -> None:
    story = {
        "story_id": "story_unverified_value",
        "records": [
            {
                "record_key": "record_unverified_value",
                "title": "Measured result",
                "url": "https://example.com/result",
                "content": "The source reports a 40 percent improvement in its own benchmark.",
            }
        ],
    }
    index = build_story_truth_index(
        story,
        {
            "story_id": "story_unverified_value",
            "source_synopsis": "The source reports a benchmark result.",
            "central_event": "A benchmark result was published.",
            "source_relationship_summary": "One project source reports the result.",
            "distinctive_details": [
                {
                    "record_key": "record_unverified_value",
                    "detail_type": "metric",
                    "source_note": "The source reports a 40 percent improvement in its own benchmark.",
                    "value_text": "80 percent",
                    "claim_frame": "source_claim",
                    "editorial_use": "Explain the project-reported benchmark.",
                    "visual_role": "counter",
                    "visual_opportunity": "Show a value only when source-owned.",
                }
            ],
            "meaning_boundaries": [],
            "tensions_and_caveats": [],
            "creator_opportunities": ["Explain the benchmark scope."],
            "visual_opportunities": [],
        },
    )

    assert index.items[0].source_text.startswith("The source reports a 40 percent")
    assert index.items[0].value_text == "80 percent"


def test_truth_index_does_not_filter_semantic_details_by_article_text() -> None:
    story = {
        "story_id": "story_partial_brief",
        "records": [
            {
                "record_key": "record_partial_brief",
                "title": "A useful source",
                "url": "https://example.com/useful-source",
                "content": "The project published a working prototype for early testers.",
            }
        ],
    }
    index = build_story_truth_index(
        story,
        {
            "story_id": "story_partial_brief",
            "source_synopsis": "The source describes a prototype.",
            "central_event": "A prototype was published.",
            "source_relationship_summary": "One assigned source describes the release.",
            "distinctive_details": [
                {
                    "record_key": "record_partial_brief",
                    "detail_type": "event",
                    "source_note": "The project published a working prototype for early testers.",
                    "value_text": "",
                    "claim_frame": "reported_fact",
                    "editorial_use": "Anchor the story in the prototype release.",
                    "visual_role": "source_proof",
                    "visual_opportunity": "Show the release source.",
                },
                {
                    "record_key": "record_partial_brief",
                    "detail_type": "metric",
                    "source_note": "The prototype reached one million users overnight.",
                    "value_text": "one million users",
                    "claim_frame": "source_claim",
                    "editorial_use": "This unsupported detail must not reach the writer.",
                    "visual_role": "counter",
                    "visual_opportunity": "",
                },
            ],
            "meaning_boundaries": [],
            "tensions_and_caveats": [],
            "creator_opportunities": ["Explain what the prototype does."],
            "visual_opportunities": ["Show the source page."],
        },
    )

    assert len(index.items) == 2
    assert index.items[0].truth_type == "event"
    assert index.items[1].value_text == "one million users"
    assert len(index.semantic_source_brief["distinctive_details"]) == 2


def test_review_contract_supports_keep_without_a_revision() -> None:
    keep = StoryReviewOutput.model_validate(
        {
            "rewrite_required": False,
            "issues": [],
            "revised_segment": None,
        }
    )

    assert keep.rewrite_required is False
    assert keep.revised_segment is None
    with pytest.raises(ValueError, match="rewrite_required=false"):
        StoryReviewOutput.model_validate(
            {
                "rewrite_required": False,
                "issues": [
                    {
                        "code": "generic_language",
                        "explanation": "The opening is generic.",
                        "affected_beat_ids": ["beat_01"],
                    }
                ],
                "revised_segment": None,
            }
        )


def test_removed_candidate_selection_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="candidate_selection"):
        ReviewConfig.model_validate(
            {
                "enabled": True,
                "max_revision_passes": 1,
                "candidate_selection": {"enabled": False},
            }
        )


def test_llm_call_retries_a_transient_rate_limit(monkeypatch) -> None:
    class Response:
        status_code = 429
        headers = {"retry-after-ms": "26"}

    class RateLimitError(Exception):
        status_code = 429
        response = Response()

    class FakeLLM:
        attempts = 0

        def with_structured_output(self, model, **_kwargs):
            def invoke(_prompt):
                self.attempts += 1
                if self.attempts == 1:
                    raise RateLimitError("Please try again in 26ms")
                payload = {
                    "episode_shape": "curated_roundup",
                    "episode_connection_reason": "The fixture contains one independent story.",
                    "episode_thesis": "A connected episode thesis.",
                    "viewer_promise": "A useful viewer promise.",
                    "hook_strategy": "Open on the consequence.",
                    "pacing_strategy": "Move through stories clearly.",
                    "ordered_story_ids": ["story_one"],
                    "story_briefs": [
                        {
                            "story_id": "story_one",
                            "story_engine": "practical_consequence",
                            "story_promise": "Explain the development.",
                            "hook_idea": "Open on the practical problem.",
                            "tension": "The workflow can lose context.",
                            "reveal_or_payoff": "A stable contract keeps it attached.",
                            "viewer_stakes": "The final output stays coherent.",
                            "specific_detail_anchor": "The handoff preserves context between stages.",
                            "source_meaning_boundary": "A contract preserves supplied context; it does not guarantee creative quality.",
                            "source_meaning_boundaries": [],
                            "must_communicate_truth_ids": [],
                            "optional_truth_ids": [],
                            "narrator_take": "Structure is the unglamorous advantage.",
                            "explanation_goal": "Make the workflow easy to picture.",
                            "analogy_opportunities": [],
                            "humor_opportunities": [],
                            "humor_restraint_reason": None,
                            "transition_relationship": "Begin clearly.",
                            "visual_payoffs": [],
                            "avoid": [],
                        }
                    ],
                }
                return {"raw": None, "parsed": model.model_validate(payload), "parsing_error": None}

            return RunnableLambda(invoke)

    delays: list[float] = []
    monkeypatch.setattr(script_writer.time, "sleep", delays.append)
    llm = FakeLLM()
    calls: list[dict] = []

    output = script_writer._invoke_chain(
        module_name="roundup_director",
        output_model=EpisodeDirectorOutput,
        llm=llm,
        prompt_bundle={"system": "System", "user_preamble": "User"},
        task_payload="{}",
        script_cfg={
            "provider": "openai",
            "model": "fake-model",
            "llm_retry": {
                "enabled": True,
                "max_attempts": 3,
                "initial_delay_seconds": 1.0,
                "max_delay_seconds": 10.0,
            },
        },
        metadata={},
        llm_calls=calls,
    )

    assert output.ordered_story_ids == ["story_one"]
    assert llm.attempts == 2
    assert delays == [1.0]
    assert calls[0]["metadata"]["attempt_count"] == 2
    assert calls[0]["metadata"]["retry_count"] == 1
    assert calls[0]["metadata"]["retry_errors"][0]["status_code"] == 429


def test_content_filter_rejection_uses_explicit_provider_fallback() -> None:
    class ProviderContentFilterError(Exception):
        status_code = 400

    class RejectingLLM:
        def with_structured_output(self, _model, **_kwargs):
            def invoke(_prompt):
                raise ProviderContentFilterError(
                    "The request was rejected because it was considered highrisk: content_filter"
                )

            return RunnableLambda(invoke)

    class WorkingLLM:
        def with_structured_output(self, model, **_kwargs):
            def invoke(_prompt):
                payload = {
                    "episode_shape": "curated_roundup",
                    "episode_connection_reason": "The stories are intentionally independent.",
                    "episode_thesis": "A concise episode direction.",
                    "viewer_promise": "A useful viewer promise.",
                    "hook_strategy": "Open on the strongest consequence.",
                    "pacing_strategy": "Keep each story distinct.",
                    "ordered_story_ids": ["story_one"],
                    "story_briefs": [
                        {
                            "story_id": "story_one",
                            "story_engine": "practical_consequence",
                            "story_promise": "Explain the development.",
                            "hook_idea": "Open on the practical effect.",
                            "tension": "The result changes an existing workflow.",
                            "reveal_or_payoff": "The consequence is concrete.",
                            "viewer_stakes": "The viewer can understand what changes.",
                            "specific_detail_anchor": "One supplied source detail.",
                            "source_meaning_boundary": "Preserve the supplied source state.",
                            "source_meaning_boundaries": [],
                            "must_communicate_truth_ids": [],
                            "optional_truth_ids": [],
                            "narrator_take": "The practical effect matters most.",
                            "explanation_goal": "Make the consequence easy to follow.",
                            "analogy_opportunities": [],
                            "humor_opportunities": [],
                            "humor_restraint_reason": None,
                            "transition_relationship": "Begin clearly.",
                            "visual_payoffs": [],
                            "avoid": [],
                        }
                    ],
                }
                return {"raw": None, "parsed": model.model_validate(payload), "parsing_error": None}

            return RunnableLambda(invoke)

    calls: list[dict] = []
    output = script_writer._invoke_runtime_chain(
        module_name="roundup_director",
        output_model=EpisodeDirectorOutput,
        llm_runtime={
            "llm": RejectingLLM(),
            "config": {
                "provider": "moonshot",
                "model": "kimi-k3",
                "structured_output": {"method": "json_schema", "strict": True},
                "llm_retry": {"enabled": True, "max_attempts": 1},
            },
            "content_filter_fallback": {
                "llm": WorkingLLM(),
                "config": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "structured_output": {"method": "json_schema", "strict": True},
                    "llm_retry": {"enabled": True, "max_attempts": 1},
                },
            },
        },
        prompt_bundle={"system": "System", "user_preamble": "User"},
        task_payload="{}",
        metadata={"story_id": "story_one"},
        llm_calls=calls,
    )

    assert output.ordered_story_ids == ["story_one"]
    assert [call["provider"] for call in calls] == ["moonshot", "openai"]
    assert calls[0]["metadata"]["route_attempt"] == "primary"
    assert calls[0]["metadata"]["parse_error"]
    assert calls[1]["metadata"] == {
        "story_id": "story_one",
        "route_attempt": "content_filter_fallback",
        "fallback_trigger": "content_filter",
        "fallback_from_provider": "moonshot",
        "fallback_from_model": "kimi-k3",
        "attempt_count": 1,
        "retry_count": 0,
    }


def test_video_packaging_does_not_reapply_semantic_duplicate_rules() -> None:
    stories = _json("video_packaging_result.json")["data"]["video_packet"]["stories"]
    duplicate = json.loads(json.dumps(stories[0]))
    duplicate["story_id"] = "story_duplicate"
    duplicate["rank"] = 2
    duplicate["story_title"] = "A second article about the same event"
    stories[1]["rank"] = 3
    stories[2]["rank"] = 4
    selected = [stories[0], duplicate, stories[1], stories[2]]
    for order, (story, role) in enumerate(zip(selected, ["lead", "major", "brief", "brief"], strict=True), start=1):
        story["editorial_selection"] = {
            "story_id": story["story_id"],
            "role": role,
            "selection_order": order,
            "selection_reason": "Selected by the semantic editorial selector.",
        }
    result = build_roundup_packet(
        {
            "episode_shape": "mixed_news_roundup",
            "episode_thesis": "",
            "ordering_rationale": "Selector-owned order.",
            "selected_stories": selected,
            "reserve": [],
            "rejected": [],
        },
        {"min_stories": 3, "max_stories": 5, "duration_mode": "content_driven"},
    )

    assert result["packet"]["selected_story_ids"] == [
        "story_evidence",
        "story_duplicate",
        "story_sync",
        "story_render",
    ]
    assert result["selection_stats"]["selection_authority"] == "editorial_selection_llm"


def test_content_driven_section_plan_uses_soft_role_guidance() -> None:
    packet = _json("video_packaging_result.json")["data"]["video_packet"]
    config = {
        "script_style": {"audience": "AI-curious professionals", "tone": "clear", "avoid": []},
        "writing_guidance": {
            "intro": {"suggested_words": 60, "beat_guidance": "Focused opening.", "editorial_goal": "Hook."},
            "lead": {"suggested_words": 220, "beat_guidance": "Natural beats.", "editorial_goal": "Explain."},
            "major": {"suggested_words": 170, "beat_guidance": "Compact beats.", "editorial_goal": "Clarify."},
            "brief": {"suggested_words": 100, "beat_guidance": "Few beats.", "editorial_goal": "Update."},
            "closing": {"suggested_words": 40, "beat_guidance": "One beat.", "editorial_goal": "Synthesize."},
            "connector": {"suggested_words": 8, "beat_guidance": "One line.", "editorial_goal": "Connect."},
        },
    }

    sections = build_roundup_section_inputs(packet, config)

    assert [section["section_type"] for section in sections] == ["intro", "story", "story", "story", "closing"]
    assert sections[0]["writing_guidance"]["suggested_words"] == 60
    assert sections[1]["writing_guidance"]["suggested_words"] == 220
    assert sections[2]["writing_guidance"]["suggested_words"] == 170
    assert sections[3]["writing_guidance"]["suggested_words"] == 170
    assert sections[-1]["writing_guidance"]["suggested_words"] == 40
    assert all(section["writing_guidance"]["enforcement"] == "soft_editorial_guidance_only" for section in sections)
    assert all("budget_contract" not in section for section in sections)
    assert all("target_seconds" not in section for section in sections)


def test_video_packaging_emits_roles_without_script_timing_allocations() -> None:
    stories = _json("video_packaging_result.json")["data"]["video_packet"]["stories"]
    for order, story in enumerate(stories, start=1):
        story["editorial_selection"] = {
            "story_id": story["story_id"],
            "role": story["video_segment"]["role"],
            "selection_order": order,
            "selection_reason": "Selected by the semantic editorial selector.",
        }
    slate = {
        "episode_shape": "mixed_news_roundup",
        "episode_thesis": "",
        "ordering_rationale": "Selector-owned order.",
        "selected_stories": stories,
        "reserve": [],
        "rejected": [],
    }
    config = {"min_stories": 3, "max_stories": 5, "duration_mode": "content_driven", "duration_ceiling_seconds": 480}

    packet = build_roundup_packet(slate, config)["packet"]

    assert packet["duration_policy"] == {
        "mode": "content_driven",
        "configured_ceiling_seconds": 480,
        "timing_source_of_truth": "voiceover",
    }
    assert [story["video_segment"]["role"] for story in packet["stories"]] == ["lead", "major", "major"]
    assert all("target_seconds" not in story["video_segment"] for story in packet["stories"])
    assert "target_duration_seconds" not in packet


def test_script_checks_do_not_reject_observed_duration_drift() -> None:
    video_packet = _json("video_packaging_result.json")["data"]["video_packet"]
    package = _json("script_generation_result.json")["data"]["script_package"]
    package["review"]["story_reviews"] = []
    package["full_script_stats"]["estimated_duration_seconds"] = 20.0

    checks = check_script_package(package, video_packet)

    assert checks["passed"] is True
    assert not any("duration drift" in error for error in checks["errors"])


def test_script_checks_do_not_apply_semantic_or_craft_scoring() -> None:
    video_packet = _json("video_packaging_result.json")["data"]["video_packet"]
    package = _json("script_generation_result.json")["data"]["script_package"]
    package["review"]["story_reviews"] = [
        {
            "story_id": "story_evidence",
            "passes": [],
            "final_gate_issues": [],
            "final_craft_diagnostics": ["generic_story_hook:['in a world where']"],
        }
    ]
    package["review"]["bookend_final_gate_issues"] = []
    package["review"]["bookend_final_craft_diagnostics"] = ["formulaic_connector_sequence:3"]

    checks = check_script_package(package, video_packet)

    assert checks["passed"] is True
    assert checks["warnings"] == []
    assert checks["validation_scope"] == "structural_integrity_and_provenance_only"


def test_manual_chatgpt_script_normalizes_to_canonical_beats() -> None:
    result = _canonical_manual_script()
    ScriptGenerationResponse.model_validate(result)
    package = result["data"]["script_package"]

    assert result["status"] == "ok"
    assert package["generation_strategy"] == "manual_story_sections_normalized_to_audiovisual_beats"
    assert len(package["sections"]) == 5
    assert package["full_script_stats"]["beat_count"] == 12
    assert len(package["audio_plan"]["units"]) == 5
    assert len(package["story_asset_hints"]) == 3
    assert all(item["source_pages"] for item in package["story_asset_hints"])
    for section in package["sections"]:
        assert section["narration_text"] == " ".join(beat["narration_text"] for beat in section["beats"])
        assert [beat["beat_order"] for beat in section["beats"]] == list(range(1, len(section["beats"]) + 1))
        assert "target_seconds" not in section
        assert "word_budget" not in section
        if section["section_type"] == "story":
            assert section["title_card"]["voice_behavior"] == "continue"
            assert section["title_card"]["anchor_beat_id"] == section["beats"][0]["beat_id"]
    assert result["handoff"] == {
        "ready_for_metadata_creation": True,
        "ready_for_voiceover": True,
        "ready_for_visual_planning": True,
    }


def test_native_script_generation_uses_director_story_writers_and_bookends(monkeypatch) -> None:
    video = _json("video_packaging_result.json")
    stories = video["data"]["video_packet"]["stories"]
    story_ids = [story["story_id"] for story in stories]
    titles = {story["story_id"]: story["story_title"] for story in stories}
    source_keys = {story["story_id"]: story["records"][0]["record_key"] for story in stories}
    records_by_story = {story["story_id"]: story["records"] for story in stories}

    class FakeLLM:
        def with_structured_output(self, model, include_raw=True, **kwargs):
            assert include_raw is True
            assert kwargs == {"method": "json_schema", "strict": True}

            def invoke(prompt):
                prompt_text = prompt.to_string() if hasattr(prompt, "to_string") else str(prompt)
                if issubclass(model, StorySourceBriefOutput):
                    task_payload = json.loads(prompt_text.split("Task payload:\n", 1)[1])
                    context = task_payload["complete_story_context"]
                    story_id = task_payload["required_story_id"]
                    assert context["story_id"] == story_id
                    assert context["records"]
                    assert context["records"] == records_by_story[story_id]
                    record = context["records"][0]
                    payload = {
                        "story_id": story_id,
                        "source_synopsis": "The source describes one stage in a media workflow.",
                        "central_event": "A workflow stage passes structured context downstream.",
                        "source_relationship_summary": "One assigned source provides the fixture context.",
                        "distinctive_details": [
                            {
                                "record_key": record["record_key"],
                                "detail_type": "event",
                                "source_note": record["title"],
                                "value_text": "",
                                "claim_frame": "reported_fact",
                                "editorial_use": "Use the exact fixture event as the story anchor.",
                                "visual_role": "source_proof",
                                "visual_opportunity": "Show the assigned source title.",
                            }
                        ],
                        "meaning_boundaries": [],
                        "tensions_and_caveats": [],
                        "creator_opportunities": ["Explain the handoff as a relay."],
                        "visual_opportunities": ["Show context moving between stages."],
                    }
                elif model is EpisodeDirectorOutput:
                    task_payload = json.loads(prompt_text.split("Task payload:\n", 1)[1])
                    assert all(item["records"] for item in task_payload["story_context_packets"])
                    truth_ids = {
                        item["story_id"]: item["story_truth_index"]["items"][0]["truth_id"]
                        for item in task_payload["story_context_packets"]
                    }
                    payload = {
                        "episode_shape": "shared_tension",
                        "episode_connection_reason": "Each fixture story concerns context moving between media stages.",
                        "episode_thesis": "Evidence and timing keep automated media coherent.",
                        "viewer_promise": "See how the pieces connect.",
                        "hook_strategy": "Open on the synchronization problem.",
                        "pacing_strategy": "Move from evidence to timing to rendering.",
                        "ordered_story_ids": story_ids,
                        "story_briefs": [
                            {
                                "story_id": story_id,
                                "story_engine": "practical_consequence",
                                "story_promise": f"Explain {story_id}.",
                                "hook_idea": "Open on the production failure this prevents.",
                                "tension": "Disconnected stages force downstream guesses.",
                                "reveal_or_payoff": "A shared contract keeps the active story aligned.",
                                "viewer_stakes": "The explanation and screen can agree.",
                                "specific_detail_anchor": "The shared contract keeps one active story attached to its media.",
                                "source_meaning_boundary": "The contract preserves identity and timing, not the semantic quality of generated content.",
                                "source_meaning_boundaries": [],
                                "must_communicate_truth_ids": [truth_ids[story_id]],
                                "optional_truth_ids": [],
                                "narrator_take": "Reliable handoffs are more useful than flashy glue code.",
                                "explanation_goal": "Make the contract handoff easy to picture.",
                                "analogy_opportunities": ["Treat the contract like a relay baton."],
                                "humor_opportunities": [],
                                "humor_restraint_reason": None,
                                "transition_relationship": "Advance the shared production chain.",
                                "visual_payoffs": ["Show context moving between stages."],
                                "avoid": ["hype"],
                            }
                            for story_id in story_ids
                        ],
                    }
                elif model is StorySegmentOutput:
                    task_payload = json.loads(prompt_text.split("Task payload:\n", 1)[1])
                    story_id = task_payload["required_story_id"]
                    truth_id = task_payload["director_brief"]["must_communicate_truth_ids"][0]
                    assert task_payload["writing_guidance"]["enforcement"] == "soft_editorial_guidance_only"
                    assert "body_beat_contract" not in task_payload
                    assert "body_word_contract" not in task_payload
                    packet = task_payload["story_context_packet"]
                    assert packet["story_id"] == story_id
                    assert packet["semantic_source_brief"]["distinctive_details"]
                    assert packet["records"] == records_by_story[story_id]

                    function_by_type = {
                        "what_changed": "reveal",
                        "explanation": "explanation",
                        "takeaway": "payoff",
                    }
                    delivery = {
                        "performance_intent": "Make the workflow consequence easy to follow.",
                        "emotional_color": "curious and confident",
                        "pace": "conversational",
                        "energy": "engaged",
                        "emphasis_phrases": [],
                        "pause_after": "micro",
                    }

                    def beat(beat_type: str, narration: str) -> dict:
                        return {
                            "beat_type": beat_type,
                            "beat_function": function_by_type[beat_type],
                            "narration_text": narration,
                            "support_truth_ids": [truth_id],
                            "creative_device": "contrast" if beat_type == "takeaway" else "none",
                            "visual_goal": "Make the concrete workflow relationship visible.",
                            "source_record_keys": [source_keys[story_id]],
                            "delivery_direction": delivery,
                            "visual_brief": {
                                "purpose": "Show the concrete mechanism.",
                                "visual_intent": "source_proof",
                                "preferred_asset_types": ["source_page", "diagram"],
                                "must_show": ["evidence"],
                                "on_screen_text": "",
                                "avoid": ["paragraph text"],
                            },
                        }

                    payload = {
                        "story_id": story_id,
                        "display_title": titles[story_id],
                        "story_thesis": "A grounded workflow matters.",
                        "viewer_takeaway": "Structure keeps media aligned.",
                        "beats": [
                            beat("what_changed", "This stage keeps every selected source attached while the story moves through the production workflow for later use."),
                            beat("explanation", "That shared context gives the writer and visual planner the same concrete development instead of forcing either tool to guess."),
                            beat("takeaway", "The practical result is a cleaner handoff, clearer timing, and a final segment whose visuals can follow the narration closely."),
                        ],
                    }
                elif model is StoryReviewOutput:
                    task_payload = json.loads(prompt_text.split("Task payload:\n", 1)[1])
                    assert task_payload["quality_criteria"]
                    assert "body_word_contract" not in task_payload
                    assert task_payload["story_context_packet"]["story_id"] in story_ids
                    assert task_payload["story_context_packet"]["records"]
                    assert "structural_issues" not in task_payload
                    assert "craft_diagnostics" not in task_payload
                    assert task_payload["beat_support_context"]
                    if task_payload["required_story_id"] == story_ids[0]:
                        revised_segment = task_payload["current_segment"]
                        revised_segment["beats"][0]["narration_text"] = (
                            "The reviewer makes this first concrete handoff easier to picture without changing its source ownership."
                        )
                        payload = {
                            "rewrite_required": True,
                            "issues": [
                                {
                                    "code": "unclear_explanation",
                                    "explanation": "The first beat can state the handoff more directly.",
                                    "affected_beat_ids": ["beat_01"],
                                }
                            ],
                            "revised_segment": revised_segment,
                        }
                    else:
                        payload = {
                            "rewrite_required": False,
                            "issues": [],
                            "revised_segment": None,
                        }
                elif model is BookendOutput:
                    delivery = {
                        "performance_intent": "Keep the episode moving with clear curiosity.",
                        "emotional_color": "intrigued",
                        "pace": "brisk",
                        "energy": "animated",
                        "emphasis_phrases": [],
                        "pause_after": "short",
                    }
                    visual = {
                        "purpose": "Keep the episode moving.",
                        "visual_intent": "transition",
                        "preferred_asset_types": ["kinetic_text"],
                        "must_show": ["connected stages"],
                        "on_screen_text": "SOURCE TO SCREEN",
                        "avoid": ["paragraph text"],
                    }
                    payload = {
                        "intro_beats": [
                            {
                                "beat_type": "hook",
                                "narration_text": "Automated video falls apart when writing, audio, and visuals disagree about the story playing right now.",
                                "delivery_direction": delivery,
                                "visual_brief": visual,
                            },
                            {
                                "beat_type": "intro",
                                "narration_text": "Here is how one evidence-first workflow keeps those moving parts connected from source material to the final screen.",
                                "delivery_direction": delivery,
                                "visual_brief": visual,
                            },
                        ],
                        "story_connectors": [
                            {
                                "target_story_id": story_id,
                                "display_title": titles[story_id],
                                "transition_line": "Next, another production problem comes into focus.",
                                "title_card_subtitle": "Evidence to screen",
                                "delivery_direction": delivery,
                            }
                            for story_id in story_ids
                        ],
                        "closing_beats": [
                            {
                                "beat_type": "conclusion",
                                "narration_text": "The real advantage is not any single model or renderer; it is the shared beat contract that lets every stage improve without losing the story.",
                                "delivery_direction": delivery,
                                "visual_brief": visual,
                            }
                        ],
                        "continuity_notes": ["Keep narration moving under story titles."],
                    }
                elif model is BookendReviewOutput:
                    task_payload = json.loads(prompt_text.split("Task payload:\n", 1)[1])
                    assert task_payload["quality_criteria"]
                    assert "intro_budget_contract" not in task_payload
                    payload = {
                        "rewrite_required": False,
                        "issues": [],
                        "revised_bookends": None,
                    }
                else:
                    raise AssertionError(f"Unexpected structured output model: {model}")
                return {"raw": None, "parsed": model.model_validate(payload), "parsing_error": None}

            return RunnableLambda(invoke)

    monkeypatch.setattr(script_app, "make_llm", lambda **_kwargs: FakeLLM())
    result = script_app.run(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {
                "provider": "openai",
                "model": "fake-structured-model",
                "prompt_version": "v1",
                "temperature": 0.2,
                "diagnostic_words_per_minute": 150,
                "worker_count": 2,
                "title_card_seconds": 2.8,
                "script_style": {
                    "audience": "AI-curious professionals",
                    "tone": "clear, energetic, grounded",
                    "avoid": ["hype"],
                },
                "source_policy": {"use_selected_stories_only": True, "include_full_records": True},
                "review": {
                    "enabled": True,
                    "max_revision_passes": 1,
                },
            },
            "input": {"video_packaging": video},
        }
    )

    package = result["data"]["script_package"]
    assert result["status"] == "ok"
    assert package["generation_strategy"] == "director_plus_per_story_beats_plus_bookends"
    assert package["full_script"] == "\n\n".join(section["narration_text"] for section in package["sections"])
    assert len(package["audio_plan"]["units"]) == 5
    assert all(section["beats"] for section in package["sections"])
    assert len(package["story_truth_indexes"]) == 3
    assert len(package["story_context_packets"]) == 3
    assert package["review"]["review_call_count"] == 4
    assert package["review"]["revision_count"] == 1
    assert "The reviewer makes this first concrete handoff" in package["full_script"]
    assert all(index["items"] for index in package["story_truth_indexes"])
    assert all(
        beat["beat_function"] and "support_truth_ids" in beat and beat["visual_goal"]
        for section in package["sections"]
        for beat in section["beats"]
    )
    assert all(
        section["title_card"]["voice_behavior"] == "continue"
        for section in package["sections"]
        if section["section_type"] == "story"
    )
    assert result["summary"]["content_policy"]["word_counts_are_approval_gates"] is False
    assert result["summary"]["content_policy"]["timing_source_of_truth"] == "voiceover"
    assert result["summary"]["llm_runtime"]["parallelized_steps"] == [
        "roundup_source_researcher",
        "roundup_story_writer",
    ]
    assert result["summary"]["llm_runtime"]["serial_steps"] == [
        "roundup_director",
        "roundup_bookend_writer",
    ]
    modules = [call["module_name"] for call in result["llm_calls"]]
    assert modules[:3] == ["roundup_source_researcher"] * 3
    assert modules[3] == "roundup_director"
    assert modules.count("roundup_story_writer") == 3
    assert modules.count("roundup_story_reviewer") == 3
    assert modules[-2:] == ["roundup_bookend_writer", "roundup_bookend_reviewer"]
    assert not {"roundup_full_script_writer", "roundup_script_reviser"} & set(modules)


def test_script_checks_reject_unknown_source_ownership() -> None:
    video_packet = _json("video_packaging_result.json")["data"]["video_packet"]
    package = _json("script_generation_result.json")["data"]["script_package"]
    story_section = next(section for section in package["sections"] if section["section_type"] == "story")
    story_section["used_source_record_keys"].append("record_not_selected")

    checks = check_script_package(package, video_packet)

    assert checks["passed"] is False
    assert any("unknown source record keys" in error for error in checks["errors"])


def test_voiceover_preserves_script_beat_identity(monkeypatch, tmp_path: Path) -> None:
    script = _canonical_manual_script()
    request = VoiceoverRequest.model_validate(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {
                "provider": "kokoro_local",
                "style": "general_youtube",
                "output_dir": str(tmp_path / "voiceover"),
                "alignment": {
                    "require_script_beats": True,
                    "beat_pause_seconds": 0.08,
                    "section_pause_seconds": 0.32,
                },
            },
            "input": {"script_generation": script},
        }
    )
    resolved = voice_script_units.resolve_script_input(
        request,
        {
            "max_chars": 900,
            "max_sentences_per_chunk": 4,
            "chunk_pause_seconds": 0.12,
            "paragraph_pause_seconds": 0.38,
        },
    )

    assert resolved["alignment_strategy"] == "script_beats"
    assert len(resolved["chunks"]) == 12
    assert len({chunk["audio_unit_id"] for chunk in resolved["chunks"]}) == 5
    assert len({chunk["beat_id"] for chunk in resolved["chunks"]}) == 12
    assert all(chunk["beat_function"] for chunk in resolved["chunks"])
    assert all("creative_device" in chunk and "visual_goal" in chunk for chunk in resolved["chunks"])

    cursor = 0.0
    synthesized = []
    for chunk in resolved["chunks"]:
        duration = max(0.8, chunk["word_count"] / 2.5)
        synthesized.append(
            {
                **chunk,
                "audio_path": str(tmp_path / f"{chunk['chunk_id']}.wav"),
                "duration_seconds": duration,
                "start_seconds": cursor,
                "end_seconds": cursor + duration,
            }
        )
        cursor += duration + chunk["pause_after_seconds"]
    monkeypatch.setattr(
        voice_script_units,
        "concatenate_wav_files",
        lambda input_paths, output_path, sample_rate_hz, pauses_after_seconds: sum(
            synthesized[index]["duration_seconds"] + (pauses_after_seconds[index] if index < len(pauses_after_seconds) - 1 else 0)
            for index in range(len(input_paths))
        ),
    )
    units = voice_script_units.build_audio_units(
        synthesized_chunks=synthesized,
        output_dir=tmp_path / "units",
        sample_rate_hz=24000,
    )

    assert len(units) == 5
    assert sum(len(unit["aligned_beats"]) for unit in units) == 12
    assert all(unit["start_seconds"] < unit["end_seconds"] for unit in units)
    assert all(
        beat["start_seconds"] < beat["end_seconds"]
        for unit in units
        for beat in unit["aligned_beats"]
    )


def test_voiceover_app_writes_section_audio_units(monkeypatch, tmp_path: Path) -> None:
    durations: dict[str, float] = {}

    def write_wav(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(b"\x00\x00" * 240)

    def synthesize(**kwargs) -> dict:
        path = Path(kwargs["output_path"])
        write_wav(path)
        duration = max(0.4, len(kwargs["text"].split()) / 3.0)
        durations[str(path)] = duration
        return {"audio_path": str(path), "duration_seconds": duration, "sample_rate_hz": 24000}

    def concatenate(*, input_paths, output_path, sample_rate_hz, pauses_after_seconds=None) -> float:
        pauses = pauses_after_seconds or [0.0] * len(input_paths)
        duration = sum(
            durations.get(str(path), 0.4) + (pauses[index] if index < len(input_paths) - 1 else 0.0)
            for index, path in enumerate(input_paths)
        )
        write_wav(Path(output_path))
        durations[str(output_path)] = duration
        return duration

    monkeypatch.setattr(voice_app, "synthesize_kokoro_chunk_to_wav", synthesize)
    monkeypatch.setattr(voice_app, "concatenate_wav_files", concatenate)
    monkeypatch.setattr(voice_script_units, "concatenate_wav_files", concatenate)
    output_dir = tmp_path / "voiceover"
    result = voice_app.run(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {
                "provider": "kokoro_local",
                "style": "general_youtube",
                "voice": "af_heart",
                "speed": 1.0,
                "language_code": "a",
                "sample_rate_hz": 24000,
                "keep_chunks": True,
                "force": True,
                "output_dir": str(output_dir),
                "alignment": {
                    "require_script_beats": True,
                    "beat_pause_seconds": 0.08,
                    "section_pause_seconds": 0.32,
                },
            },
            "input": {"script_generation": _json("script_generation_result.json")},
        }
    )

    package = result["data"]["voiceover_package"]
    validate_artifact_provenance(
        package["provenance"],
        artifact_type="voiceover",
        run_id="fixture_media_roundup_reference",
        payload=voiceover_artifact_payload(package),
        label="voiceover",
    )
    assert result["status"] == "ok"
    assert result["summary"]["audio_unit_count"] == 5
    assert result["summary"]["aligned_beat_count"] == 12
    assert len(package["audio_units"]) == 5
    assert (output_dir / "audio" / "full_voiceover.wav").exists()
    assert len(list((output_dir / "audio" / "units").glob("*.wav"))) == 5
    assert (output_dir / "tts_requests.jsonl").exists()
    assert result["summary"]["tts_request_count"] == len(package["chunks"])
    assert result["summary"]["delivery_direction_coverage"]["direction_applied_chunk_count"] == 0


def test_visual_planner_prefers_aligned_beats_and_exact_sections() -> None:
    script = _canonical_manual_script()
    sections = script["data"]["script_package"]["sections"]
    aligned_beats = []
    cursor = 0.0
    for section in sections:
        for beat in section["beats"]:
            duration = max(1.0, beat["estimated_seconds"])
            aligned_beats.append(
                {
                    "beat_id": beat["beat_id"],
                    "beat_order": beat["beat_order"],
                    "beat_type": beat["beat_type"],
                    "section_id": section["section_id"],
                    "story_id": section["story_id"],
                    "text": beat["narration_text"],
                    "word_count": beat["word_count"],
                    "start_seconds": cursor,
                    "end_seconds": cursor + duration,
                }
            )
            cursor += duration
    audio_units = []
    for unit_order, section in enumerate(sections, start=1):
        section_beats = [beat for beat in aligned_beats if beat["section_id"] == section["section_id"]]
        audio_units.append(
            {
                "audio_unit_id": f"audio_{section['section_id']}",
                "unit_order": unit_order,
                "section_id": section["section_id"],
                "section_type": section["section_type"],
                "story_id": section["story_id"],
                "story_title": section["story_title"],
                "aligned_beats": section_beats,
            }
        )
    package = {"package_type": "voiceover_package", "audio_units": audio_units, "chunks": []}
    units = voiceover_chunks(package)

    assert len(units) == len(aligned_beats)
    assert all(unit["timing_source"] == "voiceover_aligned_beat" for unit in units)
    stories = _json("video_packaging_result.json")["data"]["video_packet"]["stories"]
    mapped = _sections_from_script_generation_sections(sections, units, stories)
    assert [section["section_id"] for section in mapped] == [section["section_id"] for section in sections]
    assert all(
        section["assignment_method"] == "canonical_script_beats_with_voiceover_alignment"
        for section in mapped
    )


def test_visual_preview_preserves_canonical_beats_without_voiceover() -> None:
    script = _json("script_generation_result.json")
    package = script["data"]["script_package"]

    units = _build_script_units(
        script_text=package["full_script"],
        voiceover_package=None,
        script_sections=package["sections"],
        words_per_minute=150,
    )

    expected_beats = [beat for section in package["sections"] for beat in section["beats"]]
    assert len(units) == len(expected_beats)
    assert [unit["beat_id"] for unit in units] == [beat["beat_id"] for beat in expected_beats]
    assert all(unit["timing_source"] == "script_beat_estimate" for unit in units)
    assert all(unit["section_id"] for unit in units)


def test_visual_slicer_bounds_long_beats_and_preserves_section_titles() -> None:
    policy = {
        "compact_per_chunk_scenes": True,
        "max_scene_seconds": 14,
        "min_scene_seconds": 3,
        "semantic_min_scene_seconds": 5,
        "semantic_target_scene_seconds": 9,
        "semantic_max_units_per_scene": 4,
        "max_scenes": 64,
    }
    slices = _unit_time_slices(
        1,
        2,
        [
            {"order": 1, "start_seconds": 0.0, "end_seconds": 7.2, "text": "First aligned beat."},
            {"order": 2, "start_seconds": 7.2, "end_seconds": 14.8, "text": "Second aligned beat."},
        ],
        policy,
    )
    assert len(slices) == 2
    assert all(item["end_seconds"] - item["start_seconds"] <= 14 for item in slices)

    scenes = [
        {
            "story_id": "",
            "section_type": "intro",
            "start_seconds": 0.0,
            "end_seconds": 1.0,
            "duration_seconds": 1.0,
            "render_kind": "editorial_text_scene",
            "covered_unit_orders": [1],
            "payload": {},
        },
        {
            "story_id": "story_evidence",
            "section_type": "story",
            "start_seconds": 1.0,
            "end_seconds": 3.8,
            "duration_seconds": 2.8,
            "render_kind": "story_transition_scene",
            "covered_unit_orders": [2],
            "payload": {"voice_behavior": "continue"},
        },
    ]
    assert len(_compact_scene_timeline(scenes, policy)) == 2


def test_chatgpt_visual_parser_uses_aligned_units_and_inserts_story_titles() -> None:
    script = _json("script_generation_result.json")
    video = _json("video_packaging_result.json")
    sections = script["data"]["script_package"]["sections"]
    cursor = 0.0
    audio_units = []
    scene_timeline = []
    global_order = 0
    for unit_order, section in enumerate(sections, start=1):
        aligned_beats = []
        section_orders = []
        for beat in section["beats"]:
            global_order += 1
            duration = max(1.0, float(beat["estimated_seconds"]))
            aligned_beats.append(
                {
                    "beat_id": beat["beat_id"],
                    "beat_order": beat["beat_order"],
                    "beat_type": beat["beat_type"],
                    "section_id": section["section_id"],
                    "story_id": section["story_id"],
                    "text": beat["narration_text"],
                    "word_count": beat["word_count"],
                    "start_seconds": cursor,
                    "end_seconds": cursor + duration,
                }
            )
            section_orders.append(global_order)
            cursor += duration
        audio_units.append(
            {
                "unit_order": unit_order,
                "section_id": section["section_id"],
                "section_type": section["section_type"],
                "story_id": section["story_id"],
                "story_title": section["story_title"],
                "aligned_beats": aligned_beats,
            }
        )
        scene_timeline.append(
            {
                "scene_id": f"draft_{unit_order}",
                "scene_order": unit_order,
                "story_id": section["story_id"],
                "section_type": section["section_type"],
                "start_seconds": 900 + unit_order,
                "end_seconds": 901 + unit_order,
                "render_kind": "editorial_text_scene",
                "script_excerpt": section["narration_text"],
                "visual_intent": "Explain the active section.",
                "payload": {
                    "recipe_id": "editorial_hook",
                    "headline": section["story_title"] or section["section_type"],
                    "accent_words": [],
                    "supporting_text": "",
                    "composition": "editorial_center",
                    "motion_style": "word_reveal",
                },
                "evidence_record_keys": [],
                "evidence_text": "",
                "grounding_basis": "script_beat",
                "covered_unit_orders": section_orders,
            }
        )
    voiceover = {
        "run_id": "fixture_media_roundup_reference",
        "package_type": "voiceover_package",
        "audio": {"duration_seconds": cursor, "full_audio_path": "fixture.wav"},
        "audio_units": audio_units,
        "chunks": [],
    }
    script_fingerprint = script["data"]["script_package"]["provenance"]["script_fingerprint"]
    audio_sha256 = f"sha256:{'0' * 64}"
    voiceover["provenance"] = {"audio_sha256": audio_sha256}
    voiceover["provenance"] = build_artifact_provenance(
        artifact_type="voiceover",
        run_id="fixture_media_roundup_reference",
        parents={"script": script_fingerprint},
        payload=voiceover_artifact_payload(voiceover),
    )
    voiceover["provenance"]["audio_sha256"] = audio_sha256
    response_text = "\n".join(
        [
            "CHATGPT_VISUAL_PLAN_RESPONSE_V1",
            "[NOTES]",
            "Fixture plan",
            "[VISUAL_SCENE_PLAN_JSON]",
            json.dumps({"episode_style": {}, "story_sections": [], "scene_timeline": scene_timeline}),
        ]
    )
    result = parse_chatgpt_visual_plan(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {
                "scene_policy": {
                    "allowed_render_kinds": ["editorial_text_scene", "story_transition_scene"],
                    "max_scene_seconds": 14,
                    "min_scene_seconds": 3,
                    "semantic_min_scene_seconds": 5,
                    "semantic_target_scene_seconds": 9,
                    "compact_per_chunk_scenes": True,
                },
                "visual_capabilities": {},
                "require_complete_timeline": True,
                "gap_tolerance_seconds": 0.5,
            },
                "input": {
                    "response_text": response_text,
                    "video_packaging": video,
                    "script_generation": script,
                    "script_source": "fixture",
                    "voiceover": voiceover,
            },
        }
    )

    plan = result["data"]["visual_scene_plan"]
    validate_artifact_provenance(
        plan["provenance"],
        artifact_type="visual_plan",
        run_id="fixture_media_roundup_reference",
        payload=visual_plan_artifact_payload(plan),
        label="visual_scene_plan",
    )
    assert result["status"] == "ok"
    assert plan["scene_timeline"][0]["start_seconds"] == 0
    assert plan["scene_timeline"][-1]["end_seconds"] == round(cursor, 2)
    assert all(scene["duration_seconds"] <= 14 for scene in plan["scene_timeline"])
    title_scenes = [
        scene
        for scene in plan["scene_timeline"]
        if scene["render_kind"] == "story_transition_scene" and scene["payload"].get("voice_behavior") == "continue"
    ]
    assert len(title_scenes) == 3
    assert "Retimed" in " ".join(plan["checks"]["warnings"])
