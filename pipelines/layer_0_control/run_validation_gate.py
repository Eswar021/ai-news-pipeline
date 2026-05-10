"""
Module: run_validation_gate
Layer: 0 — Channel Strategy + Run Control
Purpose: Validate run_manifest.json before Layer 1 starts. Fails fast on bad config.
         A failed validation means the run is aborted — no downstream layer is invoked.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


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
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }

    manifest["status"] = "ready_for_layer_1" if passed else "failed_validation"
    manifest["validation_report"] = validation_report

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    report_path = manifest_path.parent / "layer0_validation_report.json"
    with open(report_path, "w") as f:
        json.dump(validation_report, f, indent=2)

    return validation_report
