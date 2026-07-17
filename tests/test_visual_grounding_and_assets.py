from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.pipeline.contracts import file_sha256
from src.pipeline.handoffs.chatgpt_script_parser.app import _normalize_visual_brief
from src.pipeline.handoffs.chatgpt_visual_plan_parser.app import (
    _attach_scene_beats,
    _build_source_index as _build_manual_source_index,
    _normalize_scenes as _normalize_manual_scenes,
    _reconcile_scene_sections,
)
from src.pipeline.visuals.generators.logo_reveal.resolver import resolve_logo_asset, simple_icon_export_for
from src.pipeline.visuals.media_discovery.clip_selector import (
    clip_selection_passes,
    sample_start_seconds,
)
from src.pipeline.visuals.media_discovery.app import (
    _apply_explicit_fallback,
    _candidate_passes_selection_gate,
    _media_constraints_for_scene,
    _media_request_key,
    _normalize_media_scene_payload,
    _queries_for_scene,
    _selection_for_reused_scene,
    _catalog_media_selection,
)
from src.pipeline.visuals.media_discovery.contract import VisualMediaConfig
from src.pipeline.visuals.planner.app import (
    _build_scene_timeline,
    _canonical_screenshot_target,
    _close_timeline_gaps,
    _deterministic_scenes_for_range,
    _episode_script_context,
    _adjacent_duplicate_visual_payloads,
    _fallback_candidate_for_slice,
    _metrics_from_draft,
    _normalize_catalog_scene_reference,
    _normalize_story_candidate_scenes,
    _normalize_overlong_story_scene_slots,
    _prepare_story_scene_draft,
    _script_units_for_story_prompt,
    _semantic_grounding_for_scene,
    _source_for_scene,
    _story_coverage_contract,
    _story_draft_errors,
    _story_for_prompt,
    _story_visual_quality_context,
    _story_scene_timing_errors,
    _truth_bound_screenshot_target,
    _stitch_section,
    _timing_continuation_variants,
    _visual_capabilities_for_prompt,
)
from src.pipeline.visuals.asset_resolver.app import _scene_with_capture_target
from src.pipeline.visuals.asset_catalog.app import (
    _MetadataParser,
    _download_source_linked_video_candidate,
    _difference_hash,
    _hash_distance,
    _largest_srcset_url,
    _logo_entities_from_asset_briefs,
    _image_dimensions_are_usable,
    _source_candidate_telemetry,
    _source_linked_video_candidates,
    _source_video_provider,
    _truth_targets_by_record,
    _video_candidates,
)
from src.pipeline.visuals.payload_validation import validate_scene_payload
from src.pipeline.visuals.common import normalize_text_list
from src.pipeline.visuals.review import run as run_visual_review


def _source_index() -> dict:
    return {
        "records_by_key": {
            "record_apple": {
                "record_key": "record_apple",
                "url": "https://apple.example/release",
                "title": "Apple release",
                "screenshot_target_candidates": ["Apple release"],
            }
        },
        "record_keys_by_story": {"story_apple": ["record_apple"]},
        "story_identity_by_id": {
            "story_apple": {"primary_entity": "Apple", "product_or_project": "Apple Intelligence"}
        },
        "truth_items_by_story": {
            "story_apple": [
                {
                    "story_id": "story_apple",
                    "truth_id": "truth_apple_80_percent",
                    "truth_type": "metric",
                    "record_key": "record_apple",
                    "value_text": "80%",
                    "source_text": "The selected record explicitly reports an 80 percent increase.",
                    "source_field": "content",
                }
            ]
        },
        "truth_items_by_id": {
            "truth_apple_80_percent": {
                "story_id": "story_apple",
                "truth_id": "truth_apple_80_percent",
                "truth_type": "metric",
                "record_key": "record_apple",
                "value_text": "80%",
                "source_text": "The selected record explicitly reports an 80 percent increase.",
                "source_field": "content",
            }
        },
    }


def test_manual_visual_beat_attachment_preserves_authored_semantics() -> None:
    warnings: list[str] = []
    scenes = [
        {
            "scene_id": "scene_001",
            "start_seconds": 0.0,
            "end_seconds": 4.0,
            "covered_unit_orders": [1],
            "payload": {
                "beats": [
                    {
                        "unit_order": 1,
                        "visual_action": "advance_diagram_step",
                        "emphasis_words": ["translator", "translator", "handoff"],
                    }
                ]
            },
        },
        {
            "scene_id": "scene_002",
            "start_seconds": 4.0,
            "end_seconds": 8.0,
            "covered_unit_orders": [2],
            "payload": {},
        },
    ]
    voiceover = {
        "data": {
            "voiceover_package": {
                "chunks": [
                    {
                        "order": 1,
                        "start_seconds": 0.0,
                        "end_seconds": 4.0,
                        "text": "The translator passes context to the next agent.",
                    },
                    {
                        "order": 2,
                        "start_seconds": 4.0,
                        "end_seconds": 8.0,
                        "text": "The API reports a 40 percent improvement.",
                    },
                ]
            }
        }
    }

    attached = _attach_scene_beats(
        scenes=scenes,
        voiceover=voiceover,
        warnings=warnings,
    )

    first = attached[0]["payload"]["beats"][0]
    assert first["visual_action"] == "advance_diagram_step"
    assert first["emphasis_words"] == ["translator", "handoff"]
    assert first["text"] == "The translator passes context to the next agent."

    second = attached[1]["payload"]["beats"][0]
    assert second["visual_action"] == "hold_scene"
    assert second["emphasis_words"] == []
    assert warnings == ["Attached voiceover beat timing to 2 visual scene(s)."]


def test_truth_bound_screenshot_target_overrides_a_loose_lexical_guess() -> None:
    source_index = _source_index()
    record = source_index["records_by_key"]["record_apple"]

    target = _truth_bound_screenshot_target(
        draft={"evidence_truth_ids": ["truth_apple_80_percent"]},
        record=record,
        source_record_key="record_apple",
        source_index=source_index,
        requested_text="Apple release",
    )

    assert target == "The selected record explicitly reports an 80 percent increase."


def test_asset_catalog_maps_script_beats_to_exact_source_targets() -> None:
    package = {
        "story_truth_indexes": [
            {
                "story_id": "story_apple",
                "items": [
                    {
                        "truth_id": "truth_apple_80_percent",
                        "record_key": "record_apple",
                        "source_text": "The selected record explicitly reports an 80 percent increase.",
                        "source_field": "content",
                        "source_order": 3,
                    }
                ],
            }
        ],
        "sections": [
            {
                "section_type": "story",
                "story_id": "story_apple",
                "beats": [
                    {
                        "beat_id": "beat_apple_metric",
                        "support_truth_ids": ["truth_apple_80_percent"],
                    }
                ],
            }
        ],
    }

    targets = _truth_targets_by_record(package)

    assert targets == {
        "record_apple": [
            {
                "beat_id": "beat_apple_metric",
                "truth_id": "truth_apple_80_percent",
                "source_text": "The selected record explicitly reports an 80 percent increase.",
                "source_field": "content",
                "source_order": 3,
            }
        ]
    }


def test_asset_catalog_parser_retains_largest_article_srcset_candidate() -> None:
    parser = _MetadataParser()
    parser.feed(
        '<html><head><meta property="og:image" content="/hero.jpg"></head>'
        '<body><img src="/small.jpg" srcset="/small.jpg 480w, /large.jpg 1600w" '
        'alt="Codex Micro control deck" width="1600" height="900"></body></html>'
    )

    assert parser.metadata["og:image"] == "/hero.jpg"
    assert parser.image_candidates[0]["url"] == "/large.jpg"
    assert parser.image_candidates[0]["alt"] == "Codex Micro control deck"
    assert _largest_srcset_url("/one.jpg 1x, /two.jpg 2x") == "/two.jpg"


