from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.pipeline.apps.metadata_finalizer import run as finalize_metadata
from src.pipeline.apps.script_generation.formats.roundup.contract import ScriptGenerationResponse
from src.pipeline.apps.video_packaging.contract import VideoPackagingResponse
from src.pipeline.contracts import (
    build_artifact_provenance,
    file_sha256,
    final_video_artifact_payload,
    validate_script_provenance,
    voiceover_artifact_payload,
)
from src.pipeline.handoffs.chatgpt_exporter import run as export_chatgpt_handoff
from src.pipeline.handoffs.chatgpt_script_parser import run as parse_chatgpt_script
from src.pipeline.handoffs.publish_handoff import run as build_publish_handoff
from src.pipeline.orchestration import (
    create_run_context,
    load_run_context,
    module_output_dir,
    resolve_script_result,
    resolve_voiceover_package,
)
from src.pipeline.visuals.planner.contract import VisualPlannerResponse
from src.pipeline.visuals.planner import app as visual_planner_app
from src.pipeline.visuals.planner.retime import retime_visual_plan_result


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "media_roundup_reference"


def _json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _bind_voiceover_provenance(
    package: dict,
    script_fingerprint: str,
    *,
    audio_sha256: str | None = None,
) -> dict:
    audio_sha256 = audio_sha256 or f"sha256:{'0' * 64}"
    package["provenance"] = {"audio_sha256": audio_sha256}
    provenance = build_artifact_provenance(
        artifact_type="voiceover",
        run_id=package["run_id"],
        parents={"script": script_fingerprint},
        payload=voiceover_artifact_payload(package),
    )
    provenance["audio_sha256"] = audio_sha256
    package["provenance"] = provenance
    return provenance


def test_voiceover_selection_resolves_repository_relative_audio_from_notebook_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    run_id = "run_relative_audio"
    run_dir = project_root / "output" / "runs" / run_id
    variant_dir = run_dir / "voiceover" / "kokoro_fixture"
    audio_path = variant_dir / "audio" / "full_voiceover.wav"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"fixture voiceover bytes")
    script_fingerprint = f"sha256:{'1' * 64}"
    package = {
        "run_id": run_id,
        "status": "ready",
        "provider": "fixture",
        "voice": "fixture",
        "style": {},
        "audio": {
            "sample_rate_hz": 24000,
            "duration_seconds": 1.0,
            "full_audio_path": str(audio_path.relative_to(project_root)),
        },
        "audio_units": [],
    }
    _bind_voiceover_provenance(
        package,
        script_fingerprint,
        audio_sha256=file_sha256(audio_path),
    )
    package_path = variant_dir / "voiceover_package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    notebook_dir = project_root / "notebooks" / "production"
    notebook_dir.mkdir(parents=True)
    monkeypatch.chdir(notebook_dir)

    selected_path, selected_package = resolve_voiceover_package(
        run_dir=run_dir,
        run_id=run_id,
        script_fingerprint=script_fingerprint,
    )

    assert selected_path == package_path
    assert selected_package["provenance"]["audio_sha256"] == file_sha256(audio_path)


def test_reference_envelopes_match_production_contracts() -> None:
    VideoPackagingResponse.model_validate(_json("video_packaging_result.json"))
    ScriptGenerationResponse.model_validate(_json("script_generation_result.json"))
    VisualPlannerResponse.model_validate(_json("visual_scene_planning_result.json"))


