from __future__ import annotations

from pydantic import TypeAdapter

from src.pipeline.content.script_generation.formats.roundup.app import _resolved_llm_configs
from src.pipeline.content.script_generation.formats.roundup.contract import LLMProvider
from src.pipeline.content.script_generation.shared.llm_client import make_llm
from src.pipeline.content.script_generation.shared.llm_logging import build_llm_call_log
from src.pipeline.content.script_generation.formats.roundup.models import StoryReviewOutput
from src.pipeline.content.script_generation.formats.roundup.writer import (
    TASK_PROMPT,
    _structured_output_options,
    _task_payload_for_structured_output,
)
from src.pipeline.orchestration.script_model_comparison import (
    ComparisonVariant,
    _aggregate_usage_by_route,
    _estimate_variant_costs,
)


def test_script_prompt_keeps_system_and_user_roles_separate() -> None:
    messages = TASK_PROMPT.format_messages(
        system_prompt="System instructions",
        user_preamble="User task",
        task_payload='{"story_id":"story_1"}',
    )

    assert [message.type for message in messages] == ["system", "human"]
    assert messages[0].content == "System instructions"
    assert "Task payload:" in str(messages[1].content)


def test_moonshot_is_a_valid_script_provider() -> None:
    assert TypeAdapter(LLMProvider).validate_python("moonshot") == "moonshot"


def test_deepseek_is_a_valid_script_provider() -> None:
    assert TypeAdapter(LLMProvider).validate_python("deepseek") == "deepseek"


def test_deepseek_client_uses_beta_api_and_explicit_thinking_mode(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    llm = make_llm(
        provider="deepseek",
        model="deepseek-v4-pro",
        temperature=0.4,
        base_url="https://api.deepseek.com/beta",
        provider_options={
            "thinking": "disabled",
            "omit_temperature": False,
            "request_timeout_seconds": 240,
        },
    )

    assert llm.model_name == "deepseek-v4-pro"
    assert str(llm.openai_api_base) == "https://api.deepseek.com/beta"
    assert llm.temperature == 0.4
    assert llm.extra_body == {"thinking": {"type": "disabled"}}
    assert llm.request_timeout == 240.0


def test_json_mode_embeds_schema_without_passing_strict() -> None:
    options = _structured_output_options({"method": "json_mode", "strict": False})
    payload = _task_payload_for_structured_output(
        '{"story_id":"story_1"}',
        output_model=StoryReviewOutput,
        method=options["method"],
    )

    assert options == {"include_raw": True, "method": "json_mode"}
    assert "JSON Schema:" in payload
    assert '"rewrite_required"' in payload


def test_moonshot_client_uses_configured_api_and_thinking_mode(monkeypatch) -> None:
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    llm = make_llm(
        provider="moonshot",
        model="kimi-k2.6",
        temperature=0.6,
        provider_options={"thinking": "disabled", "request_timeout_seconds": 240},
    )

    assert llm.model_name == "kimi-k2.6"
    assert str(llm.openai_api_base) == "https://api.moonshot.ai/v1"
    assert llm.temperature == 0.6
    assert llm.extra_body == {"thinking": {"type": "disabled"}}
    assert llm.request_timeout == 240.0


def test_script_llm_log_preserves_actual_chat_roles() -> None:
    messages = [
        {"role": "system", "content": "System instructions"},
        {"role": "user", "content": "User task"},
    ]
    entry = build_llm_call_log(
        module_name="test",
        provider="moonshot",
        model="kimi-k2.6",
        messages=messages,
        raw_response=None,
        parsed_output={"ok": True},
        metadata={},
        duration_seconds=0.1,
    )

    assert entry["messages"] == messages


def test_script_role_routes_override_only_selected_roles() -> None:
    routes = _resolved_llm_configs(
        {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.4,
            "provider_options": {"request_timeout_seconds": 300},
            "structured_output": {"method": "json_schema", "strict": True},
            "llm_retry": {"enabled": True, "max_attempts": 2},
            "llm_roles": {
                "story_writer": {
                    "provider": "moonshot",
                    "model": "kimi-k3",
                    "temperature": 1.0,
                    "provider_options": {
                        "omit_temperature": True,
                        "request_timeout_seconds": 360,
                    },
                    "structured_output": {"method": "json_schema", "strict": True},
                    "llm_retry": None,
                    "content_filter_fallback": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "temperature": 0.4,
                        "provider_options": {"request_timeout_seconds": 300},
                        "structured_output": {"method": "json_schema", "strict": True},
                        "llm_retry": None,
                    },
                }
            },
        }
    )

    assert routes["source_researcher"]["provider"] == "openai"
    assert routes["story_reviewer"]["model"] == "gpt-4o"
    assert routes["story_writer"]["provider"] == "moonshot"
    assert routes["story_writer"]["model"] == "kimi-k3"
    assert routes["story_writer"]["llm_retry"] == {"enabled": True, "max_attempts": 2}
    assert routes["story_writer"]["content_filter_fallback"] == {
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.4,
        "base_url": None,
        "provider_options": {"request_timeout_seconds": 300},
        "structured_output": {"method": "json_schema", "strict": True},
        "llm_retry": {"enabled": True, "max_attempts": 2},
    }


def test_mixed_provider_comparison_prices_each_actual_route() -> None:
    calls = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100},
        },
        {
            "provider": "moonshot",
            "model": "kimi-k3",
            "usage": {"prompt_tokens": 2000, "completion_tokens": 200, "total_tokens": 2200},
        },
    ]
    usage_by_route = _aggregate_usage_by_route(calls)
    variant = ComparisonVariant.model_validate(
        {
            "id": "mixed",
            "config": {},
            "pricing_by_route": {
                "openai/gpt-4o": {"input_cache_miss": 2.5, "input_cache_hit": 1.25, "output": 10.0},
                "moonshot/kimi-k3": {"input_cache_miss": 3.0, "input_cache_hit": 0.3, "output": 15.0},
            },
        }
    )

    costs, unpriced = _estimate_variant_costs(
        usage={"prompt_tokens": 3000, "completion_tokens": 300, "total_tokens": 3300, "cache_read_tokens": 0, "reasoning_tokens": 0},
        usage_by_route=usage_by_route,
        variant=variant,
    )

    assert unpriced == []
    assert costs["openai/gpt-4o"] == 0.0035
    assert costs["moonshot/kimi-k3"] == 0.009
