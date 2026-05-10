"""
Module: run_mode_resolver
Layer: 0 — Channel Strategy + Run Control
Purpose: Determine run mode and the set of eligible video formats for this run.
"""

from pathlib import Path
from typing import Optional
import yaml

_FORMAT_TO_MODE = {
    "roundup":    "generate_roundup",
    "deep_dive":  "generate_deep_dive",
    "evergreen":  "generate_evergreen",
    "comparison": "generate_comparison",
    "follow_up":  "generate_follow_up",
    "auto":       "auto",
}

VALID_FORMATS = {"auto", "roundup", "deep_dive", "evergreen", "comparison", "follow_up"}


def resolve_run_mode(
    target_format: str,
    format_config_path: Path,
    user_requested_mode: Optional[str] = None,
    max_videos: int = 1,
) -> dict:
    """
    Determines the run mode and which formats are eligible.

    For 'auto': includes all formats marked enabled=true in format_config.yaml.
    For explicit format: validates it is enabled, returns only that format.

    Returns:
        dict with: run_mode, target_format, eligible_formats, max_videos,
        format_decision_stage

    Raises:
        FileNotFoundError: if format_config_path does not exist
        ValueError: if target_format is unknown or explicitly disabled
    """
    if not format_config_path.exists():
        raise FileNotFoundError(f"format_config.yaml not found at: {format_config_path}")

    with open(format_config_path, "r") as f:
        fmt_config = yaml.safe_load(f)

    formats = fmt_config.get("formats", {})

    if target_format not in VALID_FORMATS:
        raise ValueError(f"Unknown format '{target_format}'. Valid: {sorted(VALID_FORMATS)}")

    if target_format == "auto":
        eligible_formats = [
            name for name, cfg in formats.items()
            if cfg.get("enabled", False)
        ]
        run_mode = "auto"
    else:
        if target_format not in formats:
            raise ValueError(f"Format '{target_format}' is not defined in format_config.yaml")
        if not formats[target_format].get("enabled", False):
            raise ValueError(
                f"Format '{target_format}' is disabled in format_config.yaml. "
                f"Set enabled: true to use it."
            )
        eligible_formats = [target_format]
        run_mode = _FORMAT_TO_MODE.get(target_format, "auto")

    if user_requested_mode:
        run_mode = user_requested_mode

    return {
        "run_mode": run_mode,
        "target_format": target_format,
        "eligible_formats": eligible_formats,
        "max_videos": max_videos,
        "format_decision_stage": "layer_5_editorial_router",
    }
