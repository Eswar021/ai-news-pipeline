from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

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
    _bookend_draft_errors,
    _canonical_screenshot_target,
    _close_timeline_gaps,
    _deterministic_scenes_for_range,
    _episode_script_context,
    _adjacent_duplicate_visual_payloads,
    _fallback_candidate_for_slice,
    _metrics_from_draft,
    _normalize_catalog_scene_reference,
    _normalize_montage_scene_references,
    _normalize_story_candidate_scenes,
    _normalize_overlong_story_scene_slots,
    _prepare_story_scene_draft,
    _script_units_for_story_prompt,
    _semantic_grounding_for_scene,
    _source_for_scene,
    _story_coverage_contract,
    _story_draft_errors,
    _story_for_prompt,
    _story_allowed_render_kinds,
    _story_visual_quality_context,
    _catalog_for_story_prompt,
    _catalog_asset_for_scene,
    _story_scene_timing_errors,
    _truth_bound_screenshot_target,
    _stitch_section,
    _timing_continuation_variants,
    _visual_capabilities_for_prompt,
)
from src.pipeline.visuals.asset_resolver.app import (
    _resolve_source_montage,
    _resolve_source_screenshot,
    _scene_with_capture_target,
    _source_capture_cache_key,
)
from src.pipeline.visuals.recipes import recipe_specs_for_prompt
from src.pipeline.visuals.asset_catalog.app import (
    _MetadataParser,
    _apply_source_page_fetch_status,
    _download_source_linked_video_candidate,
    _bind_brief_to_assets,
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
from src.pipeline.visuals.generators.source_screenshot.web_capture import _capture_block_reason
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


def test_asset_catalog_parser_keeps_image_and_page_context_separate() -> None:
    parser = _MetadataParser()
    parser.feed(
        "<html><body><h2>Factory safety</h2><p>Robots inspect hazardous zones.</p>"
        "<figure><img src='/robot.jpg' alt='Robot arm beside a welding cell'>"
        "<figcaption>The inspection robot at the pilot factory.</figcaption></figure>"
        "<h2>Employee wellness</h2><img src='/salad.jpg'></body></html>"
    )

    robot, salad = parser.image_candidates
    assert robot["figure_caption"] == "The inspection robot at the pilot factory."
    assert robot["page_section_heading"] == "Factory safety"
    assert "Robots inspect hazardous zones" in robot["nearby_text"]
    assert salad["figure_caption"] == ""
    assert salad["page_section_heading"] == "Employee wellness"
    assert "Factory safety" not in salad["page_section_heading"]


def test_asset_catalog_marks_failed_source_page_fetch_unavailable() -> None:
    assets = [
        {
            "asset_id": "asset_source_page_openai",
            "asset_type": "source_page",
            "status": "available",
            "review_status": "trusted_source",
            "source_record_key": "record_openai",
        }
    ]

    resolved = _apply_source_page_fetch_status(
        assets,
        page_results=[
            {
                "record_key": "record_openai",
                "page_fetch_status": "failed",
                "page_fetch_error": "HTTPError: 403 Client Error",
            }
        ],
        failure_policy="mark_unavailable",
    )

    assert resolved[0]["status"] == "unavailable"
    assert resolved[0]["review_status"] == "source_page_unavailable"
    assert resolved[0]["page_fetch_status"] == "failed"
    assert "403" in resolved[0]["availability_reason"]


def test_source_capture_detects_challenge_pages_as_unavailable() -> None:
    assert _capture_block_reason(
        title="Just a moment...",
        body_text="Verify you are human",
        http_status=403,
        challenge_frame_count=1,
    ) == "anti-bot challenge frame detected"
    assert (
        _capture_block_reason(
            title="A normal article",
            body_text="The article body is visible.",
            http_status=200,
            challenge_frame_count=0,
        )
        == ""
    )
    assert (
        _capture_block_reason(
            title="A normal article",
            body_text="Visible article content. " * 40,
            http_status=200,
            challenge_frame_count=1,
        )
        == ""
    )


def test_source_capture_cache_key_reuses_only_identical_capture_requests() -> None:
    scene = {
        "payload": {
            "url": "https://openai.com/index/a-scorecard-for-the-ai-age/",
            "target_text": "A scorecard for the AI age",
        }
    }

    first = _source_capture_cache_key(
        scene,
        capture_mode="target_text_focus",
        focus_zoom=1.3,
        highlight_target=True,
    )
    duplicate = _source_capture_cache_key(
        {
            "payload": {
                "url": "https://openai.com/index/a-scorecard-for-the-ai-age",
                "target_text": "A SCORECARD FOR THE AI AGE",
            }
        },
        capture_mode="target_text_focus",
        focus_zoom=1.3,
        highlight_target=True,
    )
    different_target = _source_capture_cache_key(
        {"payload": {**scene["payload"], "target_text": "A different claim"}},
        capture_mode="target_text_focus",
        focus_zoom=1.3,
        highlight_target=True,
    )

    assert first == duplicate
    assert first != different_target


def test_source_resolver_reuses_identical_successful_capture(monkeypatch, tmp_path: Path) -> None:
    capture_calls: list[str] = []

    def fake_capture_source_viewport(**kwargs):
        capture_calls.append(kwargs["scene"]["scene_id"])
        return {
            "ok": True,
            "url": kwargs["scene"]["payload"]["url"],
            "target_found": True,
            "matched_text": kwargs["scene"]["payload"]["target_text"],
            "screenshot_bytes": b"identical-png-bytes",
        }

    monkeypatch.setattr(
        "src.pipeline.visuals.asset_resolver.app.capture_source_viewport",
        fake_capture_source_viewport,
    )
    source_config = SimpleNamespace(
        capture_mode="target_text_focus",
        focus_zoom=1.3,
        highlight_target=True,
        reuse_identical_captures=True,
        save_raw_capture_debug=False,
        save_full_page_debug=False,
        target_miss_policy="failed",
    )
    request = SimpleNamespace(
        config=SimpleNamespace(
            browser=SimpleNamespace(timeout_ms=10_000, post_load_wait_ms=0),
            source_screenshots=source_config,
        )
    )
    base_scene = {
        "scene_order": 1,
        "story_id": "story_openai",
        "render_kind": "source_article_scene",
        "payload": {
            "url": "https://openai.com/index/a-scorecard-for-the-ai-age",
            "target_text": "A scorecard for the AI age",
        },
    }
    cache: dict = {}
    (tmp_path / "screenshots").mkdir(parents=True)

    first = _resolve_source_screenshot(
        context=object(),
        scene={**base_scene, "scene_id": "scene_020"},
        request=request,
        screenshots_dir=tmp_path / "screenshots",
        raw_capture_dir=tmp_path / "raw",
        full_page_dir=tmp_path / "full",
        capture_cache=cache,
    )
    second = _resolve_source_screenshot(
        context=object(),
        scene={**base_scene, "scene_id": "scene_024"},
        request=request,
        screenshots_dir=tmp_path / "screenshots",
        raw_capture_dir=tmp_path / "raw",
        full_page_dir=tmp_path / "full",
        capture_cache=cache,
    )

    assert capture_calls == ["scene_020"]
    assert first["capture"]["cache_hit"] is False
    assert second["capture"]["cache_hit"] is True
    assert second["capture"]["cache_source_scene_id"] == "scene_020"
    assert Path(first["asset_path"]).read_bytes() == b"identical-png-bytes"
    assert Path(second["asset_path"]).read_bytes() == b"identical-png-bytes"


def test_source_proof_montage_binds_only_story_owned_catalog_pages() -> None:
    catalog = {
        "assets_by_id": {
            "page_a": {
                "asset_id": "page_a",
                "asset_type": "source_page",
                "status": "available",
                "story_id": "story_a",
                "source_record_key": "record_a",
                "source_url": "https://example.com/a",
                "title": "Primary release",
                "source_name": "Example",
                "screenshot_target_candidates": ["Exact release detail"],
            },
            "page_b": {
                "asset_id": "page_b",
                "asset_type": "source_page",
                "status": "available",
                "story_id": "story_a",
                "source_record_key": "record_b",
                "source_url": "https://example.com/b",
                "title": "Independent report",
                "source_name": "Reporter",
                "screenshot_target_candidates": ["Independent confirmation"],
            },
        }
    }
    scene = {
        "render_kind": "document_stack_scene",
        "recipe_id": "source_proof_montage",
        "documents": [{"asset_id": "page_a"}, {"asset_id": "page_b"}],
        "evidence_record_keys": [],
        "payload_json": "{}",
    }

    normalized, errors = _normalize_montage_scene_references(
        scene,
        story_id="story_a",
        catalog_index=catalog,
    )

    assert errors == []
    assert normalized["evidence_record_keys"] == ["record_a", "record_b"]
    assert normalized["documents"][0]["url"] == "https://example.com/a"
    assert normalized["documents"][1]["target_text"] == "Independent confirmation"


def test_source_proof_montage_payload_requires_two_canonical_sources() -> None:
    errors = validate_scene_payload(
        "document_stack_scene",
        {
            "recipe_id": "source_proof_montage",
            "headline": "Two sources, one signal",
            "documents": [
                {
                    "title": "Release",
                    "source": "Example",
                    "asset_id": "page_a",
                    "source_record_key": "record_a",
                    "url": "https://example.com/a",
                }
            ],
            "focus_document_label": "Release",
        },
    )

    assert "source_proof_montage requires 2-3 source documents" in errors


def test_source_proof_montage_recipe_is_advertised_for_both_renderers() -> None:
    recipes = recipe_specs_for_prompt(
        "document_stack_scene",
        allowed_recipe_ids=["source_proof_montage"],
        required_backends=["remotion", "hyperframes"],
    )

    assert [recipe["recipe_id"] for recipe in recipes] == ["source_proof_montage"]


def test_source_proof_montage_resolves_each_declared_source(monkeypatch, tmp_path: Path) -> None:
    def fake_resolve_source_screenshot(**kwargs):
        scene = kwargs["scene"]
        index = scene["scene_id"].rsplit("_", 1)[-1]
        path = tmp_path / f"capture_{index}.png"
        path.write_bytes(b"png")
        return {
            "status": "resolved",
            "asset_path": str(path),
            "capture": {"domain": f"source-{index}.example"},
            "error": "",
        }

    monkeypatch.setattr(
        "src.pipeline.visuals.asset_resolver.app._resolve_source_screenshot",
        fake_resolve_source_screenshot,
    )
    scene = {
        "scene_id": "scene_010",
        "scene_order": 10,
        "story_id": "story_a",
        "render_kind": "document_stack_scene",
        "payload": {
            "recipe_id": "source_proof_montage",
            "documents": [
                {"asset_id": "page_a", "source_record_key": "record_a", "url": "https://example.com/a", "title": "A", "source": "Example"},
                {"asset_id": "page_b", "source_record_key": "record_b", "url": "https://example.com/b", "title": "B", "source": "Reporter"},
            ],
        },
    }

    resolved = _resolve_source_montage(
        context=object(),
        scene=scene,
        request=SimpleNamespace(),
        screenshots_dir=tmp_path,
        raw_capture_dir=tmp_path / "raw",
        full_page_dir=tmp_path / "full",
        capture_cache={},
    )

    assert resolved["status"] == "resolved"
    assert resolved["asset_type"] == "source_montage"
    assert [item["asset_id"] for item in resolved["assets"]] == ["page_a", "page_b"]


def test_story_capabilities_exclude_source_scenes_without_available_source_page() -> None:
    config = {
        "scene_policy": {
            "allowed_render_kinds": [
                "source_article_scene",
                "logo_reveal_scene",
                "simple_explainer_scene",
            ]
        },
        "asset_availability_policy": {
            "catalog_asset_required_render_kinds": ["source_article_scene"]
        },
    }
    story_catalog = {
        "available_assets": [
            {
                "asset_id": "asset_logo_openai",
                "asset_type": "logo",
                "status": "available",
                "review_status": "trusted_identity",
            },
        ]
    }

    assert _story_allowed_render_kinds(config, story_catalog) == [
        "logo_reveal_scene",
        "simple_explainer_scene",
    ]


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


def test_asset_catalog_parser_keeps_source_link_context_for_video_candidates() -> None:
    parser = _MetadataParser()
    parser.feed(
        '<html><body><h2>Warehouse robot demo</h2>'
        '<p>Watch the machine pick and place a real package.</p>'
        '<a href="https://www.youtube.com/watch?v=robot">See the robot in action</a>'
        '</body></html>'
    )

    candidate = parser.linked_video_candidates[0]
    assert candidate["link_text"] == "See the robot in action"
    assert candidate["page_section_heading"] == "Warehouse robot demo"
    assert "pick and place" in candidate["nearby_text"]


def test_asset_briefs_expose_structural_candidates_without_claiming_a_semantic_match() -> None:
    bound = _bind_brief_to_assets(
        {
            "asset_request_id": "request_demo",
            "beat_ids": ["beat_demo"],
            "requested_asset_types": ["source_image"],
            "preferred_record_keys": ["record_demo"],
        },
        [
            {
                "asset_id": "asset_image_demo",
                "asset_type": "source_image",
                "source_record_key": "record_demo",
            }
        ],
    )

    assert bound["candidate_asset_ids"] == ["asset_image_demo"]
    assert bound["resolution_status"] == "candidate_assets_available"
    assert bound["semantic_selection_status"] == "planner_review_required"
    assert "matched_asset_ids" not in bound


def test_story_prompt_joins_beat_candidates_to_rich_asset_descriptors() -> None:
    prompt_catalog = _catalog_for_story_prompt(
        {
            "story_catalogs": {
                "story_demo": {
                    "asset_briefs": [
                        {
                            "asset_request_id": "request_demo",
                            "beat_ids": ["beat_demo"],
                            "purpose": "Show the robot moving a package.",
                            "candidate_asset_ids": ["asset_video_demo"],
                        }
                    ]
                }
            },
            "assets_by_story": {
                "story_demo": [
                    {
                        "asset_id": "asset_video_demo",
                        "story_id": "story_demo",
                        "asset_type": "source_video",
                        "status": "available",
                        "title": "Robot demo",
                        "video_context": {"link_text": "Watch package handling"},
                        "video_moments": [
                            {
                                "video_moment_id": "moment_pick",
                                "title": "Robot picks a package",
                                "start_seconds": 12.0,
                                "end_seconds": 20.0,
                            }
                        ],
                    }
                ]
            },
        },
        "story_demo",
    )

    option = prompt_catalog["beat_asset_options"][0]
    assert option["semantic_selection_status"] == "planner_review_required"
    assert option["candidate_assets"][0]["video_moments"][0]["video_moment_id"] == "moment_pick"


def test_planner_accepts_only_video_moments_owned_by_the_selected_asset() -> None:
    asset = {
        "asset_id": "asset_video_demo",
        "story_id": "story_demo",
        "asset_type": "source_video",
        "status": "available",
        "video_moments": [{"video_moment_id": "moment_pick", "title": "Package pick"}],
    }
    catalog = {"assets_by_id": {"asset_video_demo": asset}}

    selected, errors = _catalog_asset_for_scene(
        {"asset_id": "asset_video_demo", "video_moment_id": "moment_pick"},
        story_id="story_demo",
        render_kind="broll_video_scene",
        catalog_index=catalog,
    )
    assert selected == asset
    assert errors == []

    selected, errors = _catalog_asset_for_scene(
        {"asset_id": "asset_video_demo", "video_moment_id": "moment_invented"},
        story_id="story_demo",
        render_kind="broll_video_scene",
        catalog_index=catalog,
    )
    assert selected is None
    assert "has no video moment" in errors[0]


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
                        "chapters": [
                            {"title": "Overview", "start_time": 0, "end_time": 18},
                            {"title": "Product walkthrough", "start_time": 18, "end_time": 70},
                        ],
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
            "link_text": "Watch the product walkthrough",
            "page_section_heading": "How it works",
            "nearby_text": "The linked demo shows the workflow step by step.",
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
            "max_chapter_moments": 12,
        },
    )

    assert asset["asset_type"] == "source_video"
    assert asset["provider"] == "youtube"
    assert asset["provenance_trust"]["status"] == "trusted"
    assert asset["narration_suitability"]["status"] == "unreviewed"
    assert asset["link_text"] == "Watch the product walkthrough"
    assert asset["video_moments"][1]["title"] == "Product walkthrough"
    assert asset["video_moments"][1]["start_seconds"] == 18.0
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
        policy={"allowed_render_kinds": ["editorial_text_scene", "source_article_scene"]},
    )

    assert candidate["render_kind"] == "editorial_text_scene"
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