def test_asset_catalog_structural_image_policy_accepts_portraits_and_reports_omissions() -> None:
    config = {
        "min_image_short_edge": 480,
        "min_image_pixel_area": 500_000,
    }

    assert _image_dimensions_are_usable(900, 1600, config) is True
    assert _image_dimensions_are_usable(300, 2000, config) is False

    telemetry = _source_candidate_telemetry(
        story_id="story_apple",
        record_key="record_apple",
        source_url="https://apple.example/release",
        discovered_count=12,
        unique_count=10,
        candidate_pool_count=6,
        evaluated_count=3,
        retained_count=2,
    )

    assert telemetry["ordering"] == "declared_source_hero_then_document_order"
    assert telemetry["semantic_reranking_applied"] is False
    assert telemetry["image_candidates_unevaluated_due_to_candidate_limit"] == 4
    assert telemetry["image_candidates_unevaluated_due_to_retention_limit"] == 3


def test_external_media_cannot_use_lexical_ranking_as_semantic_approval(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires semantic_verification.enabled=true"):
        VisualMediaConfig.model_validate(
            {
                "output_dir": str(tmp_path / "media"),
                "trusted_catalog_only": False,
                "semantic_verification": {"enabled": False},
            }
        )

    trusted = VisualMediaConfig.model_validate(
        {
            "output_dir": str(tmp_path / "trusted"),
            "trusted_catalog_only": True,
            "semantic_verification": {"enabled": False},
        }
    )
    assert trusted.trusted_catalog_only is True


def test_asset_catalog_parser_discovers_direct_source_video_and_poster() -> None:
    parser = _MetadataParser()
    parser.feed(
        '<html><head><meta property="og:video" content="/launch.mp4">'
        '<meta property="og:video:type" content="video/mp4"></head>'
        '<body><video src="/demo.webm" poster="/demo-poster.jpg"></video></body></html>'
    )

    candidates = _video_candidates(
        parser,
        "https://example.com/news/story",
        {"max_video_candidates": 8},
    )

    assert [item["url"] for item in candidates] == [
        "https://example.com/launch.mp4",
        "https://example.com/demo.webm",
    ]
    assert parser.image_candidates[0]["image_role"] == "video_poster"


def test_asset_catalog_parser_discovers_only_allowed_source_linked_video_providers() -> None:
    parser = _MetadataParser()
    parser.feed(
        '<html><body><iframe src="https://www.youtube.com/embed/demo"></iframe>'
        '<a href="https://vimeo.com/12345">Watch demo</a>'
        '<a href="https://untrusted.example/video">Other</a></body></html>'
    )

    candidates = _source_linked_video_candidates(
        parser=parser,
        page_url="https://source.example/story",
        record={"record_key": "record_story"},
        config={
            "enabled": True,
            "providers": ["youtube"],
            "max_links_per_record": 3,
        },
    )

    assert _source_video_provider("https://youtu.be/demo") == "youtube"
    assert _source_video_provider("https://x.com/example/status/1") == "x"
    assert [candidate["provider"] for candidate in candidates] == ["youtube"]
    assert candidates[0]["url"] == "https://www.youtube.com/embed/demo"


def test_source_linked_video_resolver_is_bounded_and_marks_suitability_unreviewed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.pipeline.visuals.asset_catalog.app as catalog_app

    monkeypatch.setattr(catalog_app.shutil, "which", lambda _: "/usr/local/bin/yt-dlp")

    def fake_run(command, **kwargs):
        if "--dump-single-json" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "id": "demo",
                        "title": "Selected source demo",
                        "description": "A product walkthrough linked by the article.",
                        "duration": 90,
                        "uploader": "Example",
                    }
                ),
                stderr="",
            )
        output_template = Path(command[command.index("--output") + 1])
        output_template.with_suffix(".mp4").write_bytes(b"fixture-video")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(catalog_app.subprocess, "run", fake_run)
    monkeypatch.setattr(
        catalog_app,
        "_probe_video",
        lambda *_: {"width": 1920, "height": 1080, "duration_seconds": 90.0},
    )

    asset = _download_source_linked_video_candidate(
        story_id="story_demo",
        record={"record_key": "record_demo", "title": "Article"},
        source_url="https://source.example/article",
        candidate={
            "url": "https://www.youtube.com/watch?v=demo",
            "provider": "youtube",
            "video_role": "source_page_video_link",
        },
        candidate_order=1,
        output_dir=tmp_path,
        page_config={
            "max_video_bytes": 10_000,
            "min_video_width": 720,
            "min_video_height": 404,
            "ffprobe_path": "ffprobe",
        },
        linked_config={
            "yt_dlp_path": "yt-dlp",
            "download_timeout_seconds": 10,
            "max_duration_seconds": 120,
            "max_height": 1080,
        },
    )

    assert asset["asset_type"] == "source_video"
    assert asset["provider"] == "youtube"
    assert asset["provenance_trust"]["status"] == "trusted"
    assert asset["narration_suitability"]["status"] == "unreviewed"
    assert Path(asset["local_path"]).exists()


def test_asset_catalog_perceptual_hash_detects_near_duplicate_images() -> None:
    from PIL import Image, ImageDraw

    first = Image.new("RGB", (320, 180), "white")
    ImageDraw.Draw(first).rectangle((30, 30, 290, 150), fill="black")
    second = first.copy()
    ImageDraw.Draw(second).rectangle((31, 30, 291, 150), fill="black")

    first_hash = _difference_hash(first)
    second_hash = _difference_hash(second)

    assert _hash_distance(first_hash, second_hash) <= 5


def test_safe_stitcher_fallback_does_not_invent_a_metric_scene() -> None:
    candidate = _fallback_candidate_for_slice(
        section={"story_id": "story_apple", "section_type": "story"},
        story={"story_id": "story_apple", "story_title": "Apple update"},
        unit_slice={"start_unit_order": 1, "end_unit_order": 1},
        script_units=[
            {
                "order": 1,
                "text": "Apple says performance increased by 80 percent.",
                "source_record_keys": [],
                "visual_brief": {"visual_intent": "metric_explainer"},
            }
        ],
        source_index=_source_index(),
        counts={},
        group_index=1,
        policy={"allowed_render_kinds": ["kinetic_type_scene", "data_counter_scene"]},
    )

    assert candidate["render_kind"] == "kinetic_type_scene"
    assert "metrics" not in candidate["payload"]
    assert candidate["semantic_grounding"]["status"] == "grounded"


def test_visual_prompt_capabilities_only_include_allowed_render_kinds() -> None:
    capabilities = _visual_capabilities_for_prompt(
        {
            "scene_policy": {"allowed_render_kinds": ["context_image_scene"]},
            "visual_capabilities": {
                "context_image_scene": {"description": "enabled"},
                "broll_video_scene": {"description": "disabled"},
            },
        }
    )

    assert set(capabilities) == {"context_image_scene"}
    assert capabilities["context_image_scene"]["description"] == "enabled"
    assert "payload_field_contract" in capabilities["context_image_scene"]

    prompt_root = (
        Path(__file__).parents[1]
        / "src/pipeline/visuals/planner/prompts/v1/story_visual_planner"
    )
    prompt_text = "\n".join(
        (prompt_root / filename).read_text(encoding="utf-8")
        for filename in ("system.txt", "user_preamble.txt")
    )
    assert "broll_video_scene" not in prompt_text


def test_visual_editor_is_not_triggered_only_because_catalog_assets_are_unused() -> None:
    quality = _story_visual_quality_context(
        story_id="story_apple",
        scenes=[
            {
                "render_kind": "context_image_scene",
                "payload": {"asset_id": "asset_used"},
            }
        ],
        asset_catalog_index={
            "assets_by_story": {
                "story_apple": [
                    {"asset_id": "asset_used", "status": "available"},
                    {"asset_id": "asset_unused", "status": "available"},
                ]
            }
        },
        config={
            "scene_policy": {"max_consecutive_same_kind": 2},
            "visual_mix_policy": {"target_max_text_like_scenes_per_story": 2},
        },
        current_errors=[],
    )

    assert quality["unused_asset_ids"] == ["asset_unused"]
    assert quality["review_recommended"] is False
    assert quality["review_reasons"] == []


