"""
Module: source_registry_loader
Layer: 1 — Source Extraction
Purpose: Load sources.yaml + source_strategy.yaml and return the active source list
         for the enabled source groups specified by the run manifest.

Each returned source dict includes its group membership, trust tier, and collector name
so the orchestrator can route it to the right collector without reading any config files.

Run standalone:
    python source_registry_loader.py
    python source_registry_loader.py --groups ai_company_blogs research_papers
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml
from config.paths import SOURCES_YAML, SOURCE_STRATEGY_YAML

# Maps module field in sources.yaml → design-doc collector name
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


def load_active_sources(
    sources_path: Path,
    source_strategy_path: Path,
    enabled_groups: list = None,
) -> list:
    """
    Return active source configs for the given enabled source groups.

    If enabled_groups is None, returns all enabled sources across all groups.

    Each returned dict has:
        source_id, source_name, source_group, source_group_role,
        collector, extraction_type, url, trust_tier_hint, priority, enabled
    """
    with open(sources_path) as f:
        sources_config = yaml.safe_load(f)

    with open(source_strategy_path) as f:
        strategy = yaml.safe_load(f)

    # Build a lookup: source_id → source config from sources.yaml
    source_lookup = {
        s["id"]: s
        for s in sources_config.get("sources", [])
    }

    # Build group membership from source_strategy.yaml
    group_configs = strategy.get("source_groups", {})

    active = []
    for group_name, group_cfg in group_configs.items():
        if enabled_groups is not None and group_name not in enabled_groups:
            continue

        for source_id in group_cfg.get("source_ids", []):
            src = source_lookup.get(source_id)
            if not src:
                continue
            if not src.get("enabled", False):
                continue

            collector = _MODULE_TO_COLLECTOR.get(src.get("module", ""), src.get("module", "unknown"))

            active.append({
                "source_id":         source_id,
                "source_name":       src.get("name", source_id),
                "source_group":      group_name,
                "source_group_role": group_cfg.get("role", "evidence"),
                "collector":         collector,
                "extraction_type":   src.get("extraction_type", "unknown"),
                "url":               src.get("url", ""),
                "trust_tier_hint":   src.get("trust_tier", group_cfg.get("trust_tier", 3)),
                "priority":          src.get("priority", "medium"),
                "categories":        src.get("categories", []),
                "env_key":           src.get("env_key", ""),
            })

    return active


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load active sources from registry")
    parser.add_argument(
        "--groups", nargs="*",
        default=None,
        help="Filter to specific source groups (default: all)"
    )
    args = parser.parse_args()

    sources = load_active_sources(SOURCES_YAML, SOURCE_STRATEGY_YAML, enabled_groups=args.groups)

    print(f"\nActive sources ({len(sources)} total):\n")
    current_group = None
    for s in sources:
        if s["source_group"] != current_group:
            current_group = s["source_group"]
            print(f"\n  [{current_group}]")
        print(f"    {s['source_id']:30s}  tier={s['trust_tier_hint']}  collector={s['collector']}")

    print(f"\nTotal: {len(sources)} sources across {len(set(s['source_group'] for s in sources))} groups")
