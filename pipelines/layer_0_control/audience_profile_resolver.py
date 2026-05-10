"""
Module: audience_profile_resolver
Layer: 0 — Channel Strategy + Run Control
Purpose: Resolve the active audience profile from audience_profiles.yaml for this run.
"""

from pathlib import Path
from typing import Optional
import yaml

_DEFAULT_SCRIPT_GUIDANCE = {
    "define_terms": True,
    "use_analogies": True,
    "include_business_impact": True,
    "include_code_level_detail": False,
}


def resolve_audience_profile(
    profiles_path: Path,
    default_audience_id: str,
    requested_audience_id: Optional[str] = None,
) -> dict:
    """
    Selects and returns the active audience profile.

    Resolution order:
      1. requested_audience_id (explicit override)
      2. default_audience_id (from channel thesis)
      3. active_profile from the YAML file
      4. First profile in the file

    Returns:
        dict with: audience_profile_id, name, explanation_depth, jargon_allowed,
        preferred_examples, avoid, script_guidance

    Raises:
        FileNotFoundError: if profiles_path does not exist
        ValueError: if no valid profile can be resolved
    """
    if not profiles_path.exists():
        raise FileNotFoundError(f"audience_profiles.yaml not found at: {profiles_path}")

    with open(profiles_path, "r") as f:
        raw = yaml.safe_load(f)

    profiles = raw.get("profiles", {})
    if not profiles:
        raise ValueError(f"audience_profiles.yaml has no profiles defined: {profiles_path}")

    # Resolution order
    audience_id = requested_audience_id or default_audience_id
    if audience_id not in profiles:
        audience_id = raw.get("active_profile")
    if audience_id not in profiles:
        audience_id = next(iter(profiles))

    profile = profiles[audience_id]

    return {
        "audience_profile_id": audience_id,
        "name": profile.get("name", audience_id),
        "explanation_depth": profile.get("explanation_depth", "medium"),
        "jargon_allowed": profile.get("jargon_allowed", "limited"),
        "preferred_examples": profile.get("preferred_examples", []),
        "avoid": profile.get("avoid", []),
        "script_guidance": profile.get("script_guidance", _DEFAULT_SCRIPT_GUIDANCE),
    }