def test_visual_planner_passes_provenance_to_plan_builder_not_episode_director(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = yaml.safe_load(
        (Path(__file__).parents[1] / "src/pipeline/config/workbench.yaml").read_text(encoding="utf-8")
    )["profiles"]["daily_48h_all_sources"]
    captured: dict = {}

    monkeypatch.setattr(visual_planner_app, "load_prompt_bundle", lambda *args, **kwargs: {})
    monkeypatch.setattr(visual_planner_app, "make_llm", lambda **kwargs: object())
    monkeypatch.setattr(
        visual_planner_app,
        "_generate_episode_direction",
        lambda **kwargs: {"visual_thesis": "fixture"},
    )
    monkeypatch.setattr(visual_planner_app, "_generate_story_visual_plans", lambda **kwargs: {})

    def fake_build_visual_scene_plan(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {
            "source_script": {"word_count": 1},
            "audio_timeline": {"duration_seconds": 1.0},
            "story_plans": [],
            "story_sections": [],
            "visual_beat_map": [],
            "scene_timeline": [],
            "coverage": {},
            "planning_calls": [],
        }

    monkeypatch.setattr(visual_planner_app, "_build_visual_scene_plan", fake_build_visual_scene_plan)
    monkeypatch.setattr(
        visual_planner_app,
        "_check_scene_plan",
        lambda plan, config: {"passed": True, "errors": [], "warnings": []},
    )

    result = visual_planner_app.run(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": profile["visuals"]["planner"],
            "input": {
                "video_packaging": _json("video_packaging_result.json"),
                "script_generation": _json("script_generation_result.json"),
            },
        }
    )

    assert result["status"] == "ok"
    assert captured["script_provenance"]["script_fingerprint"].startswith("sha256:")
    assert captured["voiceover_provenance"] is None


def test_reference_script_preserves_story_beat_contract() -> None:
    package = _json("script_generation_result.json")["data"]["script_package"]
    sections = package["sections"]

    assert package["generation_strategy"] == "manual_story_sections_normalized_to_audiovisual_beats"
    assert package["full_script_stats"]["beat_count"] == 12
    assert len(package["audio_plan"]["units"]) == len(sections) == 5
    assert package["full_script"] == "\n\n".join(section["narration_text"] for section in sections)
    for section in sections:
        assert section["narration_text"] == " ".join(beat["narration_text"] for beat in section["beats"])
        if section["section_type"] == "story":
            assert section["title_card"]["voice_behavior"] == "continue"
            assert section["title_card"]["anchor_beat_id"] == section["beats"][0]["beat_id"]


def test_manual_chatgpt_parser_matches_reference_script() -> None:
    result = parse_chatgpt_script(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {"diagnostic_words_per_minute": 150},
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


def test_script_provenance_rejects_changed_spoken_text() -> None:
    result = _json("script_generation_result.json")
    package = result["data"]["script_package"]
    package["sections"][1]["beats"][0]["narration_text"] += " Changed after approval."

    with pytest.raises(ValueError, match="provenance does not match"):
        validate_script_provenance(
            package,
            run_id=result["data"]["run_id"],
            upstream_run_id=result["data"]["run_id"],
        )


def test_metadata_finalizer_uses_actual_voiceover_section_starts() -> None:
    script_result = _json("script_generation_result.json")
    script_package = script_result["data"]["script_package"]
    script_provenance = script_package["provenance"]
    starts = [0.0, 13.42, 52.18, 91.77, 128.31]
    audio_units = [
        {
            "audio_unit_id": f"audio_{section['section_id']}",
            "unit_order": index,
            "section_id": section["section_id"],
            "section_type": section["section_type"],
            "story_id": section.get("story_id", ""),
            "start_seconds": starts[index - 1],
            "end_seconds": starts[index] if index < len(starts) else 139.5,
            "aligned_beats": [],
        }
        for index, section in enumerate(script_package["sections"], start=1)
    ]
    voiceover_package = {
        "run_id": "fixture_media_roundup_reference",
        "status": "ready",
        "provider": "fixture",
        "voice": "fixture",
        "style": {},
        "audio": {"duration_seconds": 139.5, "sample_rate_hz": 24000},
        "audio_units": audio_units,
    }
    voiceover_provenance = _bind_voiceover_provenance(
        voiceover_package,
        script_provenance["script_fingerprint"],
    )
    metadata_draft = {
        "title_options": [{"title": "From Sources to Screen"}],
        "thumbnail_text_options": ["SOURCES TO SCREEN"],
        "blocked_title_angles": [],
        "description_draft": "Provisional",
        "description_components": {
            "intro": "A deterministic media pipeline smoke test.",
            "channel_footer": "Fixture Channel",
            "include_source_urls": True,
        },
        "chapters": [],
        "tags": ["AI news"],
        "source_urls": ["https://github.com/Eswar021/ai-news-pipeline"],
        "metadata_basis": {"chapters_finalized": False},
    }
    metadata_provenance = build_artifact_provenance(
        artifact_type="metadata_draft",
        run_id="fixture_media_roundup_reference",
        parents={"script": script_provenance["script_fingerprint"]},
        payload=metadata_draft,
    )
    result = finalize_metadata(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {"require_all_script_sections": True},
            "input": {
                "script_generation": script_result,
                "metadata_creator": {
                    "status": "ok",
                    "data": {
                        "run_id": "fixture_media_roundup_reference",
                        "metadata_package": {
                            "package_type": "youtube_metadata_package",
                            "package_stage": "draft",
                            "youtube_metadata": metadata_draft,
                            "provenance": metadata_provenance,
                        },
                    },
                },
                "voiceover": voiceover_package,
            },
        }
    )

    metadata = result["data"]["metadata_package"]["youtube_metadata"]
    assert result["status"] == "ok"
    assert [chapter["start_seconds"] for chapter in metadata["chapters"]] == starts
    assert metadata["metadata_basis"]["chapter_timing_source"] == "voiceover_audio_units"
    assert metadata["metadata_basis"]["chapters_finalized"] is True
    assert "0:13" in metadata["description_draft"]


def test_manual_chatgpt_parser_normalizes_packet_segment_markers() -> None:
    video = _json("video_packaging_result.json")
    response = (FIXTURE_DIR / "chatgpt_response.txt").read_text(encoding="utf-8")
    response = response.replace("[[SECTION:section_00_intro]]", "[[SECTION:intro]]")
    response = response.replace("[[SECTION:section_99_closing]]", "[[SECTION:closing]]")
    for story in video["data"]["video_packet"]["stories"]:
        segment = story["video_segment"]
        canonical_id = f"section_{segment['segment_order']:02d}_{story['story_id']}"
        response = response.replace(
            f"[[SECTION:{canonical_id}]]",
            f"[[SECTION:{segment['segment_id']}]]",
        )

    result = parse_chatgpt_script(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {"diagnostic_words_per_minute": 150},
            "input": {
                "response_text": f"Here is the requested response:\n\n{response}",
                "video_packaging": video,
            },
        }
    )

    package = result["data"]["script_package"]
    assert result["status"] == "ok"
    assert [section["section_id"] for section in package["sections"]] == [
        "section_00_intro",
        "section_01_story_evidence",
        "section_02_story_sync",
        "section_03_story_render",
        "section_99_closing",
    ]
    assert package["manual_handoff"]["section_parse_mode"] == "inline_markers"
    assert "Normalized 5 packet script markers" in result["summary"]["checks"]["warnings"][0]


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


