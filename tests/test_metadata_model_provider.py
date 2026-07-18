from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from pydantic import TypeAdapter
import yaml

from src.pipeline.apps.metadata_creator.app import TASK_PROMPT
from src.pipeline.apps.metadata_creator.contract import LLMProvider, MetadataConfig
from src.pipeline.apps.metadata_creator.llm_client import make_llm
from src.pipeline.apps.script_generation.formats.roundup.app import _resolved_llm_configs


ROOT = Path(__file__).resolve().parents[1]


def _profile() -> dict:
    workbench = yaml.safe_load(
        (ROOT / "src/pipeline/config/workbench.yaml").read_text(encoding="utf-8")
    )
    return deepcopy(workbench["profiles"][workbench["default_run_profile"]])


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


def test_production_routes_k3_only_to_viewer_facing_creative_roles() -> None:
    profile = _profile()
    routes = _resolved_llm_configs(profile["script_generation"])
    metadata = MetadataConfig.model_validate(
        {**profile["metadata_creator"], "channel": profile["channel"]}
    )

    assert routes["source_researcher"]["provider"] == "openai"
    assert routes["director"]["provider"] == "openai"
    assert routes["story_writer"]["model"] == "kimi-k3"
    assert routes["story_reviewer"]["model"] == "kimi-k3"
    assert routes["bookend_writer"]["model"] == "kimi-k3"
    assert routes["bookend_reviewer"]["model"] == "kimi-k3"
    assert profile["script_generation"]["worker_count"] == 2
    assert metadata.provider == "moonshot"
    assert metadata.model == "kimi-k3"