def test_story_capabilities_hide_catalog_kinds_without_compatible_assets() -> None:
    config = {
        "scene_policy": {
            "allowed_render_kinds": [
                "source_article_scene",
                "context_image_scene",
                "broll_video_scene",
                "editorial_text_scene",
                "story_transition_scene",
            ]
        },
        "asset_availability_policy": {
            "catalog_asset_required_render_kinds": [
                "context_image_scene",
                "broll_video_scene",
            ]
        },
    }
    story_catalog = {
        "available_assets": [
            {
                "asset_id": "asset_source_image_1",
                "asset_type": "source_image",
                "review_status": "accepted",
            }
        ]
    }

    allowed = _story_allowed_render_kinds(config, story_catalog)

    assert allowed == [
        "source_article_scene",
        "context_image_scene",
        "editorial_text_scene",
    ]


def test_story_capabilities_keep_broll_when_source_video_exists() -> None:
    config = {
        "scene_policy": {
            "allowed_render_kinds": ["broll_video_scene", "editorial_text_scene"]
        },
        "asset_availability_policy": {
            "catalog_asset_required_render_kinds": ["broll_video_scene"]
        },
    }
    story_catalog = {
        "available_assets": [
            {
                "asset_id": "asset_source_video_1",
                "asset_type": "source_video",
                "review_status": "accepted",
            }
        ]
    }

    assert _story_allowed_render_kinds(config, story_catalog) == [
        "broll_video_scene",
        "editorial_text_scene",
    ]


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


