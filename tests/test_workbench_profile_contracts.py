from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from src.pipeline.apps.editorial_selection.formats.roundup.contract import (
    RoundupEditorialSelectionConfig,
)
from src.pipeline.apps.editorial_triage.contract import EditorialTriageConfig
from src.pipeline.apps.metadata_creator.contract import MetadataConfig
from src.pipeline.apps.script_generation.formats.roundup.contract import RoundupScriptConfig
from src.pipeline.apps.story_mapping.contract import StoryMappingConfig
from src.pipeline.apps.video_packaging.contract import VideoPackagingConfig
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
    workbench = yaml.safe_load(WORKBENCH_PATH.read_text(encoding="utf-8"))
    return deepcopy(workbench["profiles"][workbench["default_run_profile"]])


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
    assert visuals["asset_resolver"]["source_screenshots"]["target_miss_policy"] == "failed"
    assert visuals["asset_resolver"]["logos"]["favicon_fallback_enabled"] is False
    VisualRenderConfig.model_validate(_with_output_dir(visuals["render"], "render"))
    VideoAssemblyConfig.model_validate(
        _with_output_dir(visuals["assembly"], "assembly")
    )
    VisualReviewConfig.model_validate(_with_output_dir(visuals["review"], "review"))
    VoiceoverConfig.model_validate(_with_output_dir(profile["voiceover"], "voiceover"))
