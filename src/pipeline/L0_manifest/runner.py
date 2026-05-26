"""
L0 Manifest — resolve layer-wise config into one run_manifest.json for the run.

Reads:
    src/config/l0_config.yaml                 → layer_0 config
    src/config/l1_config.yaml                 → layer_1 authoring config
    src/config/l3_config.yaml                 → layer_3 authoring config
    src/config/l4_config.yaml                 → layer_4 authoring config
    src/config/l5_config.yaml                 → layer_5 authoring config
    src/config/l7_config.yaml                 → layer_7 authoring config
    src/config/l8_config.yaml                 → layer_8 authoring config

Writes:
    output/{run_id}/run_manifest.json         → runtime contract consumed by L1
    output/{run_id}/summary.json              → manifest summary and counts
    output/current_manifest.json              → latest-run convenience copy

LLM: no

Module execution order:
    1. load l0 + l1 config
    2. resolve run profile and collection window
    3. resolve layer_1 collectors
    4. write manifest and summary

Usage:
    python -m src.pipeline.L0_manifest.runner --run-profile daily_48h_all_sources
    python -m src.pipeline.L0_manifest.runner --run-profile daily_48h_all_sources --date YYYY-MM-DD
    python -m src.pipeline.L0_manifest.runner --run-profile daily_48h_all_sources --script-style general_youtube
"""

import argparse
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path

import yaml

from src.config.paths import (
    CURRENT_MANIFEST_PATH,
    L0_CONFIG_PATH,
    L1_CONFIG_PATH,
    L3_CONFIG_PATH,
    L4_CONFIG_PATH,
    L5_CONFIG_PATH,
    L7_CONFIG_PATH,
    L8_CONFIG_PATH,
    OUTPUT_DIR,
    REBUILD_MEMORY_PATH,
)


IST = timezone(timedelta(hours=5, minutes=30))


def run(
    run_profile: str,
    run_date: str | None = None,
    trigger_type: str = "manual",
    script_style: str | None = None,
) -> Path:
    print(f"[L0] Building manifest for profile: {run_profile}")
    l0_cfg = _load_l0_config()
    l1_cfg = _load_l1_config()
    l3_cfg = _load_l3_config()
    l4_cfg = _load_l4_config()
    l5_cfg = _load_l5_config()
    l7_authoring_cfg = _load_l7_config()
    l8_cfg = _load_l8_config()

    run_identity = _build_run_identity(run_profile, run_date)
    profile = _resolve_profile(l0_cfg, run_profile)
    l7_cfg = _resolve_layer7_config(l7_authoring_cfg, profile=profile, script_style=script_style)
    print(f"[L0] Run ID: {run_identity['run_id']}")
    print(f"[L0] Script style: {l7_cfg['script_style']}")

    channel_cfg = dict(l0_cfg["channel"])
    query_themes = _filter_query_themes(
        themes=list(profile["query_themes"]),
        excluded_topics=list(channel_cfg.get("excluded_topics", [])),
    )
    if not query_themes:
        raise RuntimeError("All query themes were filtered out by excluded topics")

    window = _resolve_collection_window(profile, created_at=run_identity["window_end"])
    layer1_resolution = _resolve_collectors(profile, l1_cfg, window, query_themes, channel_cfg)
    layer1_resolution["query_themes"] = query_themes
    print(
        f"[L0] Source groups: {len(layer1_resolution['enabled_source_groups'])}  "
        f"Themes: {len(query_themes)}  Window: {window['lookback_hours']}h"
    )

    memory_context = _build_memory_context()

    manifest = _build_manifest(
        run_identity=run_identity,
        profile_name=run_profile,
        trigger_type=trigger_type,
        channel_cfg=channel_cfg,
        window=window,
        layer1_resolution=layer1_resolution,
        layer3_cfg=l3_cfg,
        layer4_cfg=l4_cfg,
        layer5_cfg=l5_cfg,
        layer7_cfg=l7_cfg,
        layer8_cfg=l8_cfg,
        memory_context=memory_context,
    )
    summary = _build_summary(manifest)

    out_dir = OUTPUT_DIR / manifest["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = out_dir / "run_manifest.json"
    summary_path = out_dir / "summary.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    CURRENT_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    CURRENT_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[L0] Wrote: {manifest_path}")

    return manifest_path


