"""
Module: format_strategy_resolver
Layer: 0 — Channel Strategy + Run Control
Purpose: Load format requirements for all eligible formats and pass them into the run manifest.
"""

from pathlib import Path
import yaml


def resolve_format_strategy(
    format_config_path: Path,
    eligible_formats: list,
) -> dict:
    """
    Loads requirements for each eligible format from format_config.yaml.

    The final format selection happens in Layer 5 (editorial router) after story ranking.
    Layer 0 only defines what formats are *allowed* and what each one requires.

    Returns:
        dict with: eligible_formats, format_requirements (per-format specs),
        format_decision_stage, routing_rules

    Raises:
        FileNotFoundError: if format_config_path does not exist
    """
    if not format_config_path.exists():
        raise FileNotFoundError(f"format_config.yaml not found at: {format_config_path}")

    with open(format_config_path, "r") as f:
        raw = yaml.safe_load(f)

    formats = raw.get("formats", {})
    routing_rules = raw.get("format_routing_rules", {})

    format_requirements = {}
    for fmt_name in eligible_formats:
        if fmt_name not in formats:
            continue
        spec = dict(formats[fmt_name])
        # Remove the 'enabled' flag — it's a config-level gate, not a downstream contract
        spec.pop("enabled", None)
        spec.pop("description", None)
        format_requirements[fmt_name] = spec

    return {
        "eligible_formats": eligible_formats,
        "format_requirements": format_requirements,
        "format_decision_stage": "layer_5_editorial_router",
        "routing_rules": routing_rules,
    }
