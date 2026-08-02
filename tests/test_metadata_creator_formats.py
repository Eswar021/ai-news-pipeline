"""metadata_creator is format-aware: it tags outputs with the real format and
picks a per-format prompt, instead of assuming roundup.

Regression for a deep_dive run that failed at metadata_creator with
NotImplementedError ("currently supports only roundup").
"""
from __future__ import annotations

import pytest

from src.pipeline.content.metadata_creator.app import _resolve_supported_format
from src.pipeline.content.metadata_creator.config import (
    METADATA_PROMPT_MODULE_BY_FORMAT,
    SUPPORTED_FORMATS,
)
from src.pipeline.content.metadata_creator.prompt_loader import load_prompt_bundle


@pytest.mark.parametrize("fmt", sorted(SUPPORTED_FORMATS))
def test_resolve_returns_the_matching_supported_format(fmt: str) -> None:
    assert _resolve_supported_format(fmt, fmt, {"selected_format": fmt}) == fmt


def test_resolve_rejects_mismatched_signals() -> None:
    with pytest.raises(ValueError, match="mismatched formats"):
        _resolve_supported_format("roundup", "deep_dive", {"selected_format": "roundup"})


def test_resolve_rejects_unsupported_format() -> None:
    with pytest.raises(NotImplementedError, match="does not support"):
        _resolve_supported_format("shorts", "shorts", {"selected_format": "shorts"})


def test_every_supported_format_has_a_loadable_prompt() -> None:
    for fmt in SUPPORTED_FORMATS:
        assert fmt in METADATA_PROMPT_MODULE_BY_FORMAT
        bundle = load_prompt_bundle(METADATA_PROMPT_MODULE_BY_FORMAT[fmt], "v1")
        assert bundle.get("system") and bundle.get("user_preamble")
