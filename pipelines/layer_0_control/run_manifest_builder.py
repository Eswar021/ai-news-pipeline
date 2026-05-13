"""
Module: run_manifest_builder
Layer: 0 — Channel Strategy + Run Control
Purpose: Merge all Layer 0 module outputs into run_manifest.json and write it to disk.
         This is the single control document that every downstream layer reads.
"""

import json
from pathlib import Path

from config.time_utils import now_project_iso


_SCHEMA_VERSION = "1.3"


def build_run_manifest(
    run_request: dict,
    run_profile: dict,
    channel_strategy: dict,
    audience_strategy: dict,
    run_mode: dict,
    time_window: dict,
    format_strategy: dict,
    source_scope: dict,
    quality_policy: dict,
    memory_context: dict,
    depth_limits: dict,
    output_contract: dict,
    resolved_config: dict,
    runs_dir: Path,
) -> tuple:
    """
    Assembles the full run manifest from all Layer 0 module outputs and writes it to disk.

    Also writes run_config_snapshot.json (records raw module outputs for auditability).

    Returns:
        (manifest dict, manifest_path Path)
    """
    run_id = run_request["run_id"]
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": run_id,
        "schema_version": _SCHEMA_VERSION,
        "created_at": now_project_iso(),
        "status": "pending_validation",

        "run_request": run_request,

        "run_profile": {
            "profile_name": run_profile["profile_name"],
            "description": run_profile["description"],
            "target_format": run_profile["target_format"],
            "decision_mode": run_profile["decision_mode"],
            "allowed_formats": run_profile["allowed_formats"],
            "lookback_hours": run_profile["lookback_hours"],
            "depth": run_profile["depth"],
            "max_videos": run_profile["max_videos"],
            "collection_caps": run_profile.get("collection_caps", {}),
            "layer_limits": run_profile.get("layer_limits", {}),
            "operational_overrides": run_profile.get("operational_overrides", {}),
            "resolution_notes": run_profile.get("resolution_notes", []),
        },

        "channel_strategy": {
            "channel_thesis_id": channel_strategy["channel_thesis_id"],
            "channel_name": channel_strategy["channel_name"],
            "content_promise": channel_strategy["content_promise"],
            "tone": channel_strategy["tone"],
            "allowed_topics": channel_strategy["allowed_topics"],
            "excluded_topics": channel_strategy["excluded_topics"],
            "style_rules": channel_strategy["style_rules"],
            "preferred_angles": channel_strategy["preferred_angles"],
        },

        "audience_strategy": {
            "audience_profile_id": audience_strategy["audience_profile_id"],
            "name": audience_strategy["name"],
            "explanation_depth": audience_strategy["explanation_depth"],
            "jargon_allowed": audience_strategy["jargon_allowed"],
            "script_guidance": audience_strategy["script_guidance"],
        },

        "format_strategy": {
            "run_mode": run_mode["run_mode"],
            "decision_mode": run_mode.get("decision_mode"),
            "eligible_formats": run_mode["eligible_formats"],
            "format_decision_stage": run_mode["format_decision_stage"],
            "format_requirements": format_strategy["format_requirements"],
            "routing_rules": format_strategy["routing_rules"],
        },

        "collection_strategy": {
            "collection_window": time_window["collection_window"],
            "source_specific_windows": time_window["source_specific_windows"],
            "enabled_source_groups": source_scope["source_collection_plan"]["enabled_source_groups"],
            "priority_source_groups": source_scope["source_collection_plan"]["priority_source_groups"],
            "query_themes": source_scope["source_collection_plan"]["query_themes"],
            "query_theme_set": source_scope["source_collection_plan"].get("query_theme_set"),
            "profile_name": run_profile["profile_name"],
            "collector_caps": run_profile.get("collection_caps", {}),
            "collection_limits": {
                "minimum_expected_documents": source_scope["source_collection_plan"]["minimum_expected_documents"],
                "maximum_expected_documents": source_scope["source_collection_plan"]["maximum_expected_documents"],
            },
            "source_group_details": source_scope["source_group_details"],
        },

        "execution_policy": {
            "layer_limits": run_profile.get("layer_limits", {}),
        },

        "quality_policy": quality_policy,

        "memory_policy": memory_context["memory_policy"],
        "memory_windows": memory_context["memory_windows"],
        "memory_paths": memory_context["memory_paths"],

        "depth_limits": depth_limits,

        "output_contract": output_contract["output_contract"],
        "resolved_config": resolved_config,

        "validation_report": {
            "validation_status": "pending",
            "can_start_layer_1": False,
            "warnings": [],
            "errors": [],
        },
    }

    manifest_path = run_dir / "run_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    # Config snapshot — raw module outputs for auditability
    snapshot = {
        "run_id": run_id,
        "snapshotted_at": manifest["created_at"],
        "run_request": run_request,
        "run_profile_raw": run_profile,
        "channel_strategy_raw": channel_strategy,
        "audience_strategy_raw": audience_strategy,
        "run_mode_raw": run_mode,
        "time_window_raw": time_window,
        "format_strategy_raw": format_strategy,
        "source_scope_raw": source_scope,
        "quality_policy_raw": quality_policy,
        "memory_context_raw": memory_context,
        "depth_limits_raw": depth_limits,
        "output_contract_raw": output_contract,
        "resolved_config_raw": resolved_config,
    }
    snapshot_path = run_dir / "run_config_snapshot.json"
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)

    return manifest, manifest_path
