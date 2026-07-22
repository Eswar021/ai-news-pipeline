from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.runnables import RunnableLambda

from src.pipeline.visuals.planner.app import _story_sequences_for_section
from src.pipeline.visuals.recipes import ACTIVE_RENDER_KINDS
from src.pipeline.visuals.research import app as visual_research_app


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "media_roundup_reference"


def _json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_visual_research_uses_one_complete_story_prompt_without_cross_story_records(
    monkeypatch,
) -> None:
    video_result = _json("video_packaging_result.json")
    script_result = _json("script_generation_result.json")
    stories = video_result["data"]["video_packet"]["stories"]
    prompts_by_story: dict[str, str] = {}

    class FakeLLM:
        def with_structured_output(self, output_model, **_kwargs):
            def invoke(prompt_value):
                rendered = prompt_value.to_string()
                task_payload = json.loads(rendered.rsplit("Task payload:\n", 1)[1])
                story = task_payload["story"]
                section = task_payload["canonical_script_section"]
                story_id = story["story_id"]
                prompts_by_story[story_id] = rendered
                beat_ids = [beat["beat_id"] for beat in section["beats"]]
                record_key = story["records"][0]["record_key"]
                parsed = output_model(
                    story_id=story_id,
                    visual_thesis="Use source-owned evidence, identity, and one clean explanation.",
                    sequence_notes=[
                        {
                            "sequence_label": "Establish and explain",
                            "beat_ids": beat_ids[: min(3, len(beat_ids))],
                            "visual_arc": "Establish the subject, reveal proof, then explain the implication.",
                            "preferred_shot_progression": [
                                "Open on the verified identity or source image.",
                                "Move into the exact source proof.",
                                "Finish with a restrained explainer.",
                            ],
                            "continuity_motif": "One warm accent line follows the active detail.",
                        }
                    ],
                    asset_needs=[
                        {
                            "beat_ids": [beat_ids[0]],
                            "sequence_role": "establish",
                            "subject": story.get("story_title", "Story subject"),
                            "action_or_detail": "Show the exact source-owned visual anchor.",
                            "editorial_purpose": "Give the viewer concrete context before explanation.",
                            "preferred_asset_types": ["source_page", "source_image"],
                            "preferred_source_record_keys": [record_key],
                            "must_show": ["The selected story subject"],
                            "must_avoid": ["Generic AI stock imagery"],
                            "suggested_search_queries": [],
                            "availability_strategy": "selected_source",
                        }
                    ],
                    unresolved_gaps=[],
                    warnings=[],
                )
                return {
                    "parsed": parsed,
                    "raw": SimpleNamespace(
                        content="fixture visual research",
                        usage_metadata={
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "total_tokens": 150,
                        },
                    ),
                    "parsing_error": None,
                }

            return RunnableLambda(invoke)

    monkeypatch.setattr(visual_research_app, "make_llm", lambda **_kwargs: FakeLLM())
    result = visual_research_app.run(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {
                "provider": "openai",
                "model": "fixture-model",
                "prompt_version": "v1",
                "temperature": 0.0,
                "max_attempts": 1,
                "worker_count": 1,
                "include_full_records": True,
                "external_search_enabled": False,
                "active_render_kinds": list(ACTIVE_RENDER_KINDS),
            },
            "input": {
                "video_packaging": video_result,
                "script_generation": script_result,
            },
        }
    )

    assert result["status"] == "ok"
    assert result["summary"]["researched_story_count"] == len(stories)
    assert result["summary"]["llm_call_count"] == len(stories)
    assert result["data"]["visual_research_package"]["source_policy"] == {
        "selected_stories_only": True,
        "full_story_records_in_prompt": True,
        "external_search_enabled": False,
    }
    for story in stories:
        story_id = story["story_id"]
        own_keys = {record["record_key"] for record in story["records"]}
        other_keys = {
            record["record_key"]
            for other in stories
            if other["story_id"] != story_id
            for record in other["records"]
        }
        rendered = prompts_by_story[story_id]
        assert all(record_key in rendered for record_key in own_keys)
        assert all(record_key not in rendered for record_key in other_keys)


def test_story_sequences_group_adjacent_short_shots_without_changing_timing() -> None:
    units = [
        {
            "unit_id": f"unit_{order}",
            "order": order,
            "beat_id": f"beat_{order}",
            "start_seconds": float((order - 1) * 10),
            "end_seconds": float(order * 10),
            "duration_seconds": 10.0,
            "text": f"Narration beat {order}",
            "visual_brief": {"visual_intent": f"Show beat {order}"},
        }
        for order in range(1, 7)
    ]
    sequences = _story_sequences_for_section(
        {
            "section_id": "section_story_fixture",
            "section_type": "story",
            "story_id": "story_fixture",
            "start_unit_order": 1,
            "end_unit_order": 6,
            "script_units": units,
        },
        {
            "enabled": True,
            "min_sequence_seconds": 25,
            "target_sequence_seconds": 30,
            "max_sequence_seconds": 45,
            "min_shots_per_sequence": 2,
            "max_shots_per_sequence": 4,
            "neighboring_unit_context": 1,
        },
    )

    assert [sequence["unit_orders"] for sequence in sequences] == [[1, 2, 3], [4, 5, 6]]
    assert [sequence["duration_seconds"] for sequence in sequences] == [30.0, 30.0]
    assert [sequence["target_shot_count"] for sequence in sequences] == [3, 3]
    assert sequences[0]["start_seconds"] == 0.0
    assert sequences[-1]["end_seconds"] == 60.0
    assert sequences[0]["neighbor_after"][0]["order"] == 4
    assert sequences[1]["neighbor_before"][0]["order"] == 3
