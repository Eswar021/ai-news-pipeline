"""
Module: budget_depth_controller
Layer: 0 — Channel Strategy + Run Control
Purpose: Set processing limits for all downstream layers based on depth profile and format.
         Prevents over-processing: a roundup mention needs far less research than a deep dive.
"""

from pathlib import Path
import yaml


def build_depth_limits(
    target_format: str,
    depth: str,
    max_videos: int,
    run_defaults_path: Path,
) -> dict:
    """
    Returns the depth limits dict for this run, sourced from run_defaults.yaml depth profiles.

    Format-specific overrides are applied after loading the base profile:
    - deep_dive clamps max_stories_for_roundup to 1 (single story)
    - multi-video runs scale the roundup story budget proportionally

    Returns:
        dict with: depth_profile, limits

    Raises:
        FileNotFoundError: if run_defaults_path does not exist
    """
    if not run_defaults_path.exists():
        raise FileNotFoundError(f"run_defaults.yaml not found at: {run_defaults_path}")

    with open(run_defaults_path, "r") as f:
        raw = yaml.safe_load(f)

    depth_profiles = raw.get("depth_profiles", {})

    # Fall back to standard if the requested profile is not defined
    profile = depth_profiles.get(depth) or depth_profiles.get("standard", {})
    limits = dict(profile)

    # Format-specific overrides
    if target_format == "deep_dive":
        limits["max_stories_for_roundup"] = 1
        limits["max_claims_per_story"] = max(limits.get("max_claims_per_story", 20), 20)

    if max_videos > 1:
        story_budget = limits.get("max_stories_for_roundup", 8) * max_videos
        limits["max_stories_for_roundup"] = min(story_budget, 20)

    return {
        "depth_profile": depth,
        "limits": limits,
    }