def _load_l0_config() -> dict:
    raw = _read_yaml(L0_CONFIG_PATH)
    cfg = raw.get("layer_0")
    if not isinstance(cfg, dict):
        raise KeyError("l0_config.yaml must contain top-level key 'layer_0'")
    return cfg


def _load_l1_config() -> dict:
    raw = _read_yaml(L1_CONFIG_PATH)
    cfg = raw.get("layer_1")
    if not isinstance(cfg, dict):
        raise KeyError("l1_config.yaml must contain top-level key 'layer_1'")
    return cfg


def _load_l4_config() -> dict:
    raw = _read_yaml(L4_CONFIG_PATH)
    cfg = raw.get("layer_4")
    if not isinstance(cfg, dict):
        raise KeyError("l4_config.yaml must contain top-level key 'layer_4'")
    return cfg


def _load_l5_config() -> dict:
    raw = _read_yaml(L5_CONFIG_PATH)
    cfg = raw.get("layer_5")
    if not isinstance(cfg, dict):
        raise KeyError("l5_config.yaml must contain top-level key 'layer_5'")
    return cfg


def _load_l7_config() -> dict:
    raw = _read_yaml(L7_CONFIG_PATH)
    cfg = raw.get("layer_7")
    if not isinstance(cfg, dict):
        raise KeyError("l7_config.yaml must contain top-level key 'layer_7'")
    return cfg


def _load_l8_config() -> dict:
    raw = _read_yaml(L8_CONFIG_PATH)
    cfg = raw.get("layer_8")
    if not isinstance(cfg, dict):
        raise KeyError("l8_config.yaml must contain top-level key 'layer_8'")
    return cfg


def _load_l3_config() -> dict:
    raw = _read_yaml(L3_CONFIG_PATH)
    cfg = raw.get("layer_3")
    if not isinstance(cfg, dict):
        raise KeyError("l3_config.yaml must contain top-level key 'layer_3'")
    return cfg


def _build_run_identity(run_profile: str, run_date: str | None) -> dict:
    resolved_date = _parse_run_date(run_date)
    created_at = _now_ist()
    window_end = _run_window_end(resolved_date)
    timestamp = created_at.strftime("%Y_%m_%d_%H%M%S")
    run_id = f"run_{timestamp}_{run_profile}"
    return {
        "run_date": resolved_date.isoformat(),
        "created_at": created_at.isoformat(),
        "run_id": run_id,
        "window_end": window_end,
    }


def _resolve_profile(l0_cfg: dict, profile_name: str) -> dict:
    profiles = l0_cfg.get("run_profiles")
    if not isinstance(profiles, dict):
        raise KeyError("layer_0.run_profiles missing or invalid")
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise KeyError(f"Unknown run profile: {profile_name}")
    return deepcopy(profile)


def _filter_query_themes(themes: list[str], excluded_topics: list[str]) -> list[str]:
    excluded = [topic.lower() for topic in excluded_topics]
    kept = []
    for theme in themes:
        lower = theme.lower()
        if any(blocked in lower for blocked in excluded):
            continue
        kept.append(theme)
    return kept


def _resolve_collection_window(profile: dict, created_at) -> dict:
    lookback_hours = int(profile["lookback_hours"])
    start = created_at - timedelta(hours=lookback_hours)
    return {
        "start": start.isoformat(),
        "end": created_at.isoformat(),
        "lookback_hours": lookback_hours,
    }


def _resolve_collectors(
    profile: dict,
    l1_cfg: dict,
    window: dict,
    query_themes: list[str],
    channel_cfg: dict,
) -> dict:
    groups = l1_cfg.get("source_groups")
    if not isinstance(groups, dict):
        raise KeyError("layer_1.source_groups missing or invalid")

    enabled_groups: list[str] = []
    collectors: dict[str, dict] = {}
    caps = profile.get("collector_caps", {})

    for group_name in profile["enabled_source_groups"]:
        group_cfg = groups.get(group_name)
        if not isinstance(group_cfg, dict):
            raise KeyError(f"Unknown source group in run profile: {group_name}")
        if not group_cfg.get("enabled", True):
            continue

        collector_cfg = deepcopy(group_cfg)
        collector_cfg["source_group"] = group_name
        collector_cfg["collection_window"] = deepcopy(window)
        collector_cfg["query_themes"] = list(query_themes)
        collector_cfg["allowed_topics"] = list(channel_cfg.get("allowed_topics", []))
        collector_cfg["runtime"] = deepcopy(caps.get(group_name, {}))

        enabled_count = _count_enabled_members(collector_cfg)
        if enabled_count == 0:
            raise RuntimeError(f"Source group has zero enabled sources: {group_name}")

        collectors[group_name] = collector_cfg
        enabled_groups.append(group_name)

    if not enabled_groups:
        raise RuntimeError("No enabled source groups remained after resolution")

    return {
        "enabled_source_groups": enabled_groups,
        "collectors": collectors,
    }


