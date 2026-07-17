from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SUPPORTED_TEMPLATE_KEYS = frozenset(
    {"PROJECT_ROOT", "OUTPUT_ROOT", "CACHE_ROOT", "RUN_ID"}
)


def render_config_templates(value: Any, context: Mapping[str, Any]) -> Any:
    """Resolve known runtime tokens without interpreting descriptive braces."""

    unknown_keys = set(context) - SUPPORTED_TEMPLATE_KEYS
    if unknown_keys:
        raise ValueError(f"Unsupported config template keys: {sorted(unknown_keys)}")
    replacements = {key: str(item) for key, item in context.items()}
    return _render(value, replacements)


def _render(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, replacement in replacements.items():
            rendered = rendered.replace(f"{{{key}}}", replacement)
        unresolved = [
            key
            for key in SUPPORTED_TEMPLATE_KEYS
            if f"{{{key}}}" in rendered
        ]
        if unresolved:
            raise KeyError(f"Missing config template values: {sorted(unresolved)}")
        return rendered
    if isinstance(value, list):
        return [_render(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, replacements) for key, item in value.items()}
    return value
