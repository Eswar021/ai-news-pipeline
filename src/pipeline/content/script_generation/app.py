"""Format router for the script_generation module.

The orchestrator calls one script_generation entrypoint; the concrete writer is
chosen from the format that the upstream video_packaging module selected. This
mirrors the video_packaging PACKET_BUILDERS dispatch and keeps the orchestrator
and every profile format-agnostic — adding a format only touches the format
package plus ``SCRIPT_APP_BY_FORMAT`` in video_packaging config.
"""
from __future__ import annotations

import importlib
from typing import Any, Callable

from src.pipeline.content.video_packaging.config import SCRIPT_APP_BY_FORMAT


def _selected_format(input_json: dict[str, Any]) -> str:
    try:
        packaging = input_json["input"]["video_packaging"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "script_generation requires an upstream video_packaging result"
        ) from exc
    data = packaging.get("data") if isinstance(packaging, dict) else None
    selected = (data or {}).get("selected_format")
    if not selected:
        raise ValueError("video_packaging result is missing data.selected_format")
    if selected not in SCRIPT_APP_BY_FORMAT:
        raise ValueError(
            f"Unknown script_generation format {selected!r}; "
            f"known formats: {sorted(SCRIPT_APP_BY_FORMAT)}"
        )
    return selected


def _format_run(selected_format: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # SCRIPT_APP_BY_FORMAT values are module paths relative to this package's
    # parent (e.g. "script_generation.formats.deep_dive").
    module_path = f"src.pipeline.content.{SCRIPT_APP_BY_FORMAT[selected_format]}"
    return importlib.import_module(module_path).run


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    return _format_run(_selected_format(input_json))(input_json)