def _resolve_layer7_config(
    authoring_cfg: dict,
    *,
    profile: dict,
    script_style: str | None,
) -> dict:
    required_base = [
        "script_writer_model",
        "script_worker_count",
        "words_per_minute",
        "title_thumbnail_model",
        "default_script_style",
        "script_styles",
    ]
    missing_base = [key for key in required_base if key not in authoring_cfg]
    if missing_base:
        raise KeyError(f"l7_config.yaml layer_7 missing required keys: {missing_base}")

    styles = authoring_cfg["script_styles"]
    if not isinstance(styles, dict) or not styles:
        raise KeyError("l7_config.yaml layer_7.script_styles must be a non-empty mapping")

    selected_style = script_style or profile.get("script_style") or authoring_cfg["default_script_style"]
    if selected_style not in styles:
        available = ", ".join(sorted(styles))
        raise KeyError(f"Unknown script style '{selected_style}'. Available styles: {available}")

    style_cfg = styles[selected_style]
    if not isinstance(style_cfg, dict):
        raise KeyError(f"layer_7.script_styles.{selected_style} must be a mapping")
    required_style = ["script_writer_prompt_version", "title_thumbnail_prompt_version"]
    missing_style = [key for key in required_style if key not in style_cfg]
    if missing_style:
        raise KeyError(f"layer_7.script_styles.{selected_style} missing keys: {missing_style}")

    return {
        "script_writer_model": authoring_cfg["script_writer_model"],
        "script_worker_count": authoring_cfg["script_worker_count"],
        "words_per_minute": authoring_cfg["words_per_minute"],
        "title_thumbnail_model": authoring_cfg["title_thumbnail_model"],
        "script_style": selected_style,
        "script_style_description": style_cfg.get("description", ""),
        "available_script_styles": sorted(styles),
        "script_writer_prompt_version": style_cfg["script_writer_prompt_version"],
        "title_thumbnail_prompt_version": style_cfg["title_thumbnail_prompt_version"],
    }


def _count_enabled_members(group_cfg: dict) -> int:
    if "sources" in group_cfg:
        return sum(1 for item in group_cfg["sources"] if item.get("enabled", True))
    if "channels" in group_cfg:
        return sum(1 for item in group_cfg["channels"] if item.get("enabled", True))
    if "categories" in group_cfg:
        return sum(1 for item in group_cfg["categories"] if item.get("enabled", True))
    return 0


def _build_manifest(
    run_identity: dict,
    profile_name: str,
    trigger_type: str,
    channel_cfg: dict,
    window: dict,
    layer1_resolution: dict,
    layer3_cfg: dict,
    layer4_cfg: dict,
    layer5_cfg: dict,
    layer7_cfg: dict,
    layer8_cfg: dict,
    memory_context: dict,
) -> dict:
    return {
        "schema_version": "v1",
        "run_id": run_identity["run_id"],
        "run_date": run_identity["run_date"],
        "created_at": run_identity["created_at"],
        "status": "ready_for_layer_1",
        "memory_context": memory_context,
        "layer_0": {
            "run_profile": profile_name,
            "trigger_type": trigger_type,
            "collection_window": window,
            "channel": channel_cfg,
        },
        "layer_1": {
            "enabled_source_groups": layer1_resolution["enabled_source_groups"],
            "query_themes": layer1_resolution["query_themes"],
            "collectors": layer1_resolution["collectors"],
        },
        "layer_3": dict(layer3_cfg),
        "layer_4": dict(layer4_cfg),
        "layer_5": dict(layer5_cfg),
        "layer_7": dict(layer7_cfg),
        "layer_8": dict(layer8_cfg),
    }


