"""
Module: source_scope_planner
Layer: 0 — Channel Strategy + Run Control
Purpose: Build the source collection plan for Layer 1 — which groups to collect from,
         in what priority order, with what query themes.
"""

from pathlib import Path
import yaml


def plan_source_scope(
    sources_path: Path,
    source_strategy_path: Path,
    topic_focus: str,
    target_format: str = "auto",
) -> dict:
    """
    Determines which source groups Layer 1 should collect from.

    Cross-references:
      - source_strategy.yaml: group definitions and format requirements
      - sources.yaml: per-source enabled flags (a group is active if ≥1 source is enabled)

    Returns:
        dict with: source_collection_plan (enabled groups, priority, query themes),
        source_group_details (trust tier, role, active source IDs per group)

    Raises:
        FileNotFoundError: if either config file is missing
    """
    if not sources_path.exists():
        raise FileNotFoundError(f"sources.yaml not found at: {sources_path}")
    if not source_strategy_path.exists():
        raise FileNotFoundError(f"source_strategy.yaml not found at: {source_strategy_path}")

    with open(sources_path, "r") as f:
        sources_config = yaml.safe_load(f)

    with open(source_strategy_path, "r") as f:
        strategy = yaml.safe_load(f)

    # Build set of enabled source IDs from sources.yaml
    enabled_source_ids = {
        s["id"]
        for s in sources_config.get("sources", [])
        if s.get("enabled", False)
    }

    source_groups = strategy.get("source_groups", {})
    format_reqs = strategy.get("format_source_requirements", {})

    # Use format-specific requirements, fall back to "auto"
    fmt_key = target_format if target_format in format_reqs else "auto"
    requirements = format_reqs.get(fmt_key, format_reqs.get("auto", {}))

    priority_order = requirements.get("priority_order", list(source_groups.keys()))

    # A group is enabled if at least one of its sources is enabled in sources.yaml
    enabled_groups = []
    source_group_details = {}

    for group_name in priority_order:
        group_cfg = source_groups.get(group_name, {})
        group_source_ids = group_cfg.get("source_ids", [])
        active_ids = [sid for sid in group_source_ids if sid in enabled_source_ids]

        if active_ids:
            enabled_groups.append(group_name)
            source_group_details[group_name] = {
                "trust_tier": group_cfg.get("trust_tier"),
                "role": group_cfg.get("role", "evidence"),
                "active_source_ids": active_ids,
            }

    required_groups = requirements.get("required_groups", [])
    priority_source_groups = [g for g in enabled_groups if g in required_groups]

    query_themes = strategy.get("query_themes", {}).get("default", [])

    return {
        "source_collection_plan": {
            "enabled_source_groups": enabled_groups,
            "priority_source_groups": priority_source_groups,
            "query_themes": query_themes,
            "minimum_expected_documents": 30,
            "maximum_expected_documents": 500,
        },
        "source_group_details": source_group_details,
    }
