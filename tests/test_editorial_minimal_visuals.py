from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from src.pipeline.config import ConfigRepository
from pydantic import ValidationError

from src.pipeline.handoffs.chatgpt_exporter.app import _prepare_artifact
from src.pipeline.visuals.asset_resolver.app import NO_ASSET_RENDER_KINDS
from src.pipeline.visuals.payload_validation import validate_scene_payload
from src.pipeline.visuals.planner.app import (
    _normalize_provider_scene_fields,
    _resolved_llm_configs,
    _story_visual_edit_output_model,
    _story_visual_plan_output_model,
    _visual_capabilities_for_prompt,
)
from src.pipeline.visuals.planner.contract import VisualPlannerConfig
from src.pipeline.visuals.planner.llm_client import make_llm


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _planner_config() -> dict:
    repository = ConfigRepository(PROJECT_ROOT / "src/pipeline/config/workbench.yaml")
    return deepcopy(repository.module("daily_48h_all_sources", "visuals", "planner").value)


def test_production_profile_exposes_renderable_editorial_vocabulary() -> None:
    config = VisualPlannerConfig.model_validate(_planner_config()).model_dump(mode="json")

    assert config["style"]["style_id"] == "editorial_minimal"
    assert config["scene_policy"]["allowed_render_kinds"] == [
        "source_article_scene",
        "context_image_scene",
        "broll_video_scene",
        "logo_reveal_scene",
        "editorial_text_scene",
        "simple_explainer_scene",
        "story_transition_scene",
        "quote_or_claim_highlight_scene",
        "data_counter_scene",
        "benchmark_delta_scene",
        "ecosystem_map_scene",
        "architecture_flow_scene",
        "process_zoom_scene",
        "browser_walkthrough_scene",
        "capability_matrix_scene",
        "document_stack_scene",
        "interface_transform_scene",
    ]


def test_production_visual_planner_uses_kimi_for_story_creative_roles() -> None:
    config = VisualPlannerConfig.model_validate(_planner_config()).model_dump(mode="json")
    routes = _resolved_llm_configs(config)

    assert routes["episode_director"]["provider"] == "openai"
    assert routes["episode_director"]["model"] == "gpt-4o-mini"
    assert routes["bookend_visual_planner"]["provider"] == "openai"
    assert routes["bookend_visual_planner"]["model"] == "gpt-4o-mini"
    assert routes["story_visual_planner"]["provider"] == "moonshot"
    assert routes["story_visual_planner"]["model"] == "kimi-k3"
    assert routes["story_visual_planner"]["max_attempts"] == 1
    assert routes["story_visual_planner"]["provider_options"] == {
        "thinking": None,
        "omit_temperature": True,
        "request_timeout_seconds": 600.0,
    }
    assert routes["story_visual_editor"]["provider"] == "moonshot"
    assert routes["story_visual_editor"]["model"] == "kimi-k3"
    assert routes["story_visual_editor"]["max_attempts"] == 1
    assert routes["story_visual_editor"]["provider_options"] == {
        "thinking": None,
        "omit_temperature": True,
        "request_timeout_seconds": 600.0,
    }


def test_kimi_k3_rejects_an_explicit_temperature_before_api_use() -> None:
    with pytest.raises(ValueError, match="omit_temperature=true"):
        make_llm(
            provider="moonshot",
            model="kimi-k3",
            temperature=1.0,
            provider_options={"omit_temperature": False},
        )


def test_story_planner_prompt_hides_system_managed_transition() -> None:
    config = VisualPlannerConfig.model_validate(_planner_config()).model_dump(mode="json")
    capabilities = _visual_capabilities_for_prompt(config, include_system_managed=False)

    assert "story_transition_scene" not in capabilities
    assert set(capabilities) == {
        "source_article_scene",
        "context_image_scene",
        "broll_video_scene",
        "logo_reveal_scene",
        "editorial_text_scene",
        "simple_explainer_scene",
        "quote_or_claim_highlight_scene",
        "data_counter_scene",
        "benchmark_delta_scene",
        "ecosystem_map_scene",
        "architecture_flow_scene",
        "process_zoom_scene",
        "browser_walkthrough_scene",
        "capability_matrix_scene",
        "document_stack_scene",
        "interface_transform_scene",
    }
    explainer_contract = capabilities["simple_explainer_scene"][
        "payload_field_contract"
    ]
    assert "2-4 objects" in explainer_contract["required"]["items"]
    assert "example" not in explainer_contract
    assert "asset_source_image_example" not in json.dumps(capabilities)
    assert (
        "required concise explanation"
        in capabilities["simple_explainer_scene"]["common_scene_field_contract"][
            "evidence_text"
        ]
    )


