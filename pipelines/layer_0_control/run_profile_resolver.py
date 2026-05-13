"""
Module: run_profile_resolver
Layer: 0 — Channel Strategy + Run Control
Purpose: Resolve a named run profile into the effective run policy for this run.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"run_profiles.yaml not found at: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _resolve_profile_name(
    *,
    requested_profile: str | None,
    requested_target_format: str | None,
    requested_lookback_hours: int | None,
    catalog: dict,
) -> tuple[str, list[str]]:
    defaults = catalog.get("defaults", {})
    aliases = defaults.get("profile_aliases", {}) or {}
    profiles = catalog.get("profiles", {}) or {}
    notes: list[str] = []

    if requested_profile:
        profile_name = aliases.get(requested_profile, requested_profile)
        if profile_name not in profiles:
            raise ValueError(
                f"Unknown run profile '{requested_profile}'. "
                f"Available profiles: {sorted(profiles)}"
            )
        if profile_name != requested_profile:
            notes.append(f"Alias '{requested_profile}' resolved to profile '{profile_name}'.")
        return profile_name, notes

    if requested_target_format or requested_lookback_hours:
        candidates = []
        for name, profile in profiles.items():
            if requested_target_format and profile.get("target_format") != requested_target_format:
                continue
            if requested_lookback_hours is not None and int(profile.get("lookback_hours", -1)) != int(requested_lookback_hours):
                continue
            candidates.append(name)

        if len(candidates) == 1:
            notes.append(
                f"Inferred profile '{candidates[0]}' from target_format={requested_target_format!r} "
                f"and lookback_hours={requested_lookback_hours!r}."
            )
            return candidates[0], notes

        if len(candidates) > 1:
            alias_target = requested_target_format or "auto"
            aliased = aliases.get(alias_target)
            if aliased in candidates:
                notes.append(
                    f"Multiple profiles matched; selected alias-backed default '{aliased}' "
                    f"for target_format={alias_target!r}."
                )
                return aliased, notes
            raise ValueError(
                "Multiple run profiles match the requested selectors. "
                f"Pass --run-profile explicitly. Matches: {sorted(candidates)}"
            )

        if requested_target_format:
            aliased = aliases.get(requested_target_format)
            if aliased and aliased in profiles:
                notes.append(
                    f"No exact profile matched lookback={requested_lookback_hours!r}; "
                    f"selected alias-backed profile '{aliased}' for format '{requested_target_format}'."
                )
                return aliased, notes

        raise ValueError(
            "No run profile matches the requested selectors. "
            f"target_format={requested_target_format!r}, lookback_hours={requested_lookback_hours!r}"
        )

    default_profile = defaults.get("default_profile")
    if not default_profile or default_profile not in profiles:
        raise ValueError("run_profiles.yaml is missing defaults.default_profile")
    notes.append(f"Selected default run profile '{default_profile}'.")
    return default_profile, notes


def resolve_run_profile(
    *,
    run_profiles_path: Path,
    requested_profile: str | None = None,
    requested_target_format: str | None = None,
    requested_lookback_hours: int | None = None,
    requested_depth: str | None = None,
    requested_max_videos: int | None = None,
) -> dict:
    """
    Resolve the effective run profile for this run.

    Core collection/editorial policy comes only from the selected profile.
    Depth and max_videos may still be explicitly overridden as operational knobs.
    """
    catalog = _load_yaml(run_profiles_path)
    profiles = catalog.get("profiles", {}) or {}

    profile_name, resolution_notes = _resolve_profile_name(
        requested_profile=requested_profile,
        requested_target_format=requested_target_format,
        requested_lookback_hours=requested_lookback_hours,
        catalog=catalog,
    )
    profile = dict(profiles[profile_name])

    if requested_profile:
        if requested_target_format and profile.get("target_format") != requested_target_format:
            raise ValueError(
                f"Run profile '{profile_name}' targets format {profile.get('target_format')!r}, "
                f"but target_format={requested_target_format!r} was also requested."
            )
        if requested_lookback_hours is not None and int(profile.get("lookback_hours", 0)) != int(requested_lookback_hours):
            raise ValueError(
                f"Run profile '{profile_name}' uses lookback_hours={profile.get('lookback_hours')}, "
                f"but lookback_hours={requested_lookback_hours!r} was also requested."
            )

    depth = requested_depth or profile.get("depth", "standard")
    max_videos = requested_max_videos or int(profile.get("max_videos", 1))

    operational_overrides = {}
    if requested_depth and requested_depth != profile.get("depth"):
        operational_overrides["depth"] = requested_depth
        resolution_notes.append(
            f"Operational override applied: depth={requested_depth!r} "
            f"(profile default was {profile.get('depth')!r})."
        )
    if requested_max_videos and int(requested_max_videos) != int(profile.get("max_videos", 1)):
        operational_overrides["max_videos"] = int(requested_max_videos)
        resolution_notes.append(
            f"Operational override applied: max_videos={requested_max_videos!r} "
            f"(profile default was {profile.get('max_videos')!r})."
        )

    return {
        "profile_name": profile_name,
        "description": profile.get("description", ""),
        "target_format": profile.get("target_format", "auto"),
        "decision_mode": profile.get("decision_mode", "auto_route"),
        "allowed_formats": list(profile.get("allowed_formats", [])),
        "lookback_hours": int(profile.get("lookback_hours", 48)),
        "depth": depth,
        "max_videos": max_videos,
        "source_plan": dict(profile.get("source_plan", {})),
        "collection_windows": dict(profile.get("collection_windows", {})),
        "youtube": dict(profile.get("youtube", {})),
        "collection_caps": dict(profile.get("collection_caps", {})),
        "layer_limits": dict(profile.get("layer_limits", {})),
        "memory_windows": dict(profile.get("memory_windows", {})),
        "operational_overrides": operational_overrides,
        "resolution_notes": resolution_notes,
    }