def test_story_visual_prompt_receives_every_complete_selected_record() -> None:
    records_by_key = {}
    record_keys = []
    for index in range(1, 6):
        key = f"record_{index}"
        marker = f"MEMORABLE_DETAIL_{index}"
        full_record = {
            "record_key": key,
            "title": f"Source {index}",
            "content": ("complete source context " * 90) + marker,
            "url": f"https://example.com/{index}",
            "custom_source_field": f"preserved-{index}",
        }
        record_keys.append(key)
        records_by_key[key] = {
            "full_record": full_record,
            "record_key": key,
            "title": full_record["title"],
            "url": full_record["url"],
            "source_name": "Example",
            "source_group": "company_blogs",
            "published_at": "2026-07-17T00:00:00Z",
            "summary_or_description": "",
            "content": full_record["content"],
            "screenshot_target_candidates": [
                f"Screenshot target {candidate_index} for source {index}"
                for candidate_index in range(1, 16)
            ],
            "truth_screenshot_targets": [],
        }

    context = _story_for_prompt(
        {"story_id": "story_complete", "story_title": "Complete context"},
        {
            "record_keys_by_story": {"story_complete": record_keys},
            "records_by_key": records_by_key,
            "truth_items_by_story": {"story_complete": []},
        },
        {
            "source_policy": {
                "use_selected_stories_only": True,
                "include_full_records": True,
                "max_story_context_chars": 500_000,
            }
        },
        script_units=[],
    )

    assert context["context_telemetry"]["record_count"] == 5
    assert context["context_telemetry"]["records_truncated"] is False
    assert [record["record_key"] for record in context["records"]] == record_keys
    for index, record in enumerate(context["records"], start=1):
        assert f"MEMORABLE_DETAIL_{index}" in record["content"]
        assert record["custom_source_field"] == f"preserved-{index}"
        assert record["screenshot_target_candidates"][-1] == f"Screenshot target 15 for source {index}"


def test_episode_visual_director_context_keeps_every_timed_script_unit() -> None:
    marker = "END_OF_LONG_TIMED_SCRIPT_UNIT"
    units = [
        {
            "unit_id": "unit_001",
            "story_id": "story_complete",
            "start_seconds": 0.0,
            "end_seconds": 12.0,
            "text": ("complete narration context " * 30) + marker,
            "custom_timing_field": "preserved",
        }
    ]

    context = _episode_script_context(units)

    assert context["telemetry"]["context_mode"] == "complete_timed_script_units"
    assert context["telemetry"]["units_truncated"] is False
    assert marker in context["units"][0]["text"]
    assert context["units"][0]["custom_timing_field"] == "preserved"


def test_story_title_transition_reuses_llm_selected_opening_media() -> None:
    story = {
        "story_id": "story_apple",
        "story_title": "Apple ships a new release",
        "video_segment": {"segment_order": 2},
    }
    section = {
        "section_type": "story",
        "story_id": "story_apple",
        "start_unit_order": 1,
        "end_unit_order": 2,
        "title_card": {
            "display_title": "Apple ships a new release",
            "subtitle": "What changed",
            "duration_seconds": 2.8,
        },
        "script_units": [
            {"order": 1, "text": "Next, Apple has an update."},
            {"order": 2, "text": "Here is what changed."},
        ],
    }
    story_draft = {
        "scene_timeline": [
            {
                "order": 1,
                "start_unit_order": 1,
                "end_unit_order": 1,
                "render_kind": "context_image_scene",
                "evidence_record_keys": ["record_apple"],
                "evidence_truth_ids": [],
                "evidence_text": "The selected release image introduces the story.",
                "grounding_basis": "selected_record",
                "payload_json": json.dumps(
                    {
                        "asset_id": "asset_source_image_apple",
                        "shot_style": "wide",
                        "overlay_headline": "",
                        "motion_style": "slow_push",
                        "show_overlay": False,
                    }
                ),
            },
            {
                "order": 2,
                "start_unit_order": 2,
                "end_unit_order": 2,
                "render_kind": "editorial_text_scene",
                "evidence_record_keys": [],
                "evidence_truth_ids": [],
                "evidence_text": "Here is what changed.",
                "grounding_basis": "script_beat",
                "payload_json": json.dumps(
                    {
                        "headline": "What changed",
                        "accent_words": ["changed"],
                        "composition": "editorial_center",
                        "motion_style": "word_reveal",
                    }
                ),
            },
        ]
    }
    asset = {
        "asset_id": "asset_source_image_apple",
        "asset_type": "source_image",
        "story_id": "story_apple",
        "status": "available",
        "source_record_key": "record_apple",
        "source_url": "https://apple.example/release",
    }

    scenes = _normalize_story_candidate_scenes(
        story=story,
        section=section,
        source_index=_source_index(),
        story_draft=story_draft,
        asset_catalog_index={
            "assets_by_id": {asset["asset_id"]: asset},
            "assets_by_story": {"story_apple": [asset]},
        },
        counts=Counter(),
        config={
            "scene_policy": {
                "allowed_render_kinds": [
                    "context_image_scene",
                    "editorial_text_scene",
                    "story_transition_scene",
                ],
                "numeric_scene_failure_mode": "replan",
            }
        },
    )

    transition = scenes[0]
    assert transition["render_kind"] == "story_transition_scene"
    assert transition["payload"]["asset_id"] == "asset_source_image_apple"
    assert transition["payload"]["background_media_type"] == "image"
    assert transition["source_record_keys"] == ["record_apple"]


def test_story_owned_catalog_image_bypasses_external_media_search(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"fixture-image")
    (tmp_path / "resolved").mkdir()
    scene = {
        "scene_id": "scene_004",
        "story_id": "story_apple",
        "render_kind": "context_image_scene",
        "payload": {"asset_id": "asset_source_image_apple"},
    }
    selection = _catalog_media_selection(
        scene,
        assets_by_id={
            "asset_source_image_apple": {
                "asset_id": "asset_source_image_apple",
                "story_id": "story_apple",
                "asset_type": "source_image",
                "status": "available",
                "review_status": "trusted_source",
                "local_path": str(source),
                "source_url": "https://apple.example/release",
                "asset_url": "https://apple.example/hero.jpg",
                "title": "Apple release image",
            }
        },
        images_dir=tmp_path / "resolved",
    )

    assert selection is not None
    assert selection["provider"] == "asset_catalog"
    assert selection["provenance_verification"]["status"] == "trusted_source_asset"
    assert selection["provenance_verification"]["passed"] is True
    assert selection["semantic_verification"]["status"] == "not_independently_reviewed"
    assert selection["semantic_verification"]["passed"] is None
    assert Path(selection["asset_path"]).read_bytes() == b"fixture-image"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)
def test_story_owned_catalog_video_is_prepared_without_external_search(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x243447:s=1280x720:d=1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )
    request = VisualMediaConfig.model_validate(
            {
                "output_dir": str(tmp_path / "media"),
                "trusted_catalog_only": True,
                "semantic_verification": {"enabled": False},
            }
    )
    envelope = type(
        "RequestEnvelope",
        (),
        {"config": request},
    )()
    scene = {
        "scene_id": "scene_005",
        "story_id": "story_apple",
        "render_kind": "broll_video_scene",
        "duration_seconds": 2.0,
        "payload": {"asset_id": "asset_source_video_apple"},
    }

    selection = _catalog_media_selection(
        scene,
        assets_by_id={
            "asset_source_video_apple": {
                "asset_id": "asset_source_video_apple",
                "story_id": "story_apple",
                "asset_type": "source_video",
                "status": "available",
                "review_status": "trusted_source",
                "local_path": str(source),
                "source_url": "https://apple.example/release",
                "asset_url": "https://apple.example/demo.mp4",
                "title": "Apple product demo",
                "width": 1280,
                "height": 720,
            }
        },
        images_dir=tmp_path / "images",
        videos_dir=tmp_path / "videos",
        request=envelope,
    )

    assert selection is not None
    assert selection["provider"] == "asset_catalog"
    assert selection["media_type"] == "video"
    assert selection["clip_duration_seconds"] == pytest.approx(2.75)
    assert Path(selection["asset_path"]).exists()


def test_asset_catalog_uses_explicit_script_logo_briefs_as_identity_candidates() -> None:
    assert _logo_entities_from_asset_briefs(
        [
            {
                "requested_asset_types": ["logo", "code_graphic"],
                "subject": "OpenAI logo",
                "must_show": ["OpenAI", "ChatGPT"],
            },
            {
                "requested_asset_types": ["source_page"],
                "subject": "Not an identity request",
                "must_show": [],
            },
        ]
    ) == ["OpenAI", "ChatGPT"]


