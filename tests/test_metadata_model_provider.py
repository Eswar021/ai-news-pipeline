from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from langchain_core.runnables import RunnableLambda
from pydantic import TypeAdapter
import pytest
import yaml

from src.pipeline.config import ConfigRepository

from src.pipeline.content.metadata_creator.app import (
    MetadataDraftOutput,
    TASK_PROMPT,
    _invoke_runtime_chain,
    _provider_failover_summary,
    _structured_output_options,
    _task_payload_for_structured_output,
)
from src.pipeline.content.metadata_creator.contract import LLMProvider, MetadataConfig
from src.pipeline.content.metadata_creator.llm_client import make_llm
from src.pipeline.content.script_generation.formats.roundup.app import _resolved_llm_configs


ROOT = Path(__file__).resolve().parents[1]


def _profile() -> dict:
    repository = ConfigRepository(ROOT / "src/pipeline/config/workbench.yaml", environment="prod")
    return deepcopy(repository.profile(repository.default_profile).value)


def test_metadata_prompt_keeps_system_and_user_roles_separate() -> None:
    messages = TASK_PROMPT.format_messages(
        system_prompt="System instructions",
        user_preamble="User task",
        task_payload='{"section_id":"section_00_intro"}',
    )

    assert [message.type for message in messages] == ["system", "human"]
    assert messages[0].content == "System instructions"
    assert "Task payload:" in str(messages[1].content)


def test_moonshot_is_a_valid_metadata_provider() -> None:
    assert TypeAdapter(LLMProvider).validate_python("moonshot") == "moonshot"


def test_deepseek_is_a_valid_metadata_provider() -> None:
    assert TypeAdapter(LLMProvider).validate_python("deepseek") == "deepseek"


def test_metadata_moonshot_client_uses_configured_api(monkeypatch) -> None:
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    llm = make_llm(
        provider="moonshot",
        model="kimi-k3",
        temperature=1.0,
        provider_options={
            "omit_temperature": True,
            "request_timeout_seconds": 360,
        },
    )

    assert llm.model_name == "kimi-k3"
    assert str(llm.openai_api_base) == "https://api.moonshot.ai/v1"
    assert llm.request_timeout == 360.0


def test_metadata_deepseek_client_uses_thinking_max(monkeypatch) -> None:
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


def test_metadata_json_mode_embeds_schema_without_passing_strict() -> None:
    options = _structured_output_options({"method": "json_mode", "strict": False})
    payload = _task_payload_for_structured_output(
        '{"selected_format":"roundup"}',
        output_model=MetadataDraftOutput,
        method=options["method"],
    )

    assert options == {"include_raw": True, "method": "json_mode"}
    assert "JSON Schema:" in payload
    assert '"title_options"' in payload


def test_production_routes_deepseek_to_viewer_facing_creative_roles() -> None:
    profile = _profile()
    routes = _resolved_llm_configs(profile["script_generation"])
    metadata = MetadataConfig.model_validate(
        {**profile["metadata_creator"], "channel": profile["channel"]}
    )

    assert routes["source_researcher"]["provider"] == "openai"
    assert routes["director"]["provider"] == "openai"
    assert routes["story_writer"]["provider"] == "deepseek"
    assert routes["story_writer"]["model"] == "deepseek-v4-pro"
    assert routes["story_reviewer"]["model"] == "deepseek-v4-pro"
    assert routes["bookend_writer"]["model"] == "deepseek-v4-pro"
    assert routes["bookend_reviewer"]["model"] == "deepseek-v4-pro"
    assert routes["story_writer"]["provider_options"]["reasoning_effort"] == "max"
    assert routes["story_writer"]["structured_output"] == {
        "method": "json_mode",
        "strict": False,
    }
    assert profile["script_generation"]["worker_count"] == 2
    assert metadata.provider == "deepseek"
    assert metadata.model == "deepseek-v4-pro"
    assert metadata.provider_options.reasoning_effort == "max"
    assert metadata.structured_output.method == "json_mode"
    assert metadata.content_filter_fallback is not None
    assert metadata.content_filter_fallback.provider == "openai"
    assert metadata.content_filter_fallback.model == "gpt-4o"


