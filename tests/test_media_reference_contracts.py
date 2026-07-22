from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.pipeline.config import ConfigRepository

from src.pipeline.publishing.metadata_finalizer import run as finalize_metadata
from src.pipeline.content.script_generation.formats.roundup.contract import ScriptGenerationResponse
from src.pipeline.content.video_packaging.contract import VideoPackagingResponse
from src.pipeline.contracts import (
    artifact_fingerprint,
    build_artifact_provenance,
    file_sha256,
    final_video_artifact_payload,
    validate_script_provenance,
    visual_assets_artifact_payload,
    visual_plan_artifact_payload,
    voiceover_artifact_payload,
)
from src.pipeline.handoffs.chatgpt_exporter import run as export_chatgpt_handoff
from src.pipeline.handoffs.chatgpt_script_parser import run as parse_chatgpt_script
from src.pipeline.publishing.publish_handoff import run as build_publish_handoff
from src.pipeline.orchestration import (
    create_run_context,
    load_run_context,
    module_output_dir,
    render_config_templates,
    resolve_script_result,
    resolve_voiceover_package,
)
from src.pipeline.visuals.planner.contract import VisualPlannerResponse
from src.pipeline.visuals.planner import app as visual_planner_app
from src.pipeline.visuals.planner.retime import retime_visual_plan_result
from src.pipeline.visuals.asset_catalog import run as build_visual_asset_catalog
from src.pipeline.visuals.asset_resolver.app import _build_manifest
from src.pipeline.visuals.render.app import _required_asset_provenance


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


def test_voiceover_selection_supports_isolated_test_output_with_absolute_audio(
    tmp_path: Path,
) -> None:
    run_id = "fixture_isolated_output"
    run_dir = tmp_path / "isolated" / "runs" / run_id
    variant_dir = run_dir / "voiceover" / "kokoro_fixture"
    audio_path = variant_dir / "audio" / "full_voiceover.wav"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"isolated fixture voiceover")
    script_fingerprint = f"sha256:{'2' * 64}"
    package = {
        "run_id": run_id,
        "status": "ready",
        "provider": "fixture",
        "voice": "fixture",
        "style": {},
        "audio": {
            "sample_rate_hz": 24000,
            "duration_seconds": 1.0,
            "full_audio_path": str(audio_path),
        },
        "audio_units": [],
    }
    _bind_voiceover_provenance(
        package,
        script_fingerprint,
        audio_sha256=file_sha256(audio_path),
    )
    (variant_dir / "voiceover_package.json").write_text(
        json.dumps(package),
        encoding="utf-8",
    )

    selected_path, _ = resolve_voiceover_package(
        run_dir=run_dir,
        run_id=run_id,
        script_fingerprint=script_fingerprint,
    )

    assert selected_path == variant_dir / "voiceover_package.json"


def test_reference_envelopes_match_production_contracts() -> None:
    VideoPackagingResponse.model_validate(_json("video_packaging_result.json"))
    ScriptGenerationResponse.model_validate(_json("script_generation_result.json"))
    VisualPlannerResponse.model_validate(_json("visual_scene_planning_result.json"))


