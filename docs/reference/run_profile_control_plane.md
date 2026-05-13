# Run Profile Control Plane

This document describes the current run-policy architecture for the active pipeline.

## Purpose

The system now separates:

- `config/registries/` for asset registries
- `config/policies/` for run behavior and strategy
- `run_manifest.json` for the immutable, resolved run contract

The active runtime should no longer decide collection and routing behavior from scattered config reads. Layer 0 resolves the selected run profile and downstream layers consume the manifest.

## Config split

### Registries

These files answer "what exists?"

- `config/registries/sources.yaml`
- `config/registries/channels.yaml`
- `config/registries/channel_thesis.yaml`
- `config/registries/audience_profiles.yaml`
- `config/registries/entity_topic_taxonomy.yaml`

Registry files should not carry run-scoped collection windows or per-run routing decisions.

### Policies

These files answer "how should this run behave?"

- `config/policies/pipeline_config.yaml`
- `config/policies/run_defaults.yaml`
- `config/policies/run_profiles.yaml`
- `config/policies/source_strategy.yaml`
- `config/policies/format_config.yaml`
- `config/policies/quality_rules.yaml`
- `config/policies/chatgpt_prompts.yaml`

## Run profiles

The primary run-policy file is:

- `config/policies/run_profiles.yaml`

Each profile defines:

- `target_format`
- `decision_mode`
- `allowed_formats`
- `lookback_hours`
- `depth`
- `max_videos`
- `source_plan`
- `collection_windows`
- `youtube`
- `memory_windows`

## Decision modes

### `auto_route`

Used when Layer 5 is allowed to compare formats and choose.

Current example:

- `auto_48h`

Behavior:

- Layer 0 collects with the profile policy
- Layer 5 scores only the profile's allowed formats
- Layer 5 may choose between those allowed formats

### `forced_format`

Used when the run already knows the intended format.

Current examples:

- `roundup_48h`
- `roundup_weekly`
- `deep_dive_weekly`

Behavior:

- Layer 0 collects with the profile policy
- Layer 5 only evaluates the requested format branch
- Layer 5 returns `create_video` or `no_video`
- Layer 5 does not cross-fallback into a different format

## Current Layer 0 behavior

Layer 0 now resolves run policy in this order:

1. explicit `--run-profile`
2. inferred profile from `--target-format` and optional `--lookback-hours`
3. default profile from `pipeline_config.yaml` / `run_defaults.yaml`

Operational knobs can still be overridden without changing the collection/routing policy:

- `depth`
- `max_videos`

Those overrides are recorded in `run_manifest.json` under `run_profile.operational_overrides`.

## Current downstream behavior

### Layer 1

Layer 1 now consumes the manifest's resolved run policy for:

- enabled source groups
- query theme set and query themes
- collection window
- per-source-group window overrides
- YouTube channel registry snapshot
- YouTube per-run max-per-duration policy

### Layer 5

Layer 5 now consumes the manifest's run profile for:

- `allowed_formats`
- `decision_mode`
- forced-format vs auto-route behavior

This means the run profile chosen in Layer 0 now affects both collection and editorial routing in a consistent way.

## Why this matters

This gives the pipeline:

- reproducible run behavior
- cleaner config ownership
- fewer hidden runtime config reads
- a stable place to add future profiles such as evergreen, comparison, and follow-up

## Current profile set

At the moment the active policy file defines:

- `auto_48h`
- `roundup_48h`
- `roundup_weekly`
- `deep_dive_weekly`

Future format profiles should be added here rather than implemented as hardcoded branches inside downstream layers.