def test_story_provider_schema_exposes_only_active_user_plannable_kinds() -> None:
    output_model = _story_visual_plan_output_model(
        [
            "source_article_scene",
            "editorial_text_scene",
            "simple_explainer_scene",
            "story_transition_scene",
        ]
    )
    assert "anchor_asset_id" not in output_model.model_fields
    assert "anchor_scene_order" not in output_model.model_fields
    base_scene = {
        "order": 1,
        "start_unit_order": 2,
        "end_unit_order": 2,
        "script_excerpt": "A canonical script beat.",
        "visual_intent": "Explain the beat.",
        "evidence_record_keys": [],
        "evidence_truth_ids": [],
        "evidence_text": "A canonical script beat.",
        "grounding_basis": "script_beat",
        "payload_json": json.dumps(
            {
                "headline": "A clear idea",
                "accent_words": ["clear"],
                "composition": "editorial_center",
                "motion_style": "word_reveal",
            }
        ),
        "reason": "Useful visual support.",
    }

    accepted = output_model.model_validate(
        {
            "story_id": "story_test",
            "visual_strategy": "Use clean editorial visuals.",
            "key_entities": [],
            "scene_timeline": [
                {**base_scene, "render_kind": "editorial_text_scene"}
            ],
            "warnings": [],
        }
    )
    assert accepted.scene_timeline[0].render_kind == "editorial_text_scene"

    with pytest.raises(ValidationError):
        output_model.model_validate(
            {
                "story_id": "story_test",
                "visual_strategy": "Use clean editorial visuals.",
                "key_entities": [],
                "scene_timeline": [
                    {**base_scene, "render_kind": "kinetic_type_scene"}
                ],
                "warnings": [],
            }
        )

    with pytest.raises(ValidationError, match="at least 2 object item"):
        output_model.model_validate(
            {
                "story_id": "story_test",
                "visual_strategy": "Use clean editorial visuals.",
                "key_entities": [],
                "scene_timeline": [
                    {
                        **base_scene,
                        "render_kind": "simple_explainer_scene",
                        "payload_json": json.dumps(
                            {
                                "headline": "Only one idea",
                                "items": [{"label": "One"}],
                                "orientation": "horizontal",
                                "motion_style": "sequential_focus",
                            }
                        ),
                    }
                ],
                "warnings": [],
            }
        )


def test_visual_editor_uses_the_same_nested_plan_contract_and_rejects_system_transitions() -> None:
    story_plan_model = _story_visual_plan_output_model(
        [
            "source_article_scene",
            "editorial_text_scene",
            "story_transition_scene",
        ]
    )
    editor_model = _story_visual_edit_output_model(story_plan_model)
    scene = {
        "order": 1,
        "start_unit_order": 2,
        "end_unit_order": 2,
        "render_kind": "editorial_text_scene",
        "script_excerpt": "The active narration beat.",
        "visual_intent": "Emphasize one clear implication.",
        "evidence_record_keys": [],
        "evidence_truth_ids": [],
        "evidence_text": "The active narration beat.",
        "grounding_basis": "script_beat",
        "payload_json": json.dumps(
            {
                "headline": "One clear implication",
                "accent_words": ["clear"],
                "composition": "editorial_center",
                "motion_style": "word_reveal",
            }
        ),
        "reason": "The current plan used unrelated media.",
    }
    accepted = editor_model.model_validate(
        {
            "revision_required": True,
            "diagnosis": ["The current visual does not match the active narration."],
            "revised_plan": {
                "story_id": "story_test",
                "visual_strategy": "Use one grounded editorial treatment.",
                "key_entities": [],
                "scene_timeline": [scene],
                "warnings": [],
            },
        }
    )
    assert accepted.revised_plan.scene_timeline[0].render_kind == "editorial_text_scene"

    with pytest.raises(ValidationError):
        editor_model.model_validate(
            {
                "revision_required": True,
                "diagnosis": ["Add another title transition."],
                "revised_plan": {
                    "story_id": "story_test",
                    "visual_strategy": "Duplicate the system transition.",
                    "key_entities": [],
                    "scene_timeline": [
                        {**scene, "render_kind": "story_transition_scene"}
                    ],
                    "warnings": [],
                },
            }
        )