def test_script_selection_never_guesses_when_both_sources_exist(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    app_path = run_dir / "script_generation" / "script_generation_result.json"
    chatgpt_path = run_dir / "script_generation" / "chatgpt" / "script_generation_result.json"
    app_path.parent.mkdir(parents=True)
    chatgpt_path.parent.mkdir(parents=True)
    payload = _json("script_generation_result.json")
    app_path.write_text(json.dumps(payload), encoding="utf-8")
    chatgpt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Multiple canonical scripts"):
        resolve_script_result(
            run_dir=run_dir,
            run_id="fixture_media_roundup_reference",
            source="auto",
        )

    selected_path, selected = resolve_script_result(
        run_dir=run_dir,
        run_id="fixture_media_roundup_reference",
        source="app",
    )
    assert selected_path == app_path
    assert selected["status"] == "ok"


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
    assert "### Required Script Markers" in payload
    assert "`[[SECTION:intro]]`" in payload
    assert "`[[SECTION:segment_01_story_evidence]]`" in payload
    assert "`[[SECTION:closing]]`" in payload
    assert "Suggested words are soft editorial guidance" in payload
    assert "parser treats section, body, connector" not in payload


def test_publish_handoff_uses_current_content_contracts() -> None:
    script_result = _json("script_generation_result.json")
    script_provenance = script_result["data"]["script_package"]["provenance"]
    script_fingerprint = script_provenance["script_fingerprint"]
    voiceover_package = {
        "run_id": "fixture_media_roundup_reference",
        "status": "ready",
        "provider": "fixture",
        "voice": "fixture",
        "style": {},
        "audio": {"duration_seconds": 1.0, "sample_rate_hz": 24000},
        "audio_units": [],
    }
    voiceover_provenance = _bind_voiceover_provenance(voiceover_package, script_fingerprint)
    youtube_metadata = {
        "title_options": [{"title": "From Sources to Screen"}],
        "thumbnail_text_options": ["SOURCES TO SCREEN"],
        "description_draft": "A deterministic media pipeline smoke test.",
        "chapters": [{"timestamp": "00:00", "title": "Intro"}],
        "source_urls": ["https://github.com/Eswar021/ai-news-pipeline"],
        "metadata_basis": {"chapters_finalized": True},
    }
    metadata_provenance = build_artifact_provenance(
        artifact_type="metadata_final",
        run_id="fixture_media_roundup_reference",
        parents={
            "script": script_fingerprint,
            "voiceover": voiceover_provenance["voiceover_fingerprint"],
        },
        payload=youtube_metadata,
    )
    visual_plan_provenance = build_artifact_provenance(
        artifact_type="visual_plan",
        run_id="fixture_media_roundup_reference",
        parents={
            "script": script_fingerprint,
            "voiceover": voiceover_provenance["voiceover_fingerprint"],
        },
        payload={"fixture": True},
    )
    final_video_package = {
        "final_video_path": "fixture.mp4",
        "scene_ids": [],
        "final_video_sha256": "",
        "audio_encoding": {},
    }
    final_video_provenance = build_artifact_provenance(
        artifact_type="final_video",
        run_id="fixture_media_roundup_reference",
        parents={
            "script": script_fingerprint,
            "voiceover": voiceover_provenance["voiceover_fingerprint"],
            "visual_plan": visual_plan_provenance["visual_plan_fingerprint"],
        },
        payload=final_video_artifact_payload(final_video_package),
    )
    final_video_package["provenance"] = final_video_provenance
    result = build_publish_handoff(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {"require_ready_inputs": True},
            "input": {
                "run_context": {"run_id": "fixture_media_roundup_reference", "run_profile": "fixture"},
                "video_packaging": _json("video_packaging_result.json"),
                "script_generation": script_result,
                "metadata_finalizer": {
                    "status": "ok",
                    "data": {
                        "run_id": "fixture_media_roundup_reference",
                        "metadata_package": {
                            "package_stage": "final",
                            "provenance": metadata_provenance,
                            "youtube_metadata": youtube_metadata,
                        }
                    },
                },
                "voiceover": {
                    "status": "ok",
                    "data": {
                        "run_id": "fixture_media_roundup_reference",
                        "voiceover_package": voiceover_package,
                    },
                    "summary": {"audio_path": "fixture.wav"},
                },
                "video_assembly": {
                    "status": "ok",
                    "data": {
                        "run_id": "fixture_media_roundup_reference",
                    "final_video_package": final_video_package,
                    },
                    "summary": {"final_video_path": "fixture.mp4"},
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
