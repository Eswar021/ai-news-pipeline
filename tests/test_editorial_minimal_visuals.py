from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, ValidationError

from src.pipeline.config import ConfigRepository

from src.pipeline.handoffs.chatgpt_exporter.app import _prepare_artifact
from src.pipeline.visuals.asset_resolver.app import NO_ASSET_RENDER_KINDS
from src.pipeline.visuals.payload_validation import validate_scene_payload
from src.pipeline.visuals.planner.app import (
    _bookend_scene_owner_story_id,
    _catalog_asset_for_scene,
    _invoke_chain_with_attempts,
    _normalize_catalog_scene_reference,
    _normalize_provider_scene_fields,
    _provider_failover_summary,
    _resolved_llm_configs,
    _structured_output_options,
    _story_visual_edit_output_model,
    _story_visual_plan_output_model,
    _task_payload_for_structured_output,
    _visual_capabilities_for_prompt,
)
from src.pipeline.visuals.planner.contract import VisualPlannerConfig
from src.pipeline.visuals.planner.llm_client import make_llm


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _planner_config() -> dict:
    repository = ConfigRepository(
        PROJECT_ROOT / "src/pipeline/config/workbench.yaml",
        environment="prod",
    )
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
        "browser_walkthrough_scene",
        "document_stack_scene",
        "interface_transform_scene",
    ]
    assert not {
        "data_counter_scene",
        "benchmark_delta_scene",
        "architecture_flow_scene",
        "process_zoom_scene",
    } & set(config["scene_policy"]["allowed_render_kinds"])


def test_production_visual_planner_uses_deepseek_for_story_creative_roles() -> None:
    config = VisualPlannerConfig.model_validate(_planner_config()).model_dump(mode="json")
    routes = _resolved_llm_configs(config)

    assert routes["episode_director"]["provider"] == "openai"
    assert routes["episode_director"]["model"] == "gpt-4o-mini"
    assert routes["bookend_visual_planner"]["provider"] == "openai"
    assert routes["bookend_visual_planner"]["model"] == "gpt-4o-mini"
    assert routes["story_visual_planner"]["provider"] == "deepseek"
    assert routes["story_visual_planner"]["model"] == "deepseek-v4-pro"
    assert routes["story_visual_planner"]["max_attempts"] == 2
    assert routes["story_visual_planner"]["provider_options"] == {
        "thinking": "enabled",
        "omit_temperature": True,
        "reasoning_effort": "max",
        "request_timeout_seconds": 600.0,
    }
    assert routes["story_visual_planner"]["structured_output"] == {
        "method": "json_mode",
        "strict": False,
    }
    assert routes["story_visual_planner"]["content_filter_fallback"]["provider"] == "openai"
    assert routes["story_visual_planner"]["content_filter_fallback"]["model"] == "gpt-4o"
    assert routes["story_visual_planner"]["content_filter_fallback"]["max_attempts"] == 2
    assert routes["story_visual_editor"]["provider"] == "deepseek"
    assert routes["story_visual_editor"]["model"] == "deepseek-v4-pro"
    assert routes["story_visual_editor"]["max_attempts"] == 2
    assert routes["story_visual_editor"]["provider_options"] == {
        "thinking": "enabled",
        "omit_temperature": True,
        "reasoning_effort": "max",
        "request_timeout_seconds": 600.0,
    }
    assert routes["story_visual_editor"]["content_filter_fallback"]["provider"] == "openai"
    assert routes["story_visual_editor"]["content_filter_fallback"]["model"] == "gpt-4o"


