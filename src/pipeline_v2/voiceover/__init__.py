"""Pipeline v2 voiceover media-generation module."""

from typing import Any


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    from .app import run as _run

    return _run(input_json)

__all__ = ["run"]