def test_failed_story_plan_is_not_replaced_when_fallbacks_are_disabled() -> None:
    scenes = _build_scene_timeline(
        story_sections=[
            {
                "section_type": "story",
                "story_id": "story_apple",
                "start_unit_order": 1,
                "end_unit_order": 2,
            }
        ],
        script_units=[
            {"order": 1, "start_seconds": 0.0, "end_seconds": 2.0, "text": "Apple update."},
            {"order": 2, "start_seconds": 2.0, "end_seconds": 5.0, "text": "Here is what changed."},
        ],
        stories=[{"story_id": "story_apple", "story_title": "Apple update"}],
        source_index=_source_index(),
        story_drafts={
            "story_apple": {
                "story_id": "story_apple",
                "scene_timeline": [],
                "planning_failed": True,
            }
        },
        config={
            "allow_deterministic_story_fallbacks": False,
            "scene_policy": {
                "allowed_render_kinds": ["kinetic_type_scene"],
                "max_scene_seconds": 14.0,
            },
        },
    )

    assert scenes == []


def test_story_coverage_contract_reserves_title_and_requires_remaining_units() -> None:
    contract = _story_coverage_contract(
        {
            "start_unit_order": 14,
            "end_unit_order": 19,
            "title_card": {"display_title": "Samsung privacy dilemma"},
        }
    )

    assert contract["required_unit_orders"] == [15, 16, 17, 18, 19]
    assert [
        (slot["start_unit_order"], slot["end_unit_order"])
        for slot in contract["required_scene_slots"]
    ] == [(15, 15), (16, 16), (17, 17), (18, 18), (19, 19)]


def test_unknown_context_media_asset_id_is_removed_without_asset_substitution() -> None:
    normalized, repairs = _normalize_catalog_scene_reference(
        {
            "render_kind": "context_image_scene",
            "asset_id": "asset_source_image_example",
            "search_queries": ["Built Technologies document workflow"],
            "must_show": ["real estate finance documents"],
        },
        story_id="story_built",
        catalog_index={"assets_by_id": {}, "assets_by_story": {}},
        allowed_render_kinds={"context_image_scene"},
    )

    assert "asset_id" not in normalized
    assert normalized["search_queries"] == ["Built Technologies document workflow"]
    assert repairs == [
        "removed unknown catalog asset reference 'asset_source_image_example' from media brief"
    ]


def test_story_title_echo_and_missing_real_anchor_are_quality_warnings_by_default() -> None:
    section = {
        "start_unit_order": 1,
        "end_unit_order": 2,
        "title_card": {"display_title": "Apple update"},
        "script_units": [
            {
                "order": 1,
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "duration_seconds": 2.0,
                "text": "Apple update.",
            },
            {
                "order": 2,
                "start_seconds": 2.0,
                "end_seconds": 8.0,
                "duration_seconds": 6.0,
                "text": "Here is what changed for users.",
            },
        ],
    }
    draft = {
        "story_id": "story_apple",
        "scene_timeline": [
            {
                "order": 1,
                "start_unit_order": 1,
                "end_unit_order": 1,
                "render_kind": "source_article_scene",
                "script_excerpt": "Apple update.",
                "visual_intent": "story title",
                "evidence_record_keys": ["record_apple"],
                "evidence_truth_ids": [],
                "evidence_text": "",
                "grounding_basis": "selected_record",
                "payload_json": json.dumps(
                    {
                        "asset_id": "asset_source_page_apple",
                        "url": "https://apple.example/release",
                        "source_record_key": "record_apple",
                        "target_text": "Apple release",
                        "highlight_phrases": ["Apple release"],
                        "crop_strategy": "headline_then_body",
                        "overlay_headline": "Apple update",
                        "motion_style": "highlight_scan",
                    }
                ),
                "reason": "Provider echoed the system-owned title unit.",
            },
            {
                "order": 2,
                "start_unit_order": 2,
                "end_unit_order": 2,
                "render_kind": "editorial_text_scene",
                "script_excerpt": "Here is what changed for users.",
                "visual_intent": "takeaway",
                "evidence_record_keys": [],
                "evidence_truth_ids": [],
                "evidence_text": "",
                "grounding_basis": "script_beat",
                "payload_json": json.dumps(
                    {
                        "headline": "What changes for users",
                        "accent_words": ["changes"],
                        "composition": "editorial_center",
                        "motion_style": "word_reveal",
                    }
                ),
                "reason": "Emphasize the active narration beat.",
            },
        ],
    }
    catalog_index = {
        "assets_by_id": {
            "asset_source_page_apple": {
                "asset_id": "asset_source_page_apple",
                "asset_type": "source_page",
                "story_id": "story_apple",
                "status": "available",
                "source_record_key": "record_apple",
                "source_url": "https://apple.example/release",
            }
        },
        "assets_by_story": {
            "story_apple": [
                {
                    "asset_id": "asset_source_page_apple",
                    "asset_type": "source_page",
                    "story_id": "story_apple",
                    "status": "available",
                    "source_record_key": "record_apple",
                    "source_url": "https://apple.example/release",
                }
            ]
        },
    }
    config = {
        "require_real_anchor_per_story": True,
        "real_anchor_failure_mode": "warn",
        "scene_policy": {
            "allowed_render_kinds": [
                "source_article_scene",
                "editorial_text_scene",
                "story_transition_scene",
            ],
            "max_scene_seconds": 14.0,
            "hard_max_scene_seconds": 16.0,
            "hard_cap_tolerance_seconds": 0.25,
            "unit_assignment_mode": "one_scene_per_script_unit",
            "numeric_scene_failure_mode": "replan",
        },
    }

    errors = _story_draft_errors(
        draft,
        story_id="story_apple",
        section=section,
        source_index=_source_index(),
        asset_catalog_index=catalog_index,
        config=config,
    )

    assert errors == []

    config["real_anchor_failure_mode"] = "fail"
    strict_errors = _story_draft_errors(
        draft,
        story_id="story_apple",
        section=section,
        source_index=_source_index(),
        asset_catalog_index=catalog_index,
        config=config,
    )
    assert strict_errors == [
        "story plan must reference at least one available verified_asset_catalog asset_id"
    ]


def test_long_bookend_unit_is_split_without_crossing_authored_boundaries() -> None:
    script_units = [
        {
            "order": 1,
            "start_seconds": 0.0,
            "end_seconds": 28.0,
            "duration_seconds": 28.0,
            "text": "A long authored opening beat that still needs render-safe timing.",
            "source_record_keys": [],
            "support_truth_ids": [],
        }
    ]
    scenes = _deterministic_scenes_for_range(
        section={
            "section_type": "intro",
            "story_id": "",
            "start_unit_order": 1,
            "end_unit_order": 1,
        },
        story={},
        start_unit=1,
        end_unit=1,
        script_units=script_units,
        source_index={
            "records_by_key": {},
            "record_keys_by_story": {},
            "story_identity_by_id": {},
            "truth_items_by_story": {},
            "truth_items_by_id": {},
        },
        counts=Counter(),
        policy={
            "allowed_render_kinds": ["editorial_text_scene"],
            "max_scene_seconds": 14.0,
            "hard_max_scene_seconds": 16.0,
            "hard_cap_tolerance_seconds": 0.25,
            "compact_per_chunk_scenes": True,
        },
    )

    assert len(scenes) == 2
    assert [scene["covered_unit_orders"] for scene in scenes] == [[1], [1]]
    assert max(scene["duration_seconds"] for scene in scenes) == 14.0


