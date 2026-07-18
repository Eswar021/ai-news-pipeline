from __future__ import annotations

from typing import Any


def compose_delivery_instructions(
    *,
    base_instructions: str,
    chunk: dict[str, Any],
    provider: str,
    config: dict[str, Any],
) -> str:
    """Translate canonical beat direction into provider instruction text."""

    if not bool(config.get("enabled", True)):
        return base_instructions.strip()
    enabled_providers = {
        str(item).strip()
        for item in config.get("apply_to_providers", [])
        if str(item).strip()
    }
    if enabled_providers and provider not in enabled_providers:
        return base_instructions.strip()

    direction = chunk.get("delivery_direction")
    if not isinstance(direction, dict) or not direction:
        return base_instructions.strip()

    lines = ["Beat-specific performance direction:"]
    field_labels = (
        ("performance_intent", "Intent"),
        ("emotional_color", "Emotional color"),
        ("pace", "Pace"),
        ("energy", "Energy"),
    )
    for field, label in field_labels:
        value = str(direction.get(field) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")

    emphasis = [
        str(item).strip()
        for item in direction.get("emphasis_phrases", [])
        if str(item).strip()
    ]
    if emphasis:
        lines.append(f"- Audible emphasis: {', '.join(emphasis)}")

    pause_after = str(direction.get("pause_after") or "").strip()
    if pause_after and pause_after != "none":
        lines.append(f"- End pause: {pause_after.replace('_', ' ')}")

    if len(lines) == 1:
        return base_instructions.strip()
    return f"{base_instructions.strip()}\n\n" + "\n".join(lines)