def test_visual_editor_reviews_text_when_the_same_beat_has_catalog_candidates() -> None:
    quality = _story_visual_quality_context(
        story_id="story_apple",
        scenes=[
            {
                "scene_id": "scene_002",
                "render_kind": "editorial_text_scene",
                "payload": {"beats": [{"beat_id": "beat_product"}]},
            }
        ],
        asset_catalog_index={
            "assets_by_story": {
                "story_apple": [{"asset_id": "asset_product", "status": "available"}]
            },
            "story_catalogs": {
                "story_apple": {
                    "asset_briefs": [
                        {
                            "beat_ids": ["beat_product"],
                            "candidate_asset_ids": ["asset_product"],
                        }
                    ]
                }
            },
        },
        config={
            "scene_policy": {"max_consecutive_same_kind": 2},
            "visual_mix_policy": {
                "target_max_text_like_scenes_per_story": 2,
                "review_text_scenes_with_candidate_media": True,
            },
        },
        current_errors=[],
    )

    assert quality["review_recommended"] is True
    assert quality["review_reasons"] == ["text_scene_has_unreviewed_catalog_candidates"]
    assert quality["text_scenes_with_candidate_media"][0]["candidate_asset_ids"] == [
        "asset_product"
    ]


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
            "color=c=0x243447:s=1280x720:d=4.0",
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
        "payload": {
            "asset_id": "asset_source_video_apple",
            "video_moment_id": "moment_product",
            "clip_selection_reason": "The chapter shows the product action named in narration.",
        },
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
                "video_moments": [
                    {
                        "video_moment_id": "moment_product",
                        "title": "Product action",
                        "start_seconds": 1.0,
                        "end_seconds": 3.5,
                    }
                ],
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
    assert selection["clip_start_seconds"] == pytest.approx(1.0)
    assert selection["video_moment_id"] == "moment_product"
    assert selection["video_moment_title"] == "Product action"
    assert selection["selection_basis"] == "planner_selected_exact_story_catalog_video_moment"
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
                "allowed_render_kinds": ["editorial_text_scene"],
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