def test_overlong_story_unit_requires_distinct_planner_treatments() -> None:
    section = {
        "script_units": [
            {
                "order": 2,
                "start_seconds": 10.0,
                "end_seconds": 38.0,
                "duration_seconds": 28.0,
            }
        ]
    }
    first = {
        "order": 1,
        "start_unit_order": 2,
        "end_unit_order": 2,
        "render_kind": "kinetic_type_scene",
        "payload_json": json.dumps({"phrases": ["First idea"]}),
    }
    duplicate = {**first, "order": 2}
    distinct = {
        **first,
        "order": 2,
        "render_kind": "architecture_flow_scene",
        "payload_json": json.dumps({"headline": "How it works", "steps": [{"label": "A"}, {"label": "B"}]}),
    }

    single_errors = _story_scene_timing_errors([first], section=section, max_scene_seconds=14.0)
    duplicate_errors = _story_scene_timing_errors([first, duplicate], section=section, max_scene_seconds=14.0)
    strict_duplicate_errors = _story_scene_timing_errors(
        [first, duplicate],
        section=section,
        max_scene_seconds=14.0,
        duplicate_subscene_policy="fail",
    )
    distinct_errors = _story_scene_timing_errors([first, distinct], section=section, max_scene_seconds=14.0)

    assert any("requires exactly 2 distinct visual treatments" in error for error in single_errors)
    assert duplicate_errors == []
    assert any("duplicated render payloads" in error for error in strict_duplicate_errors)
    assert distinct_errors == []


def test_continue_policy_expands_one_honest_overlong_visual_into_timed_slices() -> None:
    section = {
        "start_unit_order": 31,
        "end_unit_order": 31,
        "script_units": [
            {
                "order": 31,
                "start_seconds": 100.0,
                "end_seconds": 117.08,
                "duration_seconds": 17.08,
            }
        ],
    }
    draft = {
        "story_id": "story_xai",
        "scene_timeline": [
            {
                "order": 1,
                "start_unit_order": 31,
                "end_unit_order": 31,
                "render_kind": "editorial_text_scene",
                "payload_json": json.dumps({"headline": "AI accountability"}),
            }
        ],
        "warnings": [],
    }

    repairs = _normalize_overlong_story_scene_slots(
        draft,
        section=section,
        config={
            "scene_policy": {
                "unit_assignment_mode": "one_scene_per_script_unit",
                "max_scene_seconds": 14.0,
                "hard_max_scene_seconds": 16.0,
                "hard_cap_tolerance_seconds": 0.25,
                "duplicate_subscene_policy": "continue",
            }
        },
    )

    assert len(draft["scene_timeline"]) == 2
    assert [scene["order"] for scene in draft["scene_timeline"]] == [1, 2]
    assert repairs == ["expanded overlong unit 31 into 2 timed continuation slices"]
    assert _story_scene_timing_errors(
        draft["scene_timeline"],
        section=section,
        max_scene_seconds=14.0,
        hard_max_scene_seconds=16.0,
        hard_cap_tolerance_seconds=0.25,
        duplicate_subscene_policy="continue",
    ) == []


def test_small_scene_target_overrun_is_allowed_below_hard_cap() -> None:
    section = {
        "script_units": [
            {
                "order": 11,
                "start_seconds": 90.0,
                "end_seconds": 104.45,
                "duration_seconds": 14.45,
            }
        ]
    }
    scene = {
        "order": 1,
        "start_unit_order": 11,
        "end_unit_order": 11,
        "render_kind": "data_counter_scene",
        "payload_json": json.dumps({"headline": "Funding", "metrics": [{"value": "439"}]}),
    }

    errors = _story_scene_timing_errors(
        [scene],
        section=section,
        max_scene_seconds=14.0,
        hard_max_scene_seconds=16.0,
    )
    contract = _story_coverage_contract(
        {
            "start_unit_order": 11,
            "end_unit_order": 11,
            "script_units": section["script_units"],
        },
        max_scene_seconds=14.0,
        hard_max_scene_seconds=16.0,
    )

    assert errors == []
    assert contract["deterministic_timing_splits"] == []
    assert contract["required_scene_slots"] == [
        {
            "slot_id": "unit_011_slice_01",
            "start_unit_order": 11,
            "end_unit_order": 11,
            "slice_index": 1,
            "slice_count": 1,
        }
    ]
    assert contract["target_max_scene_seconds"] == 14.0
    assert contract["hard_max_scene_seconds"] == 16.0


def test_subsecond_hard_cap_rounding_tolerance_does_not_force_duplicate_scene() -> None:
    contract = _story_coverage_contract(
        {
            "start_unit_order": 32,
            "end_unit_order": 32,
            "script_units": [
                {
                    "order": 32,
                    "start_seconds": 100.0,
                    "end_seconds": 116.08,
                    "duration_seconds": 16.08,
                }
            ],
        },
        max_scene_seconds=14.0,
        hard_max_scene_seconds=16.0,
        hard_cap_tolerance_seconds=0.25,
    )

    assert contract["deterministic_timing_splits"] == []
    assert len(contract["required_scene_slots"]) == 1
    assert contract["effective_hard_max_scene_seconds"] == 16.25


def test_stitcher_allocates_one_long_unit_across_distinct_planned_scenes() -> None:
    candidates = [
        {
            "planner_order": 1,
            "story_id": "story_apple",
            "story_title": "Apple update",
            "section_type": "story",
            "start_unit_order": 1,
            "end_unit_order": 1,
            "render_kind": "kinetic_type_scene",
            "script_excerpt": "First, establish the problem.",
            "visual_intent": "Show the problem.",
            "payload": {"phrases": ["THE PROBLEM"]},
            "source_record_keys": [],
            "source_urls": [],
            "semantic_grounding": {"status": "grounded", "errors": []},
        },
        {
            "planner_order": 2,
            "story_id": "story_apple",
            "story_title": "Apple update",
            "section_type": "story",
            "start_unit_order": 1,
            "end_unit_order": 1,
            "render_kind": "logo_reveal_scene",
            "script_excerpt": "Then reveal who changes it.",
            "visual_intent": "Reveal the entity.",
            "payload": {"primary_entity": "Apple"},
            "source_record_keys": [],
            "source_urls": [],
            "semantic_grounding": {"status": "grounded", "errors": []},
        },
    ]
    scenes = _stitch_section(
        section={"section_type": "story", "story_id": "story_apple", "start_unit_order": 1, "end_unit_order": 1},
        candidates=candidates,
        script_units=[
            {
                "order": 1,
                "start_seconds": 0.0,
                "end_seconds": 20.0,
                "text": "First, establish the problem. Then reveal who changes it.",
            }
        ],
        story={"story_id": "story_apple", "story_title": "Apple update"},
        source_index=_source_index(),
        counts=Counter(),
        policy={"max_scene_seconds": 14.0, "allowed_render_kinds": ["kinetic_type_scene", "logo_reveal_scene"]},
    )

    assert [(scene["start_seconds"], scene["end_seconds"]) for scene in scenes] == [(0.0, 10.0), (10.0, 20.0)]
    assert [scene["render_kind"] for scene in scenes] == ["kinetic_type_scene", "logo_reveal_scene"]
    assert [scene["script_excerpt"] for scene in scenes] == [
        "First, establish the problem.",
        "Then reveal who changes it.",
    ]


def test_stitcher_refuses_to_clone_one_long_semantic_scene() -> None:
    with pytest.raises(ValueError, match="requires 2 distinct planner scenes"):
        _stitch_section(
            section={"section_type": "story", "story_id": "story_apple", "start_unit_order": 1, "end_unit_order": 1},
            candidates=[
                {
                    "planner_order": 1,
                    "story_id": "story_apple",
                    "story_title": "Apple update",
                    "section_type": "story",
                    "start_unit_order": 1,
                    "end_unit_order": 1,
                    "render_kind": "source_article_scene",
                    "script_excerpt": "First show the headline. Then focus on the supporting detail.",
                    "visual_intent": "Use the selected source as proof.",
                    "payload": {
                        "url": "https://apple.example/release",
                        "source_record_key": "record_apple",
                        "crop_strategy": "headline_then_body",
                        "motion_style": "slow_push",
                    },
                    "source_record_keys": ["record_apple"],
                    "source_urls": ["https://apple.example/release"],
                    "semantic_grounding": {"status": "grounded", "errors": []},
                }
            ],
            script_units=[
                {
                    "order": 1,
                    "start_seconds": 0.0,
                    "end_seconds": 28.0,
                    "text": "First show the headline. Then focus on the supporting detail.",
                }
            ],
            story={"story_id": "story_apple", "story_title": "Apple update"},
            source_index=_source_index(),
            counts=Counter(),
            policy={"max_scene_seconds": 14.0, "allowed_render_kinds": ["source_article_scene"]},
        )


