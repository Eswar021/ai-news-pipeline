"""
Shared helpers for reading run-scoped config from Layer 0's run_manifest.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from config.paths import RUNS_DIR


def load_manifest(run_id: str | None = None, manifest_path: Path | None = None) -> dict:
    if manifest_path is None:
        if not run_id:
            raise ValueError("load_manifest requires run_id or manifest_path")
        manifest_path = RUNS_DIR / run_id / "run_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"run_manifest.json not found at {manifest_path}")

    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to parse run manifest at {manifest_path}: {exc}") from exc


def _resolved_config(manifest: dict) -> dict:
    resolved = manifest.get("resolved_config")
    if not isinstance(resolved, dict) or not resolved:
        raise KeyError(
            "run_manifest.json is missing required 'resolved_config'. "
            "Rebuild the run from Layer 0 so downstream runtime can use manifest snapshots only."
        )
    return resolved


def get_format_requirements(manifest: dict) -> dict:
    requirements = manifest.get("format_strategy", {}).get("format_requirements", {})
    if requirements:
        return requirements
    raise KeyError("run_manifest.json is missing format_strategy.format_requirements")


def get_run_profile(manifest: dict) -> dict:
    profile = manifest.get("run_profile", {})
    if not isinstance(profile, dict) or not profile.get("profile_name"):
        raise KeyError("run_manifest.json is missing run_profile.profile_name")
    return profile


def get_decision_mode(manifest: dict) -> str:
    return get_run_profile(manifest).get("decision_mode", "auto_route")


def get_collection_caps(manifest: dict) -> dict:
    caps = manifest.get("collection_strategy", {}).get("collector_caps", {})
    if not isinstance(caps, dict):
        raise KeyError("run_manifest.json is missing collection_strategy.collector_caps")
    return caps


def get_layer_limits(manifest: dict, layer_name: str | None = None) -> dict:
    limits = manifest.get("execution_policy", {}).get("layer_limits", {})
    if not isinstance(limits, dict):
        raise KeyError("run_manifest.json is missing execution_policy.layer_limits")
    if layer_name is None:
        return limits
    layer_limits = limits.get(layer_name, {})
    if not isinstance(layer_limits, dict):
        raise KeyError(f"run_manifest.json is missing execution_policy.layer_limits.{layer_name}")
    return layer_limits


def get_source_registry_snapshot(manifest: dict) -> dict:
    snapshot = _resolved_config(manifest).get("source_registry", {})
    if not isinstance(snapshot, dict) or not snapshot.get("sources"):
        raise KeyError("run_manifest.json is missing resolved_config.source_registry.sources")
    return snapshot


def get_youtube_registry_snapshot(manifest: dict) -> dict:
    snapshot = _resolved_config(manifest).get("youtube_channels", {})
    if not isinstance(snapshot, dict) or "enabled_channels" not in snapshot:
        raise KeyError("run_manifest.json is missing resolved_config.youtube_channels")
    return snapshot


def get_entity_topic_taxonomy(manifest: dict) -> dict:
    taxonomy = _resolved_config(manifest).get("entity_topic_taxonomy")
    if taxonomy:
        return taxonomy
    raise KeyError("run_manifest.json is missing resolved_config.entity_topic_taxonomy")


def get_handoff_prompt_config(manifest: dict) -> dict:
    prompt_cfg = _resolved_config(manifest).get("chatgpt_handoff")
    if prompt_cfg:
        return prompt_cfg
    raise KeyError("run_manifest.json is missing resolved_config.chatgpt_handoff")


def get_prompt_runtime_snapshot(manifest: dict) -> dict:
    snapshot = _resolved_config(manifest).get("prompts", {})
    if not isinstance(snapshot, dict) or not snapshot.get("modules"):
        raise KeyError("run_manifest.json is missing resolved_config.prompts.modules")
    return snapshot


def get_llm_runtime_snapshot(manifest: dict) -> dict:
    snapshot = _resolved_config(manifest).get("llm", {})
    if not isinstance(snapshot, dict) or not snapshot.get("effective_profiles"):
        raise KeyError("run_manifest.json is missing resolved_config.llm.effective_profiles")
    return snapshot


def get_runtime_settings(manifest: dict) -> dict:
    settings = _resolved_config(manifest).get("runtime", {})
    if not isinstance(settings, dict) or not settings.get("timezone_name"):
        raise KeyError("run_manifest.json is missing resolved_config.runtime.timezone_name")
    return settings


def get_runtime_timezone_name(manifest: dict) -> str:
    return get_runtime_settings(manifest)["timezone_name"]


def get_llm_profile(module_name: str, run_id: str | None = None, manifest: dict | None = None) -> dict:
    manifest = manifest or load_manifest(run_id=run_id)
    llm_snapshot = get_llm_runtime_snapshot(manifest)
    effective = llm_snapshot.get("effective_profiles", {})

    if module_name in effective:
        return dict(effective[module_name])
    if "default" in effective:
        return dict(effective["default"])
    raise KeyError(
        f"run_manifest.json resolved_config.llm.effective_profiles is missing module '{module_name}' "
        "and has no default profile."
    )