def test_unknown_context_media_asset_id_is_preserved_for_explicit_validation() -> None:
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

    assert normalized["asset_id"] == "asset_source_image_example"
    assert normalized["search_queries"] == ["Built Technologies document workflow"]
    assert repairs == []


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
                            "recipe_id": "source_proof_scan",
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
                            "recipe_id": "editorial_hook",
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


def test_catalog_backed_source_scene_requires_exact_asset_id() -> None:
    section = {
        "start_unit_order": 1,
        "end_unit_order": 1,
        "script_units": [
            {
                "order": 1,
                "start_seconds": 0.0,
                "end_seconds": 6.0,
                "duration_seconds": 6.0,
                "text": "The selected source reports an 80 percent increase.",
            }
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
                "script_excerpt": "The selected source reports an 80 percent increase.",
                "visual_intent": "Show the selected source.",
                "evidence_record_keys": ["record_apple"],
                "evidence_truth_ids": ["truth_apple_80_percent"],
                "evidence_text": "The selected record explicitly reports an 80 percent increase.",
                "grounding_basis": "selected_record",
                "payload_json": json.dumps(
                    {
                        "url": "https://apple.example/release",
                        "source_record_key": "record_apple",
                        "target_text": "Apple release",
                        "highlight_phrases": ["80 percent"],
                        "crop_strategy": "target_text_focus",
                        "overlay_headline": "80 percent increase",
                        "motion_style": "highlight_scan",
                    }
                ),
                "reason": "Use the source as proof.",
            }
        ],
    }
    catalog_asset = {
        "asset_id": "asset_source_page_apple",
        "asset_type": "source_page",
        "story_id": "story_apple",
        "status": "available",
        "source_record_key": "record_apple",
        "source_url": "https://apple.example/release",
    }
    errors = _story_draft_errors(
        draft,
        story_id="story_apple",
        section=section,
        source_index=_source_index(),
        asset_catalog_index={
            "assets_by_id": {"asset_source_page_apple": catalog_asset},
            "assets_by_story": {"story_apple": [catalog_asset]},
        },
        config={
            "require_real_anchor_per_story": True,
            "real_anchor_failure_mode": "warn",
            "asset_availability_policy": {
                "catalog_asset_required_render_kinds": ["source_article_scene"]
            },
            "scene_policy": {
                "allowed_render_kinds": ["source_article_scene"],
                "max_scene_seconds": 14.0,
                "hard_max_scene_seconds": 16.0,
                "hard_cap_tolerance_seconds": 0.25,
                "unit_assignment_mode": "one_scene_per_script_unit",
                "duplicate_subscene_policy": "continue",
            },
        },
    )

    assert any("requires an exact available story-owned asset_id" in error for error in errors)


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
        "render_kind": "editorial_text_scene",
        "payload_json": json.dumps({"headline": "First idea", "composition": "editorial_center"}),
    }
    duplicate = {**first, "order": 2}
    distinct = {
        **first,
        "order": 2,
        "render_kind": "simple_explainer_scene",
        "payload_json": json.dumps(
            {
                "headline": "How it works",
                "items": [{"label": "A"}, {"label": "B"}],
                "orientation": "horizontal",
            }
        ),
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


def test_bookend_validation_accepts_section_order_and_expands_long_units() -> None:
    intro = {
        "section_type": "intro",
        "start_unit_order": 1,
        "end_unit_order": 1,
        "script_units": [
            {
                "order": 1,
                "start_seconds": 0.0,
                "end_seconds": 20.0,
                "duration_seconds": 20.0,
            }
        ],
    }
    closing = {
        "section_type": "closing",
        "start_unit_order": 9,
        "end_unit_order": 9,
        "script_units": [
            {
                "order": 9,
                "start_seconds": 100.0,
                "end_seconds": 118.0,
                "duration_seconds": 18.0,
            }
        ],
    }
    draft = {
        "sections": [
            {
                "section_type": "intro",
                "scene_timeline": [
                    {
                        "order": 1,
                        "start_unit_order": 1,
                        "end_unit_order": 1,
                        "render_kind": "editorial_text_scene",
                        "visual_intent": "Open with the authored episode premise.",
                        "payload_json": json.dumps(
                            {
                                "headline": "The week's AI shift",
                                "accent_words": ["AI"],
                                "composition": "editorial_center",
                                "motion_style": "editorial_reveal",
                            }
                        ),
                    }
                ],
            },
            {
                "section_type": "closing",
                "scene_timeline": [
                    {
                        "order": 1,
                        "start_unit_order": 9,
                        "end_unit_order": 9,
                        "render_kind": "editorial_text_scene",
                        "visual_intent": "Land the authored closing takeaway.",
                        "payload_json": json.dumps(
                            {
                                "headline": "Watch what ships next",
                                "accent_words": ["next"],
                                "composition": "editorial_center",
                                "motion_style": "editorial_reveal",
                            }
                        ),
                    }
                ],
            },
        ]
    }
    config = {
        "scene_policy": {
            "allowed_render_kinds": ["editorial_text_scene"],
            "unit_assignment_mode": "one_scene_per_script_unit",
            "max_scene_seconds": 14.0,
            "hard_max_scene_seconds": 16.0,
            "hard_cap_tolerance_seconds": 0.0,
            "duplicate_subscene_policy": "continue",
        },
        "recipe_policy": {"enabled": False},
        "asset_availability_policy": {"catalog_asset_required_render_kinds": []},
    }

    errors = _bookend_draft_errors(
        draft,
        sections=[closing, intro],
        source_index={
            "records_by_key": {},
            "record_keys_by_story": {},
            "story_identity_by_id": {},
            "truth_items_by_story": {},
            "truth_items_by_id": {},
        },
        asset_catalog_index={"assets_by_id": {}, "assets_by_story": {}},
        config=config,
    )

    assert errors == []
    assert [len(section["scene_timeline"]) for section in draft["sections"]] == [2, 2]


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
        "render_kind": "simple_explainer_scene",
        "payload_json": json.dumps(
            {
                "headline": "Funding",
                "items": [{"label": "Before"}, {"label": "After"}],
                "orientation": "horizontal",
            }
        ),
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
            "render_kind": "editorial_text_scene",
            "script_excerpt": "First, establish the problem.",
            "visual_intent": "Show the problem.",
            "payload": {
                "headline": "THE PROBLEM",
                "accent_words": ["PROBLEM"],
                "composition": "editorial_center",
                "motion_style": "word_reveal",
            },
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
        policy={"max_scene_seconds": 14.0, "allowed_render_kinds": ["editorial_text_scene", "logo_reveal_scene"]},
    )

    assert [(scene["start_seconds"], scene["end_seconds"]) for scene in scenes] == [(0.0, 10.0), (10.0, 20.0)]
    assert [scene["render_kind"] for scene in scenes] == ["editorial_text_scene", "logo_reveal_scene"]
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
        {"scene_id": "scene_001", "story_id": "story_apple", "render_kind": "editorial_text_scene", "payload": {"headline": "SAME"}},
        {"scene_id": "scene_002", "story_id": "story_apple", "render_kind": "editorial_text_scene", "payload": {"headline": "SAME"}},
    ]

    assert _adjacent_duplicate_visual_payloads(scenes) == [
        {
            "first_scene_id": "scene_001",
            "second_scene_id": "scene_002",
            "render_kind": "editorial_text_scene",
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


def test_catalog_asset_type_does_not_rewrite_the_selected_render_kind() -> None:
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

    assert scene["render_kind"] == "context_image_scene"
    assert scene["asset_id"] == "asset_logo_apple"
    assert "primary_entity" not in scene
    assert "contract_repairs" not in scene


def test_explainer_scene_is_not_semantically_rejected_by_literal_matching_code() -> None:
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
            "render_kind": "simple_explainer_scene",
            "script_excerpt": "Performance rose by 80 percent.",
            "visual_intent": "Show the reported change.",
            "evidence_record_keys": ["record_apple"],
            "evidence_truth_ids": ["truth_apple_45_minutes"],
            "evidence_text": "A different beat mentions 45 minutes.",
            "grounding_basis": "selected_record",
            "payload_json": json.dumps(
                {
                    "headline": "Performance",
                    "items": [
                        {"label": "Setup", "detail": "45 minutes"},
                        {"label": "Result", "detail": "Performance changed"},
                    ],
                    "orientation": "horizontal",
                    "motion_style": "sequential_focus",
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
                "allowed_render_kinds": ["simple_explainer_scene", "source_article_scene"]
            }
        },
    )

    assert scene["render_kind"] == "simple_explainer_scene"
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
    ) == ["unsupported render_kind: bar_chart_scene"]
    assert "payload.items requires at least 2 object item(s)" in validate_scene_payload(
        "simple_explainer_scene",
        {
            "headline": "Request path",
            "items": [{"label": "Client"}],
            "orientation": "horizontal",
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
    ) == ["unsupported render_kind: data_counter_scene"]


def test_visual_payload_validation_checks_nested_relationships() -> None:
    explainer_errors = validate_scene_payload(
        "simple_explainer_scene",
        {
            "headline": "Platform relationships",
            "items": [
                {"label": "OpenAI"},
                {"label": "Developers"},
            ],
            "focus_item_label": "Missing",
            "orientation": "horizontal",
        },
    )
    transform_errors = validate_scene_payload(
        "interface_transform_scene",
        {
            "headline": "Workflow change",
            "before": {"label": "Before", "items": ["Manual"]},
            "after": {"label": "After", "items": ["Review", "Publish"]},
            "transformation_label": "Assisted workflow",
        },
    )

    assert "payload.focus_item_label must match an item label" in explainer_errors
    assert "payload.before.items requires at least 2 non-empty text item(s)" in transform_errors


def test_semantic_graphic_accepts_selected_record_or_canonical_script_beat_grounding() -> None:
    invalid = _semantic_grounding_for_scene(
        draft={"evidence_record_keys": [], "evidence_text": ""},
        render_kind="simple_explainer_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={
            "headline": "Reported performance increase",
            "items": [{"label": "Before"}, {"label": "After"}],
            "orientation": "horizontal",
        },
        source_index=_source_index(),
    )
    valid = _semantic_grounding_for_scene(
        draft={
            "evidence_record_keys": ["record_apple"],
            "evidence_truth_ids": ["truth_apple_80_percent"],
            "evidence_text": "The selected record explicitly reports an 80 percent increase.",
            "grounding_basis": "selected_record",
        },
        render_kind="simple_explainer_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={
            "headline": "Reported performance increase",
            "items": [{"label": "Before"}, {"label": "After"}],
            "orientation": "horizontal",
        },
        source_index=_source_index(),
    )
    script_beat = _semantic_grounding_for_scene(
        draft={
            "evidence_record_keys": [],
            "evidence_text": "The assigned narration contrasts privacy with data retention.",
            "grounding_basis": "script_beat",
        },
        render_kind="simple_explainer_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={
            "headline": "Privacy or retention",
            "items": [{"label": "Privacy"}, {"label": "Data retention"}],
            "orientation": "horizontal",
        },
        source_index=_source_index(),
    )
    missing_selected_record = _semantic_grounding_for_scene(
        draft={
            "evidence_record_keys": [],
            "evidence_text": "Claims to use a selected record without naming one.",
            "grounding_basis": "selected_record",
        },
        render_kind="simple_explainer_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={
            "headline": "Product comparison",
            "items": [{"label": "Product A"}, {"label": "Product B"}],
            "orientation": "horizontal",
        },
        source_index=_source_index(),
    )

    assert invalid["status"] == "invalid"
    assert valid["status"] == "grounded"
    assert script_beat["status"] == "grounded"
    assert missing_selected_record["status"] == "invalid"