def test_adjacent_identical_render_payloads_are_reported() -> None:
    scenes = [
        {"scene_id": "scene_001", "story_id": "story_apple", "render_kind": "kinetic_type_scene", "payload": {"phrases": ["SAME"]}},
        {"scene_id": "scene_002", "story_id": "story_apple", "render_kind": "kinetic_type_scene", "payload": {"phrases": ["SAME"]}},
    ]

    assert _adjacent_duplicate_visual_payloads(scenes) == [
        {
            "first_scene_id": "scene_001",
            "second_scene_id": "scene_002",
            "render_kind": "kinetic_type_scene",
        }
    ]


def test_repeated_overlong_slices_become_rendered_continuation_phases() -> None:
    candidate = {
        "story_id": "story_apple",
        "start_unit_order": 2,
        "end_unit_order": 2,
        "render_kind": "simple_explainer_scene",
        "payload": {
            "headline": "Two parts of one idea",
            "items": [
                {"label": "Scale", "detail": "$500B"},
                {"label": "Precision", "detail": "Document intelligence"},
            ],
            "orientation": "horizontal",
            "motion_style": "sequential_focus",
        },
    }

    variants = _timing_continuation_variants(
        [{**candidate, "planner_order": 1}, {**candidate, "planner_order": 2}]
    )
    scenes = [
        {"scene_id": f"scene_{index:03d}", **variant}
        for index, variant in enumerate(variants, start=1)
    ]

    assert [scene["payload"]["focus_item_label"] for scene in scenes] == [
        "Scale",
        "Precision",
    ]
    assert [scene["payload"]["continuation_index"] for scene in scenes] == [1, 2]
    assert _adjacent_duplicate_visual_payloads(scenes) == []


def test_cosmetic_motion_changes_do_not_hide_duplicate_visuals() -> None:
    scenes = [
        {
            "scene_id": "scene_001",
            "story_id": "story_apple",
            "render_kind": "source_article_scene",
            "payload": {
                "url": "https://example.com/story",
                "target_text": "The same source detail",
                "motion_style": "slow_push",
                "crop_strategy": "headline_then_body",
            },
        },
        {
            "scene_id": "scene_002",
            "story_id": "story_apple",
            "render_kind": "source_article_scene",
            "payload": {
                "url": "https://example.com/story",
                "target_text": "The same source detail",
                "motion_style": "highlight_scan",
                "crop_strategy": "target_text_focus",
            },
        },
    ]

    assert len(_adjacent_duplicate_visual_payloads(scenes)) == 1


def test_gap_closer_does_not_hide_missing_script_units() -> None:
    scenes = [
        {
            "start_seconds": 10.0,
            "end_seconds": 20.0,
            "duration_seconds": 10.0,
            "covered_unit_orders": [13],
        },
        {
            "start_seconds": 80.0,
            "end_seconds": 84.0,
            "duration_seconds": 4.0,
            "covered_unit_orders": [20],
        },
    ]

    _close_timeline_gaps(scenes, 14.0)

    assert scenes[1]["start_seconds"] == 80.0
    assert scenes[1]["duration_seconds"] == 4.0


def test_metric_payload_is_never_synthesized_from_numbers_in_prose() -> None:
    assert _metrics_from_draft({}, "Apple scored 100 while OpenAI scored 80.") == []


def test_story_prompt_exposes_only_each_beats_eligible_metrics() -> None:
    source_index = _source_index()
    source_index["truth_items_by_id"]["truth_apple_45_minutes"] = {
        "story_id": "story_apple",
        "truth_id": "truth_apple_45_minutes",
        "truth_type": "metric",
        "record_key": "record_apple",
        "value_text": "45 minutes",
        "source_text": "The selected record reports a 45 minute setup time.",
    }

    units = _script_units_for_story_prompt(
        [
            {"order": 1, "text": "Performance rose.", "support_truth_ids": ["truth_apple_80_percent"]},
            {"order": 2, "text": "Setup took less time.", "support_truth_ids": ["truth_apple_45_minutes"]},
            {"order": 3, "text": "The workflow changed.", "support_truth_ids": []},
        ],
        source_index=source_index,
        story_id="story_apple",
    )

    assert [item["truth_id"] for item in units[0]["eligible_numeric_truth_items"]] == [
        "truth_apple_80_percent"
    ]
    assert [item["truth_id"] for item in units[1]["eligible_numeric_truth_items"]] == [
        "truth_apple_45_minutes"
    ]
    assert units[2]["eligible_numeric_truth_items"] == []
    assert units[2]["numeric_graphics_allowed"] is False


def test_catalog_asset_type_selects_the_matching_render_kind() -> None:
    scene = _prepare_story_scene_draft(
        {
            "order": 1,
            "start_unit_order": 1,
            "end_unit_order": 1,
            "render_kind": "context_image_scene",
            "script_excerpt": "Apple enters the story.",
            "visual_intent": "Introduce Apple.",
            "evidence_record_keys": [],
            "evidence_truth_ids": [],
            "evidence_text": "Apple enters the story.",
            "grounding_basis": "context_media",
            "payload_json": json.dumps({"asset_id": "asset_logo_apple"}),
            "reason": "Use the available identity asset.",
        },
        story_id="story_apple",
        section={"script_units": [{"order": 1, "text": "Apple enters the story."}]},
        source_index=_source_index(),
        asset_catalog_index={
            "assets_by_id": {
                "asset_logo_apple": {
                    "asset_id": "asset_logo_apple",
                    "asset_type": "logo",
                    "story_id": "story_apple",
                    "status": "available",
                    "title": "Apple",
                }
            },
            "assets_by_story": {},
        },
        config={
            "scene_policy": {
                "allowed_render_kinds": ["context_image_scene", "logo_reveal_scene"]
            }
        },
    )

    assert scene["render_kind"] == "logo_reveal_scene"
    assert scene["primary_entity"] == "Apple"
    assert "mapped context_image_scene to logo_reveal_scene" in scene["contract_repairs"][0]


def test_numeric_scene_is_not_semantically_rejected_by_literal_matching_code() -> None:
    source_index = _source_index()
    source_index["truth_items_by_id"]["truth_apple_45_minutes"] = {
        "story_id": "story_apple",
        "truth_id": "truth_apple_45_minutes",
        "truth_type": "metric",
        "record_key": "record_apple",
        "value_text": "45 minutes",
        "source_text": "The selected record reports a 45 minute setup time.",
    }
    scene = _prepare_story_scene_draft(
        {
            "order": 1,
            "start_unit_order": 2,
            "end_unit_order": 2,
            "render_kind": "data_counter_scene",
            "script_excerpt": "Performance rose by 80 percent.",
            "visual_intent": "Show the reported change.",
            "evidence_record_keys": ["record_apple"],
            "evidence_truth_ids": ["truth_apple_45_minutes"],
            "evidence_text": "A different beat mentions 45 minutes.",
            "grounding_basis": "selected_record",
            "payload_json": json.dumps(
                {
                    "headline": "Performance",
                    "metrics": [{"label": "Gain", "value": "45 minutes"}],
                }
            ),
            "reason": "Display a number.",
        },
        story_id="story_apple",
        section={
            "script_units": [
                {
                    "order": 1,
                    "text": "Setup took 45 minutes.",
                    "support_truth_ids": ["truth_apple_45_minutes"],
                    "source_record_keys": ["record_apple"],
                },
                {
                    "order": 2,
                    "text": "Performance rose by 80 percent.",
                    "support_truth_ids": ["truth_apple_80_percent"],
                    "source_record_keys": ["record_apple"],
                },
            ]
        },
        source_index=source_index,
        asset_catalog_index={"assets_by_id": {}, "assets_by_story": {}},
        config={
            "scene_policy": {
                "allowed_render_kinds": ["data_counter_scene", "source_article_scene"]
            }
        },
    )

    assert scene["render_kind"] == "data_counter_scene"
    assert "contract_repairs" not in scene
    assert "contract_validation_errors" not in scene


