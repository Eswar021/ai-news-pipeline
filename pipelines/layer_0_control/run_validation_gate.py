"""
Module: run_validation_gate
Layer: 0 — Channel Strategy + Run Control
Purpose: Validate run_manifest.json before Layer 1 starts. Fails fast on bad config.
         A failed validation means the run is aborted — no downstream layer is invoked.
"""

import json
from pathlib import Path

from config.time_utils import now_project_iso


_REQUIRED_TOP_LEVEL_KEYS = [
    "run_id",
    "run_request",
    "channel_strategy",
    "format_strategy",
    "collection_strategy",
    "quality_policy",
    "memory_policy",
    "depth_limits",
    "output_contract",
    "resolved_config",
]

_VALID_FORMATS = {"roundup", "deep_dive", "evergreen", "comparison", "follow_up"}


def validate_manifest(manifest: dict, manifest_path: Path) -> dict:
    """
    Validates the assembled run manifest for completeness and internal consistency.

    Checks:
      1. All required top-level keys are present
      2. eligible_formats is non-empty and contains only known formats
      3. collection_strategy has a valid window and at least one enabled source group
      4. quality_policy has a policy_id
      5. deep_dive eligibility implies primary_source rule is set
      6. output_contract defines run_data_dir and required_layer_outputs
      7. Warns (does not error) if memory files don't exist yet (expected on first run)

    Updates manifest status in-place and writes:
      - run_manifest.json (updated status field)
      - layer0_validation_report.json (separate report file)

    Returns:
        validation_report dict with: validation_status, can_start_layer_1, warnings, errors
    """
    errors = []
    warnings = []

    # 1. Required top-level keys
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in manifest:
            errors.append(f"Missing required manifest key: '{key}'")

    if errors:
        return _finalize(manifest, manifest_path, errors, warnings)

    # 2. eligible_formats
    eligible = manifest.get("format_strategy", {}).get("eligible_formats", [])
    if not eligible:
        errors.append(
            "format_strategy.eligible_formats is empty — "
            "no formats are enabled in format_config.yaml"
        )
    unknown = [f for f in eligible if f not in _VALID_FORMATS]
    if unknown:
        errors.append(f"Unknown format(s) in eligible_formats: {unknown}")

    # 3. Collection strategy
    coll = manifest.get("collection_strategy", {})
    window = coll.get("collection_window", {})
    for field in ("start", "end", "lookback_hours"):
        if field not in window:
            errors.append(f"collection_strategy.collection_window is missing field: '{field}'")

    lookback = window.get("lookback_hours", 0)
    if lookback <= 0:
        errors.append("collection_strategy.collection_window.lookback_hours must be > 0")

    enabled_groups = coll.get("enabled_source_groups", [])
    if not enabled_groups:
        errors.append(
            "collection_strategy.enabled_source_groups is empty — "
            "no source groups have enabled sources"
        )

    # 4. Quality policy
    qp = manifest.get("quality_policy", {})
    if not qp.get("quality_policy_id"):
        errors.append("quality_policy.quality_policy_id is missing")

    # 5. Deep dive → primary source rule
    if "deep_dive" in eligible:
        source_rules = qp.get("source_rules", {})
        if not source_rules.get("require_primary_source_for_deep_dive"):
            warnings.append({
                "type": "deep_dive_policy_gap",
                "message": (
                    "deep_dive is in eligible_formats but "
                    "quality_policy.source_rules.require_primary_source_for_deep_dive is not true."
                ),
            })

    # 6. Output contract
    contract = manifest.get("output_contract", {})
    if not contract.get("run_data_dir"):
        errors.append("output_contract.run_data_dir is missing")
    if not contract.get("required_layer_outputs"):
        errors.append("output_contract.required_layer_outputs is missing or empty")

    # 6A. Resolved runtime config snapshots
    resolved = manifest.get("resolved_config", {})
    required_resolved = [
        "source_registry",
        "youtube_channels",
        "entity_topic_taxonomy",
        "chatgpt_handoff",
        "llm",
        "runtime",
    ]
    for key in required_resolved:
        if key not in resolved:
            errors.append(f"resolved_config.{key} is missing")

    source_registry = resolved.get("source_registry", {})
    if not source_registry.get("sources"):
        errors.append("resolved_config.source_registry.sources is missing or empty")

    if "enabled_channels" not in resolved.get("youtube_channels", {}):
        errors.append("resolved_config.youtube_channels.enabled_channels is missing")

    taxonomy = resolved.get("entity_topic_taxonomy", {})
    if not taxonomy.get("entities") or not taxonomy.get("topics"):
        errors.append("resolved_config.entity_topic_taxonomy is missing entities or topics")

    handoff = resolved.get("chatgpt_handoff", {})
    if not handoff.get("handoff_levels"):
        errors.append("resolved_config.chatgpt_handoff.handoff_levels is missing or empty")

    llm = resolved.get("llm", {})
    if not llm.get("effective_profiles"):
        errors.append("resolved_config.llm.effective_profiles is missing or empty")

    runtime = resolved.get("runtime", {})
    if not runtime.get("timezone_name"):
        errors.append("resolved_config.runtime.timezone_name is missing or empty")

    # 7. Memory files (warn only — expected to be empty on first run)
    memory_paths = manifest.get("memory_paths", {})
    missing_memory = [
        path_str
        for key, path_str in memory_paths.items()
        if not Path(path_str).exists()
    ]
    if missing_memory:
        warnings.append({
            "type": "memory_files_not_yet_created",
            "message": (
                f"{len(missing_memory)} memory file(s) do not exist yet. "
                "This is normal on the first run — they will be created by Layer 10."
            ),
            "files": missing_memory,
        })

    return _finalize(manifest, manifest_path, errors, warnings)


def _finalize(
    manifest: dict,
    manifest_path: Path,
    errors: list,
    warnings: list,
) -> dict:
    passed = len(errors) == 0

    validation_report = {
        "validation_status": "passed" if passed else "failed",
        "can_start_layer_1": passed,
        "warnings": warnings,
        "errors": errors,
        "validated_at": now_project_iso(),
    }

    manifest["status"] = "ready_for_layer_1" if passed else "failed_validation"
    manifest["validation_report"] = validation_report

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    report_path = manifest_path.parent / "layer0_validation_report.json"
    with open(report_path, "w") as f:
        json.dump(validation_report, f, indent=2)

    return validation_report
