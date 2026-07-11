from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.pipeline.apps.script_generation.formats.roundup.contract import ScriptGenerationResponse
from src.pipeline.apps.video_packaging.contract import VideoPackagingResponse
from src.pipeline.handoffs.chatgpt_exporter import run as export_chatgpt_handoff
from src.pipeline.handoffs.chatgpt_script_parser import run as parse_chatgpt_script
from src.pipeline.handoffs.publish_handoff import run as build_publish_handoff
from src.pipeline.orchestration import create_run_context, load_run_context, module_output_dir
from src.pipeline.visuals.planner.contract import VisualPlannerResponse
from src.pipeline.visuals.planner.retime import retime_visual_plan_result


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "media_roundup_reference"


def _json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_reference_envelopes_match_production_contracts() -> None:
    VideoPackagingResponse.model_validate(_json("video_packaging_result.json"))
    ScriptGenerationResponse.model_validate(_json("script_generation_result.json"))
    VisualPlannerResponse.model_validate(_json("visual_scene_planning_result.json"))


def test_manual_chatgpt_parser_matches_reference_script() -> None:
    result = parse_chatgpt_script(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {"words_per_minute": 150, "duration_tolerance_seconds": 60},
            "input": {
                "response_text": (FIXTURE_DIR / "chatgpt_response.txt").read_text(encoding="utf-8"),
                "video_packaging": _json("video_packaging_result.json"),
                "script_source": str(FIXTURE_DIR / "chatgpt_response.txt"),
            },
        }
    )

    assert result["status"] == "ok"
    assert result["handoff"]["ready_for_metadata_creation"] is True
    assert result["data"]["script_package"]["full_script"] == (
        FIXTURE_DIR / "full_script.txt"
    ).read_text(encoding="utf-8").strip()
    assert [section["section_type"] for section in result["data"]["script_package"]["sections"]] == [
        "intro",
        "story",
        "story",
        "story",
        "closing",
    ]


def test_reference_visual_timeline_is_contiguous_and_bounded() -> None:
    plan = _json("visual_scene_planning_result.json")["data"]["visual_scene_plan"]
    scenes = plan["scene_timeline"]

    assert scenes[0]["start_seconds"] == 0
    assert scenes[-1]["end_seconds"] == plan["coverage"]["total_duration_seconds"]
    assert all(scene["duration_seconds"] <= 14 for scene in scenes)
    assert all(left["end_seconds"] == right["start_seconds"] for left, right in zip(scenes, scenes[1:]))


def test_reference_visual_timeline_can_follow_generated_audio() -> None:
    retimed = retime_visual_plan_result(_json("visual_scene_planning_result.json"), 87.35)
    VisualPlannerResponse.model_validate(retimed)
    scenes = retimed["data"]["visual_scene_plan"]["scene_timeline"]

    assert scenes[-1]["end_seconds"] == 87.35
    assert retimed["summary"]["retimed_to_voiceover"] is True
    assert all(left["end_seconds"] == right["start_seconds"] for left, right in zip(scenes, scenes[1:]))


def test_run_context_freezes_profile_and_uses_run_first_layout(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config_path = project_root / "src" / "pipeline" / "config" / "workbench.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump({"default_run_profile": "smoke", "profiles": {"smoke": {"feature": {"enabled": True}}}}),
        encoding="utf-8",
    )
    output_root = project_root / "output"

    context = create_run_context(
        project_root=project_root,
        run_id="run_fixture",
        config_path=config_path,
        output_root=output_root,
        orchestrator="notebooks/production/content_pipeline.ipynb",
    )

    assert context["profile_config"]["feature"]["enabled"] is True
    assert Path(context["run_dir"]) == output_root / "runs" / "run_fixture"
    assert module_output_dir(context, "story_mapping") == output_root / "runs" / "run_fixture" / "story_mapping"
    assert load_run_context(output_root=output_root, run_id="current")["run_id"] == "run_fixture"

    config_path.write_text(
        yaml.safe_dump({"default_run_profile": "smoke", "profiles": {"smoke": {"feature": {"enabled": False}}}}),
        encoding="utf-8",
    )
    resumed = create_run_context(
        project_root=project_root,
        run_id="run_fixture",
        config_path=config_path,
        output_root=output_root,
    )
    assert resumed["profile_config"]["feature"]["enabled"] is True


def test_chatgpt_exporter_reads_current_video_packet_shape() -> None:
    video = _json("video_packaging_result.json")
    result = export_chatgpt_handoff(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {"profile": "content_packet", "prompt_version": "v1"},
            "input": {
                "manifest": {"run_id": "fixture_media_roundup_reference", "run_profile": "fixture", "profile_config": {}},
                "artifacts": {"content_packet": video["data"]["video_packet"]},
                "summaries": {},
            },
        }
    )

    assert result["status"] == "ok"
    payload = next(item["content"] for item in result["data"]["handoff_package"]["files"] if item["filename"] == "02_payload.md")
    assert "Selected stories: 3" in payload
    assert "story_evidence" in payload


def test_publish_handoff_uses_current_content_contracts() -> None:
    result = build_publish_handoff(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {"require_ready_inputs": True},
            "input": {
                "run_context": {"run_id": "fixture_media_roundup_reference", "run_profile": "fixture"},
                "video_packaging": _json("video_packaging_result.json"),
                "script_generation": _json("script_generation_result.json"),
                "metadata_creator": {
                    "status": "ok",
                    "data": {
                        "metadata_package": {
                            "youtube_metadata": {
                                "title_options": [{"title": "From Sources to Screen"}],
                                "thumbnail_text_options": ["SOURCES TO SCREEN"],
                                "description_draft": "A deterministic media pipeline smoke test.",
                                "chapters": [{"timestamp": "00:00", "title": "Intro"}],
                                "source_urls": ["https://github.com/Eswar021/ai-news-pipeline"],
                            }
                        }
                    },
                },
            },
        }
    )

    assert result["status"] == "ok"
    assert result["handoff"]["ready_for_manual_publish_review"] is True
    assert "Manual Publish Review" in result["data"]["publish_handoff_package"]["files"][0]["content"]


def test_committed_notebooks_are_clean_and_canonical() -> None:
    notebook_root = Path(__file__).parents[1] / "notebooks"
    expected = {
        "production/content_pipeline.ipynb",
        "production/voiceover_generation.ipynb",
        "production/visual_production.ipynb",
        "handoffs/chatgpt_handoffs.ipynb",
        "labs/visual_assets_lab.ipynb",
    }
    actual = {str(path.relative_to(notebook_root)) for path in notebook_root.glob("**/*.ipynb")}

    assert actual == expected
    for relative in expected:
        notebook = json.loads((notebook_root / relative).read_text(encoding="utf-8"))
        serialized = json.dumps(notebook)
        assert "pipeline_v2" not in serialized
        assert "output_v2" not in serialized
        for cell in notebook["cells"]:
            if cell.get("cell_type") == "code":
                assert cell.get("execution_count") is None
                assert cell.get("outputs") == []