def test_visual_story_call_uses_openai_only_after_explicit_content_filter_rejection() -> None:
    class Draft(BaseModel):
        value: str

    class ProviderContentFilterError(Exception):
        status_code = 400

    class RejectingLLM:
        def with_structured_output(self, _model, **_kwargs):
            return RunnableLambda(
                lambda _prompt: (_ for _ in ()).throw(
                    ProviderContentFilterError("request rejected as high risk by content_filter")
                )
            )

    class WorkingLLM:
        def with_structured_output(self, model, **_kwargs):
            return RunnableLambda(
                lambda _prompt: {
                    "raw": None,
                    "parsed": model(value="usable visual plan"),
                    "parsing_error": None,
                }
            )

    calls: list[dict] = []
    output = _invoke_chain_with_attempts(
        module_name="story_visual_planner",
        output_model=Draft,
        llm_runtime={
            "llm": RejectingLLM(),
            "config": {
                "provider": "moonshot",
                "model": "kimi-k3",
                "structured_output": {"method": "json_schema", "strict": True},
                "max_attempts": 1,
            },
            "content_filter_fallback": {
                "llm": WorkingLLM(),
                "config": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "structured_output": {"method": "json_schema", "strict": True},
                    "max_attempts": 2,
                },
            },
        },
        prompt_bundle={"system": "System", "user_preamble": "User"},
        task_payload={},
        metadata={"story_id": "story_sensitive"},
        llm_calls=calls,
    )

    assert output == {"value": "usable visual plan"}
    assert [call["provider"] for call in calls] == ["moonshot", "openai"]
    assert calls[0]["metadata"]["route_attempt"] == "primary"
    assert calls[0]["metadata"]["parse_error"]
    assert calls[1]["metadata"]["route_attempt"] == "content_filter_fallback"
    assert _provider_failover_summary(calls) == {
        "content_filter_fallback_call_count": 1,
        "events": [
            {
                "module_name": "story_visual_planner",
                "story_id": "story_sensitive",
                "trigger": "content_filter",
                "from_provider": "moonshot",
                "from_model": "kimi-k3",
                "to_provider": "openai",
                "to_model": "gpt-4o",
            }
        ],
    }


def test_visual_story_call_does_not_switch_provider_for_unrelated_bad_request() -> None:
    class Draft(BaseModel):
        value: str

    class InvalidRequestError(Exception):
        status_code = 400

    class RejectingLLM:
        def with_structured_output(self, _model, **_kwargs):
            return RunnableLambda(
                lambda _prompt: (_ for _ in ()).throw(
                    InvalidRequestError("invalid structured output schema")
                )
            )

    class UnexpectedFallbackLLM:
        called = False

        def with_structured_output(self, model, **_kwargs):
            self.called = True
            return RunnableLambda(
                lambda _prompt: {
                    "raw": None,
                    "parsed": model(value="unexpected"),
                    "parsing_error": None,
                }
            )

    fallback = UnexpectedFallbackLLM()
    with pytest.raises(RuntimeError, match="failed after 1 bounded attempt"):
        _invoke_chain_with_attempts(
            module_name="story_visual_planner",
            output_model=Draft,
            llm_runtime={
                "llm": RejectingLLM(),
                "config": {
                    "provider": "moonshot",
                    "model": "kimi-k3",
                    "structured_output": {"method": "json_schema", "strict": True},
                    "max_attempts": 1,
                },
                "content_filter_fallback": {
                    "llm": fallback,
                    "config": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "structured_output": {"method": "json_schema", "strict": True},
                        "max_attempts": 1,
                    },
                },
            },
            prompt_bundle={"system": "System", "user_preamble": "User"},
            task_payload={},
            metadata={"story_id": "story_regular"},
            llm_calls=[],
        )

    assert fallback.called is False


def test_kimi_k3_rejects_an_explicit_temperature_before_api_use() -> None:
    with pytest.raises(ValueError, match="omit_temperature=true"):
        make_llm(
            provider="moonshot",
            model="kimi-k3",
            temperature=1.0,
            provider_options={"omit_temperature": False},
        )


