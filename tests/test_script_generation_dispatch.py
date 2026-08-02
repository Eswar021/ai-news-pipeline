"""script_generation format router: selects the writer from the packet's format.

Regression guard for the wiring gap where the orchestrator hardcoded the
roundup writer and rejected every other format's config.
"""
from __future__ import annotations

import pytest

from src.pipeline.content.script_generation import app
from src.pipeline.content.video_packaging.config import SCRIPT_APP_BY_FORMAT


def _packet(selected_format: str) -> dict:
    return {"input": {"video_packaging": {"data": {"selected_format": selected_format}}}}


@pytest.mark.parametrize("selected_format", sorted(SCRIPT_APP_BY_FORMAT))
def test_router_resolves_every_known_format_to_a_callable(selected_format: str) -> None:
    assert app._selected_format(_packet(selected_format)) == selected_format
    run = app._format_run(selected_format)
    assert callable(run)
    # the resolved writer lives under the format's own package
    assert selected_format in run.__module__


def test_router_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="Unknown script_generation format"):
        app._selected_format(_packet("no_such_format"))


def test_router_requires_upstream_packet() -> None:
    with pytest.raises(ValueError, match="requires an upstream video_packaging"):
        app._selected_format({"input": {}})
    with pytest.raises(ValueError, match="missing data.selected_format"):
        app._selected_format({"input": {"video_packaging": {"data": {}}}})


def test_orchestrator_imports_the_router_not_a_hardcoded_format() -> None:
    # The content stage must import the format-agnostic entrypoint so new
    # formats route without touching the orchestrator.
    from src.pipeline.orchestration.stages.content import _module_function

    run = _module_function("script_generation")
    assert run.__module__ == "src.pipeline.content.script_generation.app"