def test_explainer_context_is_owned_by_llm_and_structural_provenance() -> None:
    result = _semantic_grounding_for_scene(
        draft={
            "evidence_record_keys": ["record_apple"],
            "evidence_truth_ids": ["truth_apple_80_percent"],
            "evidence_text": "The selected record reports an 80 percent increase.",
            "grounding_basis": "selected_record",
        },
        render_kind="simple_explainer_scene",
        story_id="story_apple",
        source_record_key="",
        url="",
        payload={
            "headline": "Reported performance increase",
            "items": [
                {"label": "Before", "detail": "Baseline"},
                {"label": "After", "detail": "Reported increase"},
            ],
            "orientation": "horizontal",
        },
        source_index=_source_index(),
    )

    assert result["status"] == "grounded"
    assert result["errors"] == []


def test_manual_visual_plan_preserves_structural_provenance_for_active_explainer() -> None:
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
                "render_kind": "simple_explainer_scene",
                "script_excerpt": "The report says performance rose by 80 percent.",
                "visual_intent": "Show the exact reported gain.",
                "evidence_record_keys": ["record_apple"],
                "evidence_truth_ids": ["truth_apple_80_percent"],
                "evidence_text": "The assigned metric truth reports 80 percent.",
                "grounding_basis": "selected_record",
                "payload": {
                    "headline": "Reported performance gain",
                    "items": [
                        {"label": "Before", "detail": "Baseline"},
                        {"label": "After", "detail": "Reported gain"},
                    ],
                    "orientation": "horizontal",
                    "motion_style": "sequential_focus",
                },
                "covered_unit_orders": [1],
            }
        ],
        allowed_render_kinds={"simple_explainer_scene"},
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
    assert Path(exact["logo_path"]).is_file()
    assert "<svg" in Path(exact["logo_path"]).read_text(encoding="utf-8")
    assert ambiguous["status"] == "fallback"
    assert ambiguous["quality_class"] == "text_identity_fallback"
    assert simple_icon_export_for("Amazon") is None
    assert unavailable_brand["logo_source"] == "text_fallback"
    assert unavailable_brand["quality_class"] == "text_identity_fallback"
    fallback_svg = Path(ambiguous["fallback_svg_path"]).read_text(encoding="utf-8")
    assert "Pineapple Research Collective" in fallback_svg
    assert "Pineapple Research Collective"[:18] + "</text>" not in fallback_svg
    assert "#171611" in fallback_svg
    assert "#b64b2d" in fallback_svg
    assert "rect" not in fallback_svg


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