def test_metadata_content_filter_rejection_uses_configured_fallback() -> None:
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
                    "title_options": [
                        {
                            "title": "Five AI Stories Worth Watching",
                            "accuracy_risk": "low",
                            "click_potential": "medium_high",
                            "why_it_works": "It signals a concrete roundup.",
                            "angle_strategy": "concrete_list",
                            "represented_story_ids": ["story_one"],
                            "relationship_basis": "",
                            "scope_and_state_check": "The title clearly signals roundup scope.",
                        }
                    ],
                    "thumbnail_text_options": ["FIVE AI SHIFTS"],
                    "thumbnail_concepts": [
                        {
                            "concept_name": "Five Signals",
                            "visual_hook": "Five concrete AI changes converge around one central question.",
                            "primary_subject": "A clean five-part editorial composition",
                            "secondary_subjects": [],
                            "composition": "One dominant center subject with five restrained evidence fragments.",
                            "background_direction": "Warm editorial paper texture.",
                            "text_overlay": "FIVE AI SHIFTS",
                            "color_direction": "Warm cream, near-black, and burnt orange.",
                            "emotional_tone": "Curious and consequential.",
                            "represented_story_ids": ["story_one"],
                            "source_record_keys": [],
                            "generation_prompt": "Create a clean 16:9 editorial YouTube thumbnail with one dominant center subject and five restrained evidence fragments.",
                            "avoid": ["generic robots", "tiny text"],
                        }
                    ],
                    "blocked_title_angles": [],
                    "chapter_titles": [
                        {"section_id": "section_00_intro", "title": "What Changed"}
                    ],
                    "description_intro": "A concise look at this episode's AI developments.",
                    "tags": ["AI news"],
                }
                return {
                    "raw": None,
                    "parsed": model.model_validate(payload),
                    "parsing_error": None,
                }

            return RunnableLambda(invoke)

    calls: list[dict] = []
    output = _invoke_runtime_chain(
        module_name="youtube_metadata_creator",
        output_model=MetadataDraftOutput,
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
        metadata={"selected_format": "roundup"},
        llm_calls=calls,
    )

    assert output["description_intro"].startswith("A concise look")
    assert [call["provider"] for call in calls] == ["moonshot", "openai"]
    assert calls[0]["metadata"]["route_attempt"] == "primary"
    assert calls[0]["metadata"]["parse_error"]
    assert calls[1]["metadata"]["route_attempt"] == "content_filter_fallback"
    assert _provider_failover_summary(calls)["content_filter_fallback_call_count"] == 1


def test_metadata_unrelated_bad_request_does_not_switch_provider() -> None:
    class InvalidRequestError(Exception):
        status_code = 400

    class RejectingLLM:
        def with_structured_output(self, _model, **_kwargs):
            return RunnableLambda(
                lambda _prompt: (_ for _ in ()).throw(InvalidRequestError("invalid request schema"))
            )

    class UnexpectedFallbackLLM:
        called = False

        def with_structured_output(self, _model, **_kwargs):
            self.called = True
            return RunnableLambda(lambda _prompt: {})

    fallback = UnexpectedFallbackLLM()
    with pytest.raises(InvalidRequestError):
        _invoke_runtime_chain(
            module_name="youtube_metadata_creator",
            output_model=MetadataDraftOutput,
            llm_runtime={
                "llm": RejectingLLM(),
                "config": {
                    "provider": "moonshot",
                    "model": "kimi-k3",
                    "structured_output": {"method": "json_schema", "strict": True},
                    "llm_retry": {"enabled": True, "max_attempts": 1},
                },
                "content_filter_fallback": {
                    "llm": fallback,
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
            metadata={},
            llm_calls=[],
        )

    assert fallback.called is False