def test_provider_scene_formatting_is_preserved_without_code_rewriting() -> None:
    scene, repairs = _normalize_provider_scene_fields(
        {
            "render_kind": "simple_explainer_scene",
            "start_unit_order": 4,
            "end_unit_order": 4,
            "grounding_basis": "script_beat",
            "evidence_text": "",
            "payload_json": json.dumps(
                {
                    "headline": "Before and after",
                    "items": [
                        {"label": "Before", "value": "Manual"},
                        {"label": "After", "detail": "Assisted"},
                    ],
                    "orientation": "horizontal",
                    "motion_style": "sequential_focus",
                }
            ),
        },
        section={
            "script_units": [
                {
                    "order": 4,
                    "text": "The workflow moves from manual review to assisted review.",
                }
            ]
        },
    )

    payload = json.loads(scene["payload_json"])
    assert scene["evidence_text"] == ""
    assert payload["items"][0] == {"label": "Before", "value": "Manual"}
    assert repairs == []


def test_one_item_explainer_is_rejected_instead_of_changed_into_another_scene() -> None:
    scene, repairs = _normalize_provider_scene_fields(
        {
            "render_kind": "simple_explainer_scene",
            "start_unit_order": 8,
            "end_unit_order": 8,
            "grounding_basis": "script_beat",
            "evidence_text": "A reported total of 570 vulnerabilities.",
            "payload_json": json.dumps(
                {
                    "headline": "570 vulnerabilities",
                    "items": [{"label": "Reported total", "detail": "570"}],
                    "orientation": "horizontal",
                    "motion_style": "sequential_focus",
                }
            ),
        },
        section={"script_units": []},
        allowed_render_kinds={"simple_explainer_scene", "editorial_text_scene"},
    )

    payload = json.loads(scene["payload_json"])
    assert scene["render_kind"] == "simple_explainer_scene"
    assert payload["headline"] == "570 vulnerabilities"
    assert repairs == []
    assert validate_scene_payload(scene["render_kind"], payload) == [
        "payload.items requires at least 2 object item(s)"
    ]


def test_chatgpt_handoff_hides_system_managed_transition() -> None:
    config = VisualPlannerConfig.model_validate(_planner_config()).model_dump(mode="json")
    artifact = {
        "visual_context": {
            "scene_policy": deepcopy(config["scene_policy"]),
            "visual_capabilities": deepcopy(config["visual_capabilities"]),
        },
        "asset_catalog": {"assets": [{"asset_id": "asset_source"}]},
    }

    prepared = _prepare_artifact("visual_scene_plan", artifact)

    assert "story_transition_scene" not in prepared["visual_context"]["scene_policy"][
        "allowed_render_kinds"
    ]
    assert prepared["visual_context"]["system_managed_render_kinds"] == [
        "story_transition_scene"
    ]


def test_editorial_code_scenes_require_no_external_asset() -> None:
    assert {
        "editorial_text_scene",
        "simple_explainer_scene",
        "story_transition_scene",
    } <= NO_ASSET_RENDER_KINDS


def test_editorial_scene_payloads_are_structurally_renderable() -> None:
    fixture_dir = PROJECT_ROOT / "tests/fixtures/editorial_minimal_visuals"
    for path in sorted(fixture_dir.glob("*.json")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        scene = spec["scene"]
        assert validate_scene_payload(scene["render_kind"], scene["payload"]) == []