def test_visual_review_builds_story_by_story_scene_report(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe are required for the visual review smoke")
    video_path = tmp_path / "fixture_story_report.mp4"
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
            "run": {"run_id": "visual_story_review_fixture"},
            "config": {
                "output_dir": str(tmp_path / "story_review"),
                "ffmpeg_path": ffmpeg,
                "ffprobe_path": ffprobe,
                "sample_count": 4,
                "columns": 2,
                "thumbnail_width": 320,
                "story_report": {
                    "enabled": True,
                    "worker_count": 2,
                    "thumbnail_width": 360,
                    "jpeg_quality": 85,
                },
            },
            "input": {
                "video_assembly": {
                    "status": "ok",
                    "data": {
                        "run_id": "visual_story_review_fixture",
                        "final_video_package": {
                            "final_video_path": str(video_path),
                            "final_video_sha256": file_sha256(video_path),
                        },
                    },
                },
                "visual_scene_planning": {
                    "status": "ok",
                    "data": {
                        "run_id": "visual_story_review_fixture",
                        "visual_scene_plan": {
                            "scene_timeline": [
                                {
                                    "scene_id": "scene_001",
                                    "section_type": "story",
                                    "story_id": "story_robot",
                                    "story_title": "Robots enter the warehouse",
                                    "start_seconds": 0.0,
                                    "end_seconds": 0.6,
                                    "duration_seconds": 0.6,
                                    "render_kind": "broll_video_scene",
                                    "script_excerpt": "The robot picks a package from the line.",
                                    "visual_intent": "Show the real package-picking action.",
                                    "reason": "The selected chapter directly depicts the action.",
                                    "payload": {
                                        "recipe_id": "annotated_video_focus",
                                        "asset_id": "asset_robot_video",
                                        "video_moment_id": "moment_pick",
                                    },
                                },
                                {
                                    "scene_id": "scene_002",
                                    "section_type": "story",
                                    "story_id": "story_robot",
                                    "story_title": "Robots enter the warehouse",
                                    "start_seconds": 0.6,
                                    "end_seconds": 1.2,
                                    "duration_seconds": 0.6,
                                    "render_kind": "source_article_scene",
                                    "script_excerpt": "The pilot is still limited in scope.",
                                    "visual_intent": "Show the source qualification.",
                                    "reason": "The article text carries the caveat.",
                                    "payload": {"recipe_id": "source_proof_scan"},
                                },
                            ],
                            "asset_catalog": {
                                "assets": [
                                    {
                                        "asset_id": "asset_robot_video",
                                        "asset_type": "source_video",
                                        "title": "Warehouse robot demo",
                                        "source_url": "https://example.com/robot",
                                        "video_moments": [
                                            {
                                                "video_moment_id": "moment_pick",
                                                "title": "Package pick",
                                            }
                                        ],
                                    }
                                ]
                            },
                        },
                    },
                },
            },
        }
    )

    report_path = Path(result["summary"]["story_review_report_path"])
    manifest_path = Path(result["summary"]["story_review_manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert report_path.exists()
    assert result["summary"]["story_review_scene_count"] == 2
    assert manifest["groups"][0]["story_title"] == "Robots enter the warehouse"
    assert manifest["groups"][0]["scenes"][0]["video_moment_title"] == "Package pick"
    html = report_path.read_text(encoding="utf-8")
    assert "The robot picks a package from the line." in html
    assert "Warehouse robot demo" in html


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