def test_visual_payload_validation_rejects_incomplete_semantic_graphics() -> None:
    assert validate_scene_payload(
        "bar_chart_scene",
        {
            "headline": "Reported benchmark",
            "bars": [
                {"label": "Before", "value": "unknown"},
                {"label": "After", "value": "88"},
            ],
        },
    ) == ["payload.bars[1].value must contain a numeric value"]
    assert "payload.active_step_label is required" in validate_scene_payload(
        "architecture_flow_scene",
        {
            "headline": "Request path",
            "steps": [{"label": "Client"}, {"label": "API"}],
        },
    )
    assert validate_scene_payload(
        "logo_reveal_scene",
        {
            "primary_entity": "Amazon",
            "companion_text": "A concise identity moment",
        },
    ) == []
    assert "payload.companion_text must be at most 90 characters for readable rendering" in validate_scene_payload(
        "logo_reveal_scene",
        {
            "primary_entity": "Amazon",
            "companion_text": "x" * 91,
        },
    )
    assert validate_scene_payload(
        "data_counter_scene",
        {
            "headline": "Efficiency delta",
            "metrics": [{"label": "Reported gain", "value": "Competitive Edge"}],
        },
    ) == ["payload.metrics[1].value must contain a numeric value"]


def test_visual_payload_validation_checks_nested_relationships() -> None:
    ecosystem_errors = validate_scene_payload(
        "ecosystem_map_scene",
        {
            "headline": "Platform relationships",
            "focus_entity": "OpenAI",
            "nodes": [
                {"id": "openai", "label": "OpenAI"},
                {"id": "developers", "label": "Developers"},
            ],
            "edges": [{"from": "openai", "to": "missing", "label": "serves"}],
        },
    )
    matrix_errors = validate_scene_payload(
        "capability_matrix_scene",
        {
            "headline": "Product tradeoffs",
            "columns": ["Speed", "Cost"],
            "rows": [
                {"label": "Product A", "values": ["Fast"]},
                {"label": "Product B", "values": ["Medium", "Low"]},
            ],
        },
    )

    assert "payload.edges[1].to does not reference a node id" in ecosystem_errors
    assert "payload.rows[1].values must contain exactly 2 value(s), one per column" in matrix_errors


def test_semantic_graphic_accepts_selected_record_or_canonical_script_beat_grounding() -> None:
    invalid = _semantic_grounding_for_scene(
        draft={"evidence_record_keys": [], "evidence_text": ""},
        render_kind="data_counter_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={"headline": "Reported performance increase", "metrics": [{"label": "Performance", "value": "80%"}]},
        source_index=_source_index(),
    )
    valid = _semantic_grounding_for_scene(
        draft={
            "evidence_record_keys": ["record_apple"],
            "evidence_truth_ids": ["truth_apple_80_percent"],
            "evidence_text": "The selected record explicitly reports an 80 percent increase.",
            "grounding_basis": "selected_record",
        },
        render_kind="data_counter_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={"headline": "Reported performance increase", "metrics": [{"label": "Reported increase", "value": "80%"}]},
        source_index=_source_index(),
    )
    script_beat = _semantic_grounding_for_scene(
        draft={
            "evidence_record_keys": [],
            "evidence_text": "The assigned narration contrasts privacy with data retention.",
            "grounding_basis": "script_beat",
        },
        render_kind="entity_compare_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={
            "headline": "Privacy or retention",
            "entities": ["Privacy", "Data retention"],
            "comparison_axis": "User choice",
        },
        source_index=_source_index(),
    )
    missing_selected_record = _semantic_grounding_for_scene(
        draft={
            "evidence_record_keys": [],
            "evidence_text": "Claims to use a selected record without naming one.",
            "grounding_basis": "selected_record",
        },
        render_kind="entity_compare_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={
            "headline": "Product comparison",
            "entities": ["Product A", "Product B"],
            "comparison_axis": "Capabilities",
        },
        source_index=_source_index(),
    )

    assert invalid["status"] == "invalid"
    assert valid["status"] == "grounded"
    assert script_beat["status"] == "grounded"
    assert missing_selected_record["status"] == "invalid"


def test_numeric_graphic_context_is_owned_by_llm_and_structural_provenance() -> None:
    result = _semantic_grounding_for_scene(
        draft={
            "evidence_record_keys": ["record_apple"],
            "evidence_truth_ids": ["truth_apple_80_percent"],
            "evidence_text": "The selected record reports an 80 percent increase.",
            "grounding_basis": "selected_record",
        },
        render_kind="data_counter_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={
            "headline": "Reported performance increase",
            "metrics": [{"label": "Reported increase", "value": "100%"}],
        },
        source_index=_source_index(),
    )

    assert result["status"] == "grounded"
    assert result["errors"] == []


def test_manual_visual_plan_preserves_the_same_numeric_truth_contract() -> None:
    source_index = _build_manual_source_index(
        {
            "stories": [
                {
                    "story_id": "story_apple",
                    "records": [
                        {
                            "record_key": "record_apple",
                            "url": "https://apple.example/release",
                        }
                    ],
                }
            ]
        },
        {
            "story_truth_indexes": [
                {
                    "story_id": "story_apple",
                    "items": [
                        {
                            "truth_id": "truth_apple_80_percent",
                            "truth_type": "metric",
                            "record_key": "record_apple",
                            "value_text": "80%",
                        }
                    ],
                }
            ]
        },
    )
    errors: list[str] = []
    scenes = _normalize_manual_scenes(
        scenes=[
            {
                "scene_id": "scene_001",
                "story_id": "story_apple",
                "section_type": "story",
                "start_seconds": 0,
                "end_seconds": 6,
                "render_kind": "data_counter_scene",
                "script_excerpt": "The report says performance rose by 80 percent.",
                "visual_intent": "Show the exact reported gain.",
                "evidence_record_keys": ["record_apple"],
                "evidence_truth_ids": ["truth_apple_80_percent"],
                "evidence_text": "The assigned metric truth reports 80 percent.",
                "grounding_basis": "selected_record",
                "payload": {
                    "headline": "Reported performance gain",
                    "metrics": [{"label": "Gain", "value": "80%"}],
                },
                "covered_unit_orders": [1],
            }
        ],
        allowed_render_kinds={"data_counter_scene"},
        source_index=source_index,
        asset_catalog_index={},
        errors=errors,
        warnings=[],
    )

    assert errors == []
    assert scenes[0]["evidence_truth_ids"] == ["truth_apple_80_percent"]
    assert scenes[0]["semantic_grounding"]["status"] == "grounded"


def test_source_resolution_never_substitutes_the_first_story_url() -> None:
    assert _source_for_scene(
        {"source_record_key": "record_unknown", "url": "https://wrong.example/article"},
        "story_apple",
        "source_article_scene",
        _source_index(),
    ) == ("", "")


def test_screenshot_target_uses_actual_source_text_instead_of_planner_paraphrase() -> None:
    record = {
        "title": "Apple release",
        "screenshot_target_candidates": [
            "Apple release",
            "The update moves more processing onto the device.",
        ],
    }

    assert _canonical_screenshot_target(
        record,
        "More of the processing now happens on-device.",
    ) == "Apple release"


def test_quote_scene_uses_supporting_source_text_as_capture_target() -> None:
    scene = {
        "render_kind": "quote_or_claim_highlight_scene",
        "payload": {
            "claim_text": "A faster local workflow",
            "supporting_text": "The update moves more processing onto the device.",
        },
    }

    normalized = _scene_with_capture_target(scene)

    assert normalized["payload"]["target_text"] == (
        "The update moves more processing onto the device."
    )


def test_manual_visual_plan_marks_story_ownership_reconciliation_as_substantial() -> None:
    warnings: list[str] = []
    repairs: list[dict] = []

    scenes = _reconcile_scene_sections(
        [
            {
                "scene_id": "scene_001",
                "story_id": "story_wrong",
                "section_type": "story",
                "start_seconds": 2.0,
                "end_seconds": 5.0,
            }
        ],
        [
            {
                "section_id": "section_story_apple",
                "story_id": "story_apple",
                "section_type": "story",
                "start_seconds": 0.0,
                "end_seconds": 8.0,
            }
        ],
        warnings,
        repairs,
    )

    assert scenes[0]["story_id"] == "story_apple"
    assert repairs == [
        {
            "repair_type": "section_story_reconciliation",
            "scene_count": 1,
            "reason": "The submitted scene ownership disagreed with its submitted story-section timing.",
        }
    ]


