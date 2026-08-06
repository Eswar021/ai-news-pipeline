"""Guard against provider-support drift between the shared LLM client and the module
config contracts.

A run broke because story_mapping's contract pinned Literal["openai","gemini","lmstudio"]
and rejected the deepseek config we'd set — even though the shared client supports
deepseek. These tests validate the REAL profile configs against their REAL contracts,
so a provider we switch to in YAML can never be rejected by a stale contract again.
"""
from __future__ import annotations

import typing
from pathlib import Path

import yaml

from src.pipeline.llm import LLMProvider

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "src" / "pipeline" / "config" / "profiles"


def test_shared_llm_provider_covers_every_supported_provider() -> None:
    providers = set(typing.get_args(LLMProvider))
    assert {"openai", "gemini", "lmstudio", "moonshot", "deepseek"} <= providers


def test_story_mapping_config_accepts_switched_deepseek_role() -> None:
    from src.pipeline.content.story_mapping.contract import PairAdjudicationConfig

    cfg = yaml.safe_load((PROFILES / "daily_48h_all_sources/content/story_mapping.yaml").read_text())
    model = PairAdjudicationConfig.model_validate(cfg["clustering"]["pair_adjudication"])
    # The whale is on deepseek and the contract must accept it.
    assert model.full_record_review is not None
    assert model.full_record_review.provider == "deepseek"


def test_editorial_selection_config_accepts_switched_deepseek_role() -> None:
    from src.pipeline.content.editorial_selection.formats.roundup.contract import SlateReviewConfig

    cfg = yaml.safe_load((PROFILES / "daily_48h_all_sources/content/editorial_selection.yaml").read_text())
    model = SlateReviewConfig.model_validate(cfg["slate_review"])
    assert model.provider == "deepseek"