def _build_summary(manifest: dict) -> dict:
    collectors = manifest["layer_1"]["collectors"]
    enabled_source_count = 0
    enabled_youtube_channel_count = 0

    for cfg in collectors.values():
        if "sources" in cfg:
            enabled_source_count += sum(1 for item in cfg["sources"] if item.get("enabled", True))
        if "categories" in cfg:
            enabled_source_count += sum(1 for item in cfg["categories"] if item.get("enabled", True))
        if "channels" in cfg:
            enabled_youtube_channel_count += sum(1 for item in cfg["channels"] if item.get("enabled", True))

    return {
        "run_id": manifest["run_id"],
        "run_profile": manifest["layer_0"]["run_profile"],
        "created_at": manifest["created_at"],
        "status": manifest["status"],
        "enabled_source_groups": manifest["layer_1"]["enabled_source_groups"],
        "enabled_source_group_count": len(manifest["layer_1"]["enabled_source_groups"]),
        "enabled_source_count": enabled_source_count,
        "enabled_youtube_channel_count": enabled_youtube_channel_count,
        "query_theme_count": len(manifest["layer_1"]["query_themes"]),
        "memory_context_available": bool(manifest.get("memory_context", {}).get("available")),
        "memory_video_count": manifest.get("memory_context", {}).get("stats", {}).get("video_count", 0),
        "memory_story_count": len(manifest.get("memory_context", {}).get("covered_stories", [])),
        "script_style": manifest.get("layer_7", {}).get("script_style", ""),
        "validation": {
            "passed": True,
            "errors": [],
            "warnings": [],
        },
    }


def _build_memory_context() -> dict:
    if not REBUILD_MEMORY_PATH.exists():
        return {
            "available": False,
            "memory_path": str(REBUILD_MEMORY_PATH),
            "stats": {},
            "approved_not_published_run_ids": [],
            "covered_stories": [],
            "recent_title_angles": [],
            "source_urls": [],
        }

    memory = json.loads(REBUILD_MEMORY_PATH.read_text(encoding="utf-8"))
    required = ["videos_by_run_id", "stories_by_story_id", "source_urls", "recent_title_angles", "stats"]
    missing = [key for key in required if key not in memory]
    if missing:
        raise KeyError(f"Rebuild memory store missing required keys: {missing}")

    videos = memory.get("videos_by_run_id", {})
    approved_not_published_run_ids = [
        run_id
        for run_id, video in videos.items()
        if video.get("memory_status") == "approved_not_published"
    ]
    covered_stories = [
        {
            "story_id": story_id,
            "story_title": story.get("story_title", ""),
            "memory_status": story.get("memory_status", ""),
            "latest_run_id": story.get("latest_run_id", ""),
            "selected_format": story.get("selected_format", ""),
        }
        for story_id, story in memory.get("stories_by_story_id", {}).items()
    ]
    recent_title_angles = [
        {
            "run_id": item.get("run_id", ""),
            "memory_status": item.get("memory_status", ""),
            "title": item.get("title", ""),
            "selected_format": item.get("selected_format", ""),
        }
        for item in memory.get("recent_title_angles", [])[-30:]
    ]
    return {
        "available": True,
        "memory_path": str(REBUILD_MEMORY_PATH),
        "stats": dict(memory.get("stats", {})),
        "approved_not_published_run_ids": approved_not_published_run_ids[-20:],
        "covered_stories": covered_stories[-80:],
        "recent_title_angles": recent_title_angles,
        "source_urls": list(memory.get("source_urls", {}).keys())[-100:],
    }


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must deserialize to a dict: {path}")
    return raw


def _now_ist() -> datetime:
    return datetime.now(IST)


def _parse_run_date(value: str | None) -> date:
    return date.fromisoformat(value) if value else _now_ist().date()


def _run_window_end(run_date: date) -> datetime:
    current = _now_ist()
    if run_date == current.date():
        return current
    return datetime.combine(run_date, time(23, 59, 59), tzinfo=IST)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-profile", required=True)
    parser.add_argument("--date", default=None)
    parser.add_argument("--trigger", default="manual")
    parser.add_argument("--script-style", default=None)
    args = parser.parse_args()
    path = run(args.run_profile, args.date, args.trigger, args.script_style)
    print(path)