def test_visual_planner_passes_provenance_to_plan_builder_not_episode_director(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = ConfigRepository(
        Path(__file__).parents[1] / "src/pipeline/config/workbench.yaml"
    )
    profile = repository.profile("daily_48h_all_sources").value
    captured: dict = {}
    catalog_config = {
        **profile["visuals"]["asset_catalog"],
        "require_visual_research": False,
        "output_dir": str(tmp_path / "catalog"),
        "page_metadata": {**profile["visuals"]["asset_catalog"]["page_metadata"], "enabled": False},
        "source_page_preflight": {
            **profile["visuals"]["asset_catalog"]["source_page_preflight"],
            "enabled": False,
        },
        "contact_sheet": {**profile["visuals"]["asset_catalog"]["contact_sheet"], "enabled": False},
    }
    asset_catalog = build_visual_asset_catalog(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": catalog_config,
            "input": {
                "video_packaging": _json("video_packaging_result.json"),
                "script_generation": _json("script_generation_result.json"),
            },
        }
    )

    monkeypatch.setattr(visual_planner_app, "load_prompt_bundle", lambda *args, **kwargs: {})
    monkeypatch.setattr(visual_planner_app, "make_llm", lambda **kwargs: object())
    monkeypatch.setattr(
        visual_planner_app,
        "_generate_episode_direction",
        lambda **kwargs: {"visual_thesis": "fixture"},
    )
    monkeypatch.setattr(visual_planner_app, "_generate_bookend_visual_plan", lambda **kwargs: {})
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

    planner_config = {
        **profile["visuals"]["planner"],
        "require_visual_research": False,
        "visual_editor": {
            **profile["visuals"]["planner"].get("visual_editor", {}),
            "enabled": False,
        },
    }
    result = visual_planner_app.run(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": planner_config,
            "input": {
                "video_packaging": _json("video_packaging_result.json"),
                "script_generation": _json("script_generation_result.json"),
                "asset_catalog": asset_catalog,
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


def test_manual_chatgpt_parser_requires_explicit_production_beats() -> None:
    response = """CHATGPT_PIPELINE_RESPONSE_V1

[NOTES]
Fixture with missing audiovisual beats.

[SCRIPT]
[SCRIPT_SECTIONS_JSON]
```json
{"sections": [{"section_id": "section_00_intro", "narration_text": "Hello."}]}
```

[METADATA]
title_options: []
"""

    with pytest.raises(ValueError, match="missing explicit beats"):
        parse_chatgpt_script(
            {
                "run": {"run_id": "fixture_media_roundup_reference"},
                "input": {
                    "response_text": response,
                    "video_packaging": _json("video_packaging_result.json"),
                },
            }
        )


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
    draft_chapter_titles = [
        "The evidence arrives before the confidence",
        "Source records become an editorial story",
        "The script keeps its story boundaries",
        "Audio timing becomes the production clock",
        "What the final package carries forward",
    ]
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
        "chapters": [
            {
                "timestamp": "0:00",
                "start_seconds": 0,
                "section_id": section["section_id"],
                "title": draft_chapter_titles[index],
            }
            for index, section in enumerate(script_package["sections"])
        ],
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
    assert [chapter["title"] for chapter in metadata["chapters"]] == draft_chapter_titles
    assert metadata["metadata_basis"]["chapter_timing_source"] == "voiceover_audio_units"
    assert metadata["metadata_basis"]["chapters_finalized"] is True
    assert "0:13" in metadata["description_draft"]


def test_manual_chatgpt_parser_normalizes_packet_segment_markers() -> None:
    video = _json("video_packaging_result.json")
    response = (FIXTURE_DIR / "chatgpt_response.txt").read_text(encoding="utf-8")
    response = response.replace('"section_id": "section_00_intro"', '"section_id": "intro"')
    response = response.replace('"section_id": "section_99_closing"', '"section_id": "closing"')
    for story in video["data"]["video_packet"]["stories"]:
        segment = story["video_segment"]
        canonical_id = f"section_{segment['segment_order']:02d}_{story['story_id']}"
        response = response.replace(
            f'"section_id": "{canonical_id}"',
            f'"section_id": "{segment["segment_id"]}"',
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
    assert package["manual_handoff"]["section_parse_mode"] == "structured_json"
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


def test_run_context_freezes_environment_and_rejects_cross_environment_resume(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config_root = project_root / "src" / "pipeline" / "config"
    config_root.mkdir(parents=True)
    (config_root / "dev.yaml").write_text(
        yaml.safe_dump({"shared": {"orchestration": {"logging": {"profile": "verbose"}}}, "modules": {}}),
        encoding="utf-8",
    )
    config_path = config_root / "workbench.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "default_run_profile": "smoke",
                "default_environment": "prod",
                "environments": {"dev": "dev.yaml", "prod": "prod.yaml"},
                "profiles": {"smoke": {"feature": {"enabled": True}}},
            }
        ),
        encoding="utf-8",
    )
    (config_root / "prod.yaml").write_text(
        yaml.safe_dump({"shared": {}, "modules": {}}), encoding="utf-8"
    )
    output_root = project_root / "output"

    context = create_run_context(
        project_root=project_root,
        run_id="run_dev_fixture",
        config_path=config_path,
        output_root=output_root,
        config_environment="dev",
    )

    assert context["config_environment"] == "dev"
    assert context["profile_config"]["orchestration"]["logging"]["profile"] == "verbose"
    with pytest.raises(ValueError, match="uses config environment 'dev'"):
        create_run_context(
            project_root=project_root,
            run_id="run_dev_fixture",
            config_path=config_path,
            output_root=output_root,
            config_environment="prod",
        )


def test_config_template_renderer_preserves_descriptive_schema_braces() -> None:
    rendered = render_config_templates(
        {
            "cache": "{CACHE_ROOT}/models/{RUN_ID}",
            "render_notes": "metrics use {label, value, unit?, context?}",
            "nested": ["{PROJECT_ROOT}/src", "{from, to, label}"],
        },
        {
            "PROJECT_ROOT": "/repo",
            "CACHE_ROOT": "/cache",
            "RUN_ID": "run_fixture",
        },
    )

    assert rendered["cache"] == "/cache/models/run_fixture"
    assert rendered["render_notes"] == "metrics use {label, value, unit?, context?}"
    assert rendered["nested"] == ["/repo/src", "{from, to, label}"]


def test_config_template_renderer_fails_for_missing_supported_value() -> None:
    with pytest.raises(KeyError, match="RUN_ID"):
        render_config_templates("{RUN_ID}/artifact", {"PROJECT_ROOT": "/repo"})


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


def test_chatgpt_visual_handoff_hides_disabled_capabilities() -> None:
    result = export_chatgpt_handoff(
        {
            "run": {"run_id": "fixture_media_roundup_reference"},
            "config": {"profile": "visual_scene_plan", "prompt_version": "v1"},
            "input": {
                "manifest": {
                    "run_id": "fixture_media_roundup_reference",
                    "run_profile": "fixture",
                    "profile_config": {},
                },
                "artifacts": {
                    "visual_scene_plan": {
                        "package_type": "visual_scene_planning_handoff",
                        "script": {"word_count": 3},
                        "video_packet": {"stories": []},
                        "voiceover_timing": {"duration_seconds": 1.0, "chunks": []},
                        "asset_catalog": {
                            "assets": [
                                {
                                    "asset_id": "asset_source_page_fixture",
                                    "asset_type": "source_page",
                                    "story_id": "story_fixture",
                                    "status": "available",
                                }
                            ]
                        },
                        "visual_context": {
                            "scene_policy": {
                                "max_scene_seconds": 14.0,
                                "allowed_render_kinds": ["context_image_scene"],
                            },
                            "visual_capabilities": {
                                "context_image_scene": {"description": "enabled"},
                                "broll_video_scene": {"description": "disabled"},
                            },
                        },
                    }
                },
                "summaries": {},
            },
        }
    )

    assert result["status"] == "ok"
    payload = next(
        item["content"]
        for item in result["data"]["handoff_package"]["files"]
        if item["filename"] == "02_payload.md"
    )
    assert '"context_image_scene"' in payload
    assert '"broll_video_scene"' not in payload
    instructions = next(
        item["content"]
        for item in result["data"]["handoff_package"]["files"]
        if item["filename"] == "01_instructions.md"
    )
    assert "broll_video_scene" not in instructions


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
        "render_mode": "final",
        "render_settings": {"quality_preset": "1080p", "width": 1920, "height": 1080, "fps": 30},
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
    publish_input = {
        "run": {"run_id": "fixture_media_roundup_reference"},
        "config": {"require_ready_inputs": True},
        "input": {
            "run_context": {
                "run_id": "fixture_media_roundup_reference",
                "run_profile": "fixture",
            },
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
                    },
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
    result = build_publish_handoff(publish_input)

    assert result["status"] == "ok"
    assert result["handoff"]["ready_for_manual_publish_review"] is True
    assert "Manual Publish Review" in result["data"]["publish_handoff_package"]["files"][0]["content"]

    preview_input = json.loads(json.dumps(publish_input))
    preview_package = preview_input["input"]["video_assembly"]["data"]["final_video_package"]
    preview_package["render_mode"] = "preview"
    preview_package["provenance"] = build_artifact_provenance(
        artifact_type="final_video",
        run_id="fixture_media_roundup_reference",
        parents=final_video_provenance["parent_fingerprints"],
        payload=final_video_artifact_payload(preview_package),
    )
    preview_result = build_publish_handoff(preview_input)
    assert preview_result["status"] == "failed"
    assert "requires a final-quality video assembly" in preview_result["summary"]["error"]


def test_visual_plan_identity_changes_with_asset_catalog_fingerprint() -> None:
    plan = {
        "planning_strategy": "episode_director_plus_per_story",
        "episode_style": {},
        "story_sections": [],
        "scene_timeline": [],
        "asset_catalog": {
            "provenance": {"artifact_fingerprint": "sha256:" + "1" * 64},
        },
    }
    first = artifact_fingerprint(visual_plan_artifact_payload(plan))
    plan["asset_catalog"]["provenance"]["artifact_fingerprint"] = "sha256:" + "2" * 64
    second = artifact_fingerprint(visual_plan_artifact_payload(plan))
    assert first != second


def test_visual_asset_manifest_identity_is_shared_by_resolver_and_renderer(
    tmp_path: Path,
) -> None:
    run_id = "run_asset_identity"
    visual_plan_fingerprint = "sha256:" + "1" * 64
    script_fingerprint = "sha256:" + "2" * 64
    voiceover_fingerprint = "sha256:" + "3" * 64
    manifest = _build_manifest(
        run_id=run_id,
        generated_at="2026-07-19T00:00:00+00:00",
        output_dir=tmp_path,
        visual_scene_plan={
            "scene_timeline": [
                {
                    "scene_id": "scene_001",
                    "scene_order": 1,
                    "render_kind": "source_article_scene",
                }
            ]
        },
        visual_media_package={},
        resolved_assets=[
            {
                "scene_id": "scene_001",
                "asset_type": "source_montage",
                "status": "resolved",
                "asset_path": "montage.png",
                "assets": [
                    {"asset_path": "source-a.png"},
                    {"asset_path": "source-b.png"},
                ],
            }
        ],
        plan_provenance={
            "visual_plan_fingerprint": visual_plan_fingerprint,
            "script_fingerprint": script_fingerprint,
            "voiceover_fingerprint": voiceover_fingerprint,
            "script_source": "native_app",
        },
    )

    payload = visual_assets_artifact_payload(manifest)
    assert payload["resolved_assets"][0]["asset_paths"] == [
        "source-a.png",
        "source-b.png",
    ]
    provenance = _required_asset_provenance(manifest, run_id)
    assert provenance["artifact_fingerprint"] == manifest["provenance"][
        "artifact_fingerprint"
    ]


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
