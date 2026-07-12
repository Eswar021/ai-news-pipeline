from __future__ import annotations

import json
import re
import wave
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool

from src.pipeline.apps.script_generation.formats.roundup import app as script_app
from src.pipeline.apps.script_generation.formats.roundup import writer as script_writer
from src.pipeline.apps.script_generation.formats.roundup.checks import check_script_package
from src.pipeline.apps.script_generation.formats.roundup.contract import ScriptGenerationResponse
from src.pipeline.apps.script_generation.formats.roundup.models import (
    BookendOutput,
    BookendReviewOutput,
    EpisodeDirectorOutput,
    StoryReviewOutput,
    StorySegmentOutput,
)
from src.pipeline.apps.script_generation.formats.roundup.sections import build_roundup_section_inputs
from src.pipeline.apps.script_generation.formats.roundup.writer import _story_gate_issues
from src.pipeline.apps.video_packaging.formats.roundup import build_roundup_packet, select_roundup_stories
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
    )
    for model in models:
        schema = convert_to_openai_tool(model, strict=True)["function"]["parameters"]
        assert _strict_schema_failures(schema) == [], model.__name__


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
                    "episode_thesis": "A connected episode thesis.",
                    "viewer_promise": "A useful viewer promise.",
                    "hook_strategy": "Open on the consequence.",
                    "pacing_strategy": "Move through stories clearly.",
                    "ordered_story_ids": ["story_one"],
                    "story_briefs": [
                        {
                            "story_id": "story_one",
                            "story_promise": "Explain the development.",
                            "angle": "Focus on practical impact.",
                            "must_cover": [],
                            "avoid": [],
                            "transition_in": "Begin clearly.",
                            "transition_out": "Move forward.",
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


def test_roundup_rejects_duplicate_canonical_events() -> None:
    stories = _json("video_packaging_result.json")["data"]["video_packet"]["stories"]
    duplicate = json.loads(json.dumps(stories[0]))
    duplicate["story_id"] = "story_duplicate"
    duplicate["rank"] = 2
    duplicate["story_title"] = "A second article about the same event"
    stories[1]["rank"] = 3
    stories[2]["rank"] = 4
    config = {
        "candidate_limit": 10,
        "max_stories": 5,
        "allowed_priority_buckets": ["high", "medium"],
        "exclude_noise": True,
        "exclude_tutorials": True,
        "max_per_entity": 3,
        "max_per_product": 2,
        "max_per_event_family": 2,
        "reject_duplicate_events": True,
    }

    selected, stats = select_roundup_stories([stories[0], duplicate, stories[1], stories[2]], config)

    assert [story["story_id"] for story in selected] == [
        "story_evidence",
        "story_sync",
        "story_render",
    ]
    assert stats["rejected_story_ids"]["story_duplicate"] == ["duplicate_canonical_event"]


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
    config = {
        "candidate_limit": 10,
        "max_stories": 5,
        "duration_mode": "content_driven",
        "duration_ceiling_seconds": 480,
        "allowed_priority_buckets": ["high", "medium"],
        "exclude_noise": True,
        "exclude_tutorials": True,
        "max_per_entity": 3,
        "max_per_product": 2,
        "max_per_event_family": 2,
        "reject_duplicate_events": True,
    }

    packet = build_roundup_packet(stories, config)["packet"]

    assert packet["duration_policy"] == {
        "mode": "content_driven",
        "configured_ceiling_seconds": 480,
        "timing_source_of_truth": "voiceover",
    }
    assert [story["video_segment"]["role"] for story in packet["stories"]] == ["lead", "major", "major"]
    assert all("target_seconds" not in story["video_segment"] for story in packet["stories"])
    assert "target_duration_seconds" not in packet


def test_structural_story_gate_accepts_natural_length() -> None:
    packet = _json("video_packaging_result.json")["data"]["video_packet"]
    story = packet["stories"][0]
    source_key = story["records"][0]["record_key"]
    concise = {
        "beats": [
            {
                "narration_text": "A concise but complete explanation.",
                "source_record_keys": [source_key],
            }
        ]
    }

    assert _story_gate_issues(concise, story=story) == []


def test_script_checks_do_not_reject_observed_duration_drift() -> None:
    video_packet = _json("video_packaging_result.json")["data"]["video_packet"]
    package = _json("script_generation_result.json")["data"]["script_package"]
    package["review"]["story_reviews"] = []
    package["review"]["bookend_final_gate_issues"] = []
    package["full_script_stats"]["estimated_duration_seconds"] = 20.0

    checks = check_script_package(package, video_packet)

    assert checks["passed"] is True
    assert not any("duration drift" in error for error in checks["errors"])


def test_manual_chatgpt_script_normalizes_to_canonical_beats() -> None:
    result = _canonical_manual_script()
    ScriptGenerationResponse.model_validate(result)
    package = result["data"]["script_package"]

    assert result["status"] == "ok"
    assert package["generation_strategy"] == "manual_story_sections_normalized_to_audiovisual_beats"
    assert len(package["sections"]) == 5
    assert package["full_script_stats"]["beat_count"] == 15
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

    class FakeLLM:
        def with_structured_output(self, model, include_raw=True, **kwargs):
            assert include_raw is True
            assert kwargs == {"strict": True}

            def invoke(prompt):
                prompt_text = prompt.to_string() if hasattr(prompt, "to_string") else str(prompt)
                if model is EpisodeDirectorOutput:
                    payload = {
                        "episode_thesis": "Evidence and timing keep automated media coherent.",
                        "viewer_promise": "See how the pieces connect.",
                        "hook_strategy": "Open on the synchronization problem.",
                        "pacing_strategy": "Move from evidence to timing to rendering.",
                        "ordered_story_ids": story_ids,
                        "story_briefs": [
                            {
                                "story_id": story_id,
                                "story_promise": f"Explain {story_id}.",
                                "angle": "The practical consequence.",
                                "must_cover": ["what changed", "why it matters"],
                                "avoid": ["hype"],
                                "transition_in": "Connect from the prior story.",
                                "transition_out": "Set up the next story.",
                            }
                            for story_id in story_ids
                        ],
                    }
                elif model is StorySegmentOutput:
                    task_payload = json.loads(prompt_text.split("Task payload:\n", 1)[1])
                    story_id = task_payload["required_story_id"]
                    assert task_payload["writing_guidance"]["enforcement"] == "soft_editorial_guidance_only"
                    assert "body_beat_contract" not in task_payload
                    assert "body_word_contract" not in task_payload

                    def beat(beat_type: str, narration: str) -> dict:
                        return {
                            "beat_type": beat_type,
                            "narration_text": narration,
                            "source_record_keys": [source_keys[story_id]],
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
                    payload = {
                        "should_apply_revision": False,
                        "diagnosis": [],
                        "revised_segment": task_payload["current_segment"],
                    }
                elif model is BookendOutput:
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
                                "visual_brief": visual,
                            },
                            {
                                "beat_type": "intro",
                                "narration_text": "Here is how one evidence-first workflow keeps those moving parts connected from source material to the final screen.",
                                "visual_brief": visual,
                            },
                        ],
                        "story_connectors": [
                            {
                                "story_id": story_id,
                                "display_title": titles[story_id],
                                "transition_line": "Next, another production problem comes into focus.",
                                "title_card_subtitle": "Evidence to screen",
                            }
                            for story_id in story_ids
                        ],
                        "closing_beats": [
                            {
                                "beat_type": "conclusion",
                                "narration_text": "The real advantage is not any single model or renderer; it is the shared beat contract that lets every stage improve without losing the story.",
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
                        "should_apply_revision": False,
                        "diagnosis": [],
                        "revised_bookends": task_payload["current_bookends"],
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
    assert all(
        section["title_card"]["voice_behavior"] == "continue"
        for section in package["sections"]
        if section["section_type"] == "story"
    )
    assert result["summary"]["content_policy"]["word_counts_are_approval_gates"] is False
    assert result["summary"]["content_policy"]["timing_source_of_truth"] == "voiceover"
    modules = [call["module_name"] for call in result["llm_calls"]]
    assert modules[0] == "roundup_director"
    assert modules.count("roundup_story_writer") == 3
    assert modules.count("roundup_story_reviewer") == 3
    assert modules[-2:] == ["roundup_bookend_writer", "roundup_bookend_reviewer"]
    assert not {"roundup_full_script_writer", "roundup_script_reviser"} & set(modules)


def test_unresolved_script_review_gates_block_downstream_handoff() -> None:
    video_packet = _json("video_packaging_result.json")["data"]["video_packet"]
    package = _json("script_generation_result.json")["data"]["script_package"]
    package["review"]["story_reviews"] = [
        {
            "story_id": "story_evidence",
            "passes": [],
            "final_gate_issues": ["overlong_beats:[2]:max_words=35"],
        }
    ]

    checks = check_script_package(
        package,
        video_packet,
    )

    assert checks["passed"] is False
    assert any("unresolved deterministic gates" in error for error in checks["errors"])


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
    assert len(resolved["chunks"]) == 15
    assert len({chunk["audio_unit_id"] for chunk in resolved["chunks"]}) == 5
    assert len({chunk["beat_id"] for chunk in resolved["chunks"]}) == 15

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
    assert sum(len(unit["aligned_beats"]) for unit in units) == 15
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
            "render_kind": "kinetic_type_scene",
            "covered_unit_orders": [1],
            "payload": {},
        },
        {
            "story_id": "story_evidence",
            "section_type": "story",
            "start_seconds": 1.0,
            "end_seconds": 3.8,
            "duration_seconds": 2.8,
            "render_kind": "transition_stinger_scene",
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
                "render_kind": "recap_sequence_scene" if section["section_type"] == "closing" else "architecture_flow_scene",
                "script_excerpt": section["narration_text"],
                "visual_intent": "Explain the active section.",
                "payload": {"headline": section["story_title"] or section["section_type"], "steps": []},
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
                    "allowed_render_kinds": ["architecture_flow_scene", "recap_sequence_scene", "transition_stinger_scene"],
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
        if scene["render_kind"] == "transition_stinger_scene" and scene["payload"].get("voice_behavior") == "continue"
    ]
    assert len(title_scenes) == 3
    assert "Retimed" in " ".join(plan["checks"]["warnings"])
