from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from src.pipeline.config import ConfigRepository
from src.pipeline.content.editorial_selection.formats.roundup.contract import (
    RoundupEditorialSelectionConfig,
)
from src.pipeline.content.editorial_triage.contract import EditorialTriageConfig
from src.pipeline.content.metadata_creator.contract import MetadataConfig
from src.pipeline.content.script_generation.formats.roundup.contract import RoundupScriptConfig
from src.pipeline.content.story_mapping.contract import StoryMappingConfig
from src.pipeline.content.video_packaging.contract import VideoPackagingConfig
from src.pipeline.voiceover.contract import VoiceoverConfig


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_PATH = ROOT / "src" / "pipeline" / "config" / "workbench.yaml"


def _profile() -> dict:
    repository = ConfigRepository(WORKBENCH_PATH)
    return deepcopy(repository.profile(repository.default_profile).value)


def _with_output_dir(config: dict, module_name: str) -> dict:
    resolved = deepcopy(config)
    resolved["output_dir"] = f"/tmp/ai_content_creation_profile_test/{module_name}"
    return resolved


def test_default_workbench_profile_composes_into_public_configs() -> None:
    profile = _profile()
    channel = profile["channel"]
    collection_window = {
        "start": "2026-07-12T00:00:00+05:30",
        "end": "2026-07-14T00:00:00+05:30",
        "lookback_hours": 48,
    }

    EditorialTriageConfig.model_validate(
        {**profile["editorial_triage"], "channel": channel}
    )
    StoryMappingConfig.model_validate(
        {**profile["story_mapping"], "collection_window": collection_window}
    )
    RoundupEditorialSelectionConfig.model_validate(
        {**profile["editorial_selection"], "channel": channel}
    )
    VideoPackagingConfig.model_validate(profile["video_packaging"])
    RoundupScriptConfig.model_validate(profile["script_generation"])
    MetadataConfig.model_validate({**profile["metadata_creator"], "channel": channel})

    assert "visuals" not in profile
    VoiceoverConfig.model_validate(_with_output_dir(profile["voiceover"], "voiceover"))
    preview_voiceover = deepcopy(profile["voiceover"])
    preview_voiceover.update(profile["voiceover_preview"])
    validated_preview = VoiceoverConfig.model_validate(
        _with_output_dir(preview_voiceover, "voiceover_preview")
    )
    assert validated_preview.provider == "kokoro_local"
    assert validated_preview.voice == "af_heart"


def test_module_config_has_independent_source_identity() -> None:
    repository = ConfigRepository(WORKBENCH_PATH)
    profile_name = repository.default_profile
    script = repository.module(profile_name, "content", "script_generation")
    voiceover = repository.module(profile_name, "voiceover", "voiceover")
    voiceover_preview = repository.module(profile_name, "voiceover", "voiceover_preview")

    assert script.sha256 != voiceover.sha256
    assert script.source_paths[-1].endswith("content/script_generation.yaml")
    assert voiceover.source_paths[-1].endswith("voiceover/voiceover.yaml")
    assert voiceover_preview.source_paths[-1].endswith("voiceover/voiceover_preview.yaml")
    assert repository.profile(profile_name).value["script_generation"] == script.value
    assert repository.profile(profile_name).value["voiceover"] == voiceover.value
    assert repository.profile(profile_name).value["voiceover_preview"] == voiceover_preview.value


def test_environment_overlays_change_only_declared_module_behavior() -> None:
    production = ConfigRepository(WORKBENCH_PATH, environment="prod")
    development = ConfigRepository(WORKBENCH_PATH, environment="dev")
    staging = ConfigRepository(WORKBENCH_PATH, environment="staging")
    profile_name = production.default_profile

    production_script = production.module(profile_name, "content", "script_generation")
    development_script = development.module(profile_name, "content", "script_generation")
    staging_script = staging.module(profile_name, "content", "script_generation")

    assert production_script.value["llm_roles"]["story_writer"]["model"] == "deepseek-v4-pro"
    assert staging_script.value["llm_roles"]["story_writer"]["model"] == "deepseek-v4-pro"
    assert development_script.value["llm_roles"]["story_writer"]["model"] == "gpt-4o-mini"
    assert production_script.sha256 != development_script.sha256
    assert production_script.source_paths[-1].endswith("content/script_generation.yaml")
    assert "environments/dev.yaml" in development_script.source_paths


def test_manifest_exposes_stage_ownership_and_default_dev_environment() -> None:
    repository = ConfigRepository(WORKBENCH_PATH)
    profile_name = repository.default_profile

    assert repository.environment == "dev"
    assert set(repository.environment_names()) == {"dev", "staging", "prod"}
    assert repository.module(profile_name, "ingestion", "news_collection").value
    assert repository.module(profile_name, "publishing", "metadata_finalizer").value
    assert repository.module(profile_name, "publishing", "publish_handoff").value
    assert repository.module(profile_name, "content", "metadata_creator").value[
        "metadata_policy"
    ]["thumbnail_concept_count"] == 3