def test_media_discovery_uses_explicit_queries_unless_config_enables_fallback() -> None:
    scene = {
        "story_title": "Apple AI release",
        "visual_intent": "Show a concrete device.",
        "script_excerpt": "Apple introduced a new device workflow.",
        "payload": {"search_queries": ["Apple device on desk"]},
    }

    assert _queries_for_scene(scene, allow_fallback=False) == ["Apple device on desk"]
    assert len(_queries_for_scene(scene, allow_fallback=True)) > 1


def test_media_text_lists_preserve_phrases_and_recover_from_historical_character_arrays() -> None:
    assert normalize_text_list("high-stakes chess game") == ["high-stakes chess game"]
    assert normalize_text_list(list("high-")) == []

    scene = {
        "payload": {
            "search_queries": ["chess game tech giants"],
            "must_show": list("high-"),
            "must_avoid": list("gener"),
            "beats": [
                {
                    "visual_brief": {
                        "must_show": ["chess analogy"],
                        "on_screen_text": "A high-stakes chess game",
                        "avoid": ["generic AI imagery"],
                    }
                }
            ],
        }
    }

    must_show, must_avoid = _media_constraints_for_scene(scene)
    assert must_show == ["chess analogy"]
    assert must_avoid == ["generic AI imagery"]
    assert _queries_for_scene(scene, allow_fallback=False) == [
        "chess analogy",
        "A high-stakes chess game",
        "chess game tech giants",
    ]
    _normalize_media_scene_payload(scene, allow_fallback=False)
    assert scene["payload"]["must_show"] == ["chess analogy"]
    assert scene["payload"]["must_avoid"] == ["generic AI imagery"]


def test_logo_aliases_require_exact_identity_and_report_text_fallback_truthfully(tmp_path: Path) -> None:
    exact = resolve_logo_asset(
        scene={"payload": {"primary_entity": "Apple"}},
        output_dir=tmp_path,
        favicon_fallback_enabled=False,
        text_fallback_enabled=False,
    )
    ambiguous = resolve_logo_asset(
        scene={"payload": {"primary_entity": "Pineapple Research Collective"}},
        output_dir=tmp_path,
        favicon_fallback_enabled=False,
        text_fallback_enabled=True,
    )
    unavailable_brand = resolve_logo_asset(
        scene={"payload": {"primary_entity": "Amazon"}},
        output_dir=tmp_path,
        favicon_fallback_enabled=False,
        text_fallback_enabled=True,
    )

    assert exact["logo_source"] == "simple_icons"
    assert exact["quality_class"] == "simple_icon"
    assert ambiguous["status"] == "fallback"
    assert ambiguous["quality_class"] == "text_identity_fallback"
    assert simple_icon_export_for("Amazon") is None
    assert unavailable_brand["logo_source"] == "text_fallback"
    assert unavailable_brand["quality_class"] == "text_identity_fallback"
    fallback_svg = Path(ambiguous["fallback_svg_path"]).read_text(encoding="utf-8")
    assert "Pineapple Research Collective" in fallback_svg
    assert "Pineapple Research Collective"[:18] + "</text>" not in fallback_svg


def test_manual_visual_brief_preserves_authored_text() -> None:
    authored = (
        "This complete line is intentionally longer than ninety characters so its meaning "
        "must survive canonical script normalization."
    )

    normalized = _normalize_visual_brief(
        {"on_screen_text": authored},
        {"section_type": "story", "section_id": "section_story_apple"},
        1,
    )

    assert normalized["on_screen_text"] == authored


def test_media_fallback_never_invents_generic_display_copy() -> None:
    scene = {"scene_id": "scene_empty", "script_excerpt": "", "payload": {}}

    assert not _apply_explicit_fallback(scene, "context_image_scene", "No candidate")
    assert "render_kind" not in scene


def test_equivalent_split_image_scenes_share_one_media_request_and_asset() -> None:
    base_scene = {
        "scene_id": "scene_014",
        "story_id": "story_apple",
        "render_kind": "context_image_scene",
        "script_excerpt": "A concrete office moment.",
        "visual_intent": "Show the physical setting.",
        "payload": {
            "search_queries": ["technology office employees"],
            "must_show": ["people working in a technology office"],
            "must_avoid": ["empty office"],
            "shot_style": "wide",
            "beats": [{"beat_id": "beat_03", "relative_end_seconds": 8.0}],
        },
    }
    split_scene = {
        **base_scene,
        "scene_id": "scene_015",
        "payload": {
            **base_scene["payload"],
            "beats": [{"beat_id": "beat_03", "relative_end_seconds": 4.0}],
        },
    }

    request_key = _media_request_key(base_scene, reuse_equivalent_images=True)
    assert request_key == _media_request_key(split_scene, reuse_equivalent_images=True)
    assert _media_request_key(base_scene, reuse_equivalent_images=False) != _media_request_key(
        split_scene,
        reuse_equivalent_images=False,
    )

    reused = _selection_for_reused_scene(
        {
            "scene_id": "scene_014",
            "render_kind": "context_image_scene",
            "asset_path": "/tmp/shared.png",
            "candidate_id": "candidate_1",
        },
        split_scene,
        request_key=request_key,
    )
    assert reused["scene_id"] == "scene_015"
    assert reused["asset_path"] == "/tmp/shared.png"
    assert reused["reused_from_scene_id"] == "scene_014"


def test_media_fallback_budget_supports_current_and_frozen_config_names() -> None:
    current = VisualMediaConfig(output_dir="/tmp/media", max_fallback_requests=5)
    frozen = VisualMediaConfig(output_dir="/tmp/media", max_fallback_scenes=2)

    assert current.fallback_request_budget == 5
    assert frozen.fallback_request_budget == 2


def test_external_media_selection_uses_only_the_semantic_editor_decision() -> None:
    candidate = {
        "score": 0.01,
        "score_breakdown": {"semantic_keyword_match": 0.0},
        "semantic_verification": {"passed": True},
    }

    assert _candidate_passes_selection_gate(candidate)
    assert not _candidate_passes_selection_gate(
        {**candidate, "semantic_verification": {"passed": False}}
    )
    assert not _candidate_passes_selection_gate(
        {"score": 0.99, "score_breakdown": {"semantic_keyword_match": 1.0}}
    )


def test_video_clip_sampling_is_bounded_and_requires_a_semantic_match() -> None:
    assert sample_start_seconds(max_start=20.0, count=5) == [0.0, 5.0, 10.0, 15.0, 20.0]
    assert clip_selection_passes(
        {"visual_match": "strong", "confidence": 0.82, "recommended_action": "use"},
    )
    assert not clip_selection_passes(
        {"visual_match": "strong", "confidence": 0.95, "recommended_action": "reject"},
    )


def test_visual_review_renders_a_real_contact_sheet(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe are required for the visual review smoke")
    video_path = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24:duration=1.2",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
    )
    result = run_visual_review(
        {
            "run": {"run_id": "visual_review_fixture"},
            "config": {
                "output_dir": str(tmp_path / "review"),
                "ffmpeg_path": ffmpeg,
                "ffprobe_path": ffprobe,
                "sample_count": 4,
                "columns": 2,
                "thumbnail_width": 320,
            },
            "input": {
                "video_assembly": {
                    "status": "ok",
                    "data": {
                        "run_id": "visual_review_fixture",
                        "final_video_package": {
                            "final_video_path": str(video_path),
                            "final_video_sha256": file_sha256(video_path),
                        },
                    },
                }
            },
        }
    )

    contact_sheet = Path(result["summary"]["contact_sheet_path"])
    assert result["status"] == "ok"
    assert contact_sheet.exists()
    assert contact_sheet.stat().st_size > 0


def test_visual_review_rejects_a_mismatched_final_video_hash(tmp_path: Path) -> None:
    video_path = tmp_path / "fixture.mp4"
    video_path.write_bytes(b"not-the-declared-video")

    with pytest.raises(ValueError, match="final_video_sha256"):
        run_visual_review(
            {
                "run": {"run_id": "visual_review_fixture"},
                "config": {"output_dir": str(tmp_path / "review")},
                "input": {
                    "video_assembly": {
                        "status": "ok",
                        "data": {
                            "run_id": "visual_review_fixture",
                            "final_video_package": {
                                "final_video_path": str(video_path),
                                "final_video_sha256": "wrong-hash",
                            },
                        },
                    }
                },
            }
        )
