"""
Module: resolved_config_snapshot_builder
Layer: 0 — Channel Strategy + Run Control
Purpose: Build run-scoped snapshots of authoring config so downstream runtime
         behavior can read the run manifest instead of live config files.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from config import llm_config
from config.time_utils import get_project_timezone_name


_MODULE_TO_COLLECTOR = {
    "blog_collector":       "official_company_blog_collector",
    "arxiv_collector":      "research_paper_collector",
    "newsapi_collector":    "tech_news_api_collector",
    "newsdata_collector":   "tech_news_api_collector",
    "mediastack_collector": "tech_news_api_collector",
    "hackernews_collector": "community_signal_collector",
    "github_collector":     "github_open_source_collector",
    "reddit_collector":     "community_signal_collector",
    "youtube_collector":    "youtube_podcast_collector",
}

_ACTIVE_LLM_MODULES = [
    "claim_extractor",
    "viewer_value_analyzer",
    "editorial_brief_builder",
    "hook_planner",
    "title_thumbnail_planner",
    "roundup_script_writer",
    "deep_dive_script_writer",
    "sentence_support_verifier",
]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _build_source_registry_snapshot(
    sources_path: Path,
    source_strategy_path: Path,
    enabled_groups: list[str],
    source_group_details: dict,
) -> dict:
    sources_config = _load_yaml(sources_path)
    strategy = _load_yaml(source_strategy_path)

    source_lookup = {s["id"]: s for s in sources_config.get("sources", [])}
    group_configs = strategy.get("source_groups", {})

    active_sources = []
    for group_name in enabled_groups:
        group_cfg = group_configs.get(group_name, {})
        detail = source_group_details.get(group_name, {})
        active_source_ids = detail.get("active_source_ids", group_cfg.get("source_ids", []))

        for source_id in active_source_ids:
            src = source_lookup.get(source_id)
            if not src:
                continue
            collector = _MODULE_TO_COLLECTOR.get(src.get("module", ""), src.get("module", "unknown"))
            active_sources.append({
                "source_id":         source_id,
                "source_name":       src.get("name", source_id),
                "source_group":      group_name,
                "source_group_role": detail.get("role", group_cfg.get("role", "evidence")),
                "collector":         collector,
                "extraction_type":   src.get("extraction_type", "unknown"),
                "url":               src.get("url", ""),
                "trust_tier_hint":   src.get("trust_tier", detail.get("trust_tier", group_cfg.get("trust_tier", 3))),
                "priority":          src.get("priority", "medium"),
                "categories":        src.get("categories", []),
                "env_key":           src.get("env_key", ""),
                "fetch_frequency":   src.get("fetch_frequency", ""),
            })

    return {
        "groups": source_group_details,
        "sources": active_sources,
        "source_count": len(active_sources),
    }


def _build_youtube_channels_snapshot(channels_path: Path, youtube_enabled: bool) -> dict:
    cfg = _load_yaml(channels_path)
    yt_cfg = cfg.get("youtube", {})
    channels = yt_cfg.get("channels", []) or []
    enabled_channels = [ch for ch in channels if ch.get("enabled", True)] if youtube_enabled else []
    return {
        "defaults": {
            "days_back": yt_cfg.get("days_back", 7),
            "max_per_duration": yt_cfg.get("max_per_duration", 3),
        },
        "enabled_channels": enabled_channels,
        "channel_count": len(enabled_channels),
    }


def _build_llm_snapshot() -> dict:
    effective_profiles = {
        "default": dict(llm_config.get_active_profile()),
    }
    for module_name in _ACTIVE_LLM_MODULES:
        effective_profiles[module_name] = dict(llm_config.get_profile(module_name))

    return {
        "active_profile_name": llm_config.ACTIVE_PROFILE,
        "active_profile": dict(llm_config.get_active_profile()),
        "module_overrides": dict(llm_config.MODULE_OVERRIDES),
        "profile_catalog": {name: dict(profile) for name, profile in llm_config.LLM_PROFILES.items()},
        "effective_profiles": effective_profiles,
    }


def build_resolved_config_snapshots(
    *,
    sources_path: Path,
    source_strategy_path: Path,
    channels_path: Path,
    run_defaults_path: Path,
    entity_topic_taxonomy_path: Path,
    chatgpt_prompts_path: Path,
    enabled_source_groups: list[str],
    source_group_details: dict,
) -> dict:
    return {
        "source_registry": _build_source_registry_snapshot(
            sources_path=sources_path,
            source_strategy_path=source_strategy_path,
            enabled_groups=enabled_source_groups,
            source_group_details=source_group_details,
        ),
        "youtube_channels": _build_youtube_channels_snapshot(
            channels_path=channels_path,
            youtube_enabled="youtube_podcast_transcripts" in enabled_source_groups,
        ),
        "entity_topic_taxonomy": _load_yaml(entity_topic_taxonomy_path),
        "chatgpt_handoff": _load_yaml(chatgpt_prompts_path),
        "llm": _build_llm_snapshot(),
        "runtime": {
            "timezone_name": get_project_timezone_name(),
            "run_defaults_snapshot": _load_yaml(run_defaults_path),
        },
    }