def test_visual_deepseek_client_uses_thinking_max(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    llm = make_llm(
        provider="deepseek",
        model="deepseek-v4-pro",
        temperature=1.0,
        provider_options={
            "thinking": "enabled",
            "omit_temperature": True,
            "reasoning_effort": "max",
            "request_timeout_seconds": 600,
        },
    )

    assert llm.model_name == "deepseek-v4-pro"
    assert str(llm.openai_api_base) == "https://api.deepseek.com"
    assert llm.extra_body == {"thinking": {"type": "enabled"}}
    assert llm.reasoning_effort == "max"
    assert llm.request_timeout == 600.0


def test_visual_json_mode_embeds_dynamic_schema_without_passing_strict() -> None:
    class Draft(BaseModel):
        value: str

    options = _structured_output_options({"method": "json_mode", "strict": False})
    payload = _task_payload_for_structured_output(
        '{"story_id":"story_1"}',
        output_model=Draft,
        method=options["method"],
    )

    assert options == {"include_raw": True, "method": "json_mode"}
    assert "JSON Schema:" in payload
    assert '"value"' in payload


def test_bookend_logo_binding_prefers_exact_declared_identity() -> None:
    catalog_index = {
        "assets_by_id": {
            "asset_nvidia": {
                "asset_id": "asset_nvidia",
                "story_id": "story_factory",
                "asset_type": "logo",
                "status": "available",
                "title": "NVIDIA",
            },
            "asset_openai": {
                "asset_id": "asset_openai",
                "story_id": "story_security",
                "asset_type": "logo",
                "status": "available",
                "title": "OpenAI",
            },
        },
        "assets_by_story": {
            "story_factory": [],
            "story_security": [
                {
                    "asset_id": "asset_openai",
                    "story_id": "story_security",
                    "asset_type": "logo",
                    "status": "available",
                    "title": "OpenAI",
                }
            ],
        },
    }
    scene = {
        "render_kind": "logo_reveal_scene",
        "asset_id": "asset_nvidia",
        "primary_entity": "OpenAI",
        "entities": ["OpenAI", "Google Cloud"],
    }

    owner = _bookend_scene_owner_story_id(
        scene,
        source_index={"records_by_key": {}},
        asset_catalog_index=catalog_index,
    )
    normalized, errors = _normalize_catalog_scene_reference(
        scene,
        story_id=owner,
        catalog_index=catalog_index,
        allowed_render_kinds={"logo_reveal_scene"},
    )

    assert owner == "story_security"
    assert errors == []
    assert normalized["asset_id"] == "asset_openai"
    assert normalized["primary_entity"] == "OpenAI"
    assert normalized["entities"] == ["OpenAI", "Google Cloud"]


def test_transition_background_and_episode_bookend_assets_validate() -> None:
    logo = {
        "asset_id": "asset_anthropic",
        "story_id": "story_anthropic",
        "asset_type": "logo",
        "status": "available",
        "title": "Anthropic",
        "source_record_key": "",
        "source_url": "",
    }
    catalog_index = {
        "assets_by_id": {"asset_anthropic": logo},
        "assets_by_story": {"story_anthropic": [logo]},
    }

    transition_asset, transition_errors = _catalog_asset_for_scene(
        {
            "asset_id": "asset_anthropic",
            "background_render_kind": "logo_reveal_scene",
        },
        story_id="story_anthropic",
        render_kind="story_transition_scene",
        catalog_index=catalog_index,
    )
    bookend_asset, bookend_errors = _catalog_asset_for_scene(
        {"asset_id": "asset_anthropic"},
        story_id="",
        render_kind="logo_reveal_scene",
        catalog_index=catalog_index,
        allow_episode_asset=True,
    )

    assert transition_asset == logo
    assert transition_errors == []
    assert bookend_asset == logo
    assert bookend_errors == []


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
        "browser_walkthrough_scene",
        "document_stack_scene",
        "interface_transform_scene",
    }
    assert all(capability["available_recipes"] for capability in capabilities.values())
    assert all(
        "recipe_id" in capability["payload_field_contract"]["required"]
        for capability in capabilities.values()
    )
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
