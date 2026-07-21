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
from src.pipeline.visuals.assembly.contract import VideoAssemblyConfig
from src.pipeline.visuals.asset_resolver.contract import AssetResolverConfig
from src.pipeline.visuals.media_discovery.contract import VisualMediaConfig
from src.pipeline.visuals.planner.contract import VisualPlannerConfig
from src.pipeline.visuals.render.contract import VisualRenderConfig
from src.pipeline.visuals.review.contract import VisualReviewConfig
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

    visuals = profile["visuals"]
    VisualPlannerConfig.model_validate(visuals["planner"])
    VisualMediaConfig.model_validate(
        _with_output_dir(visuals["media_discovery"], "media_discovery")
    )
    AssetResolverConfig.model_validate(
        _with_output_dir(visuals["asset_resolver"], "asset_resolver")
    )
    assert visuals["asset_resolver"]["source_screenshots"]["target_miss_policy"] == "partial"
    assert visuals["asset_resolver"]["logos"]["favicon_fallback_enabled"] is False
    VisualRenderConfig.model_validate(_with_output_dir(visuals["render"], "render"))
    VideoAssemblyConfig.model_validate(
        _with_output_dir(visuals["assembly"], "assembly")
    )
    VisualReviewConfig.model_validate(_with_output_dir(visuals["review"], "review"))
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
    profile_name = production.default_profile

    production_planner = production.module(profile_name, "visuals", "planner")
    development_planner = development.module(profile_name, "visuals", "planner")
    production_render = production.module(profile_name, "visuals", "render")
    development_render = development.module(profile_name, "visuals", "render")

    assert production_planner.value["llm_roles"]["story_visual_planner"]["provider"] == "moonshot"
    assert development_planner.value["llm_roles"]["story_visual_planner"]["provider"] == "openai"
    assert production_render.value["backend"] == "remotion"
    assert development_render.value["backend"] == "remotion"
    assert production_planner.sha256 != development_planner.sha256
    assert production_planner.source_paths[-1].endswith("visuals/planner.yaml")
    assert "environments/dev.yaml" in development_planner.source_paths
