# L0 / L1 Rebuild Decisions

This document locks the rebuild decisions for the first active slice of the new
system: `L0` and `L1`.

The goal is to avoid copying the old system's config sprawl and confusing
runtime semantics into the new architecture.

## Scope

These decisions apply only to the first rebuild slice:
- `L0` manifest
- `L1` collection

They are intentionally narrow. Later layers may add new config and new manifest
keys only when those layers are implemented.

## Config Decisions

### 1. Use layer-wise config files only

For the first rebuild slice, create only:
- `src/config/l0_config.yaml`
- `src/config/l1_config.yaml`
- `src/config/paths.py`

Do not create:
- `run_profiles.yaml`
- `sources.yaml`
- `channels.yaml`
- `format_config.yaml`
- `prompt_config.yaml`
- any `l2+` config file yet

`l0_config.yaml` owns:
- our channel identity
- run profiles
- shared collection window defaults only if `L0` truly needs them

`l1_config.yaml` owns:
- source group definitions
- collector settings
- non-YouTube source registry
- external YouTube source registry

`src/config/paths.py` owns:
- project root and output/config path constants
- current-manifest path
- layer-relevant file path constants only

Keep `src/config/` declarative. Do not put manifest loading, yaml reading, or
date/time helper logic in `paths.py`.

### 2. One authoritative publishing-channel identity

Our own channel identity must exist in exactly one place:
- `src/config/l0_config.yaml`

That file should hold:
- `channel_name`
- `content_promise`
- `allowed_topics`
- `excluded_topics`

The canonical publishing-channel name for the rebuild is:
- `ManiVerse - AI`

Do not duplicate our channel name in prompt config or collector registries.

### 3. Remove ambiguous or dead config concepts from the new design

Do not carry these legacy concepts into the rebuild unless a real use case
appears:
- `optional_groups`
- `priority_order` as a vague planning hint
- `minimum_expected_documents`
- `maximum_expected_documents`
- `collection_windows.default.mode: inherit_base`
- `youtube.channel_selection`
- `scheduled_runs`
- `scoring_config.yaml`

If a future runtime genuinely needs one of these ideas, reintroduce it with a
clear operational meaning at that time.

### 4. Prefer explicit, narrow collector controls

If a collector limit is needed in the first slice, prefer clear names such as:
- `max_items`
- `max_articles`
- `max_papers`
- `max_videos_per_channel`

Avoid ambiguous names like:
- `max_per_duration`

If the runtime truly needs duration-bucket logic later, add it later with a
name that states exactly what it does.

## L0 Decisions

### 5. The manifest is the only runtime contract

`L0` writes:
- `output/{run_id}/run_manifest.json`
- `output/{run_id}/summary.json`
- `output/current_manifest.json`

Do not add:
- `run_config_snapshot.json`
- separate validation artifacts
- future-layer keys

The manifest is the only runtime contract downstream layers read.
`output/current_manifest.json` is a convenience copy of the latest manifest, not
a second source of truth.

### 6. Keep the first manifest narrow

The first manifest should contain only:
- run identity and timestamps
- `layer_0`
- `layer_1`

`layer_0` should contain:
- selected run profile
- trigger type
- collection window
- channel scope

`layer_1` should contain:
- enabled source groups
- query themes
- fully resolved collector runtime config

Do not duplicate the same runtime values in multiple places in the manifest.
If a cap is for `L1`, it belongs only under `layer_1`.

### 7. Require explicit run intent

The new runner should not silently decide important content behavior.

For the first slice:
- require explicit run profile selection
- avoid hidden defaults for content scope

The runner may still have simple operational defaults such as today's date.

## L1 Decisions

### 8. `L1` reads only the manifest

Collectors must not read yaml directly.

`L1` reads:
- `run_manifest.json`

`L1` writes:
- `output/{run_id}/L1/raw_records.json`
- `output/{run_id}/L1/summary.json`

No backward joins. No reopening config files.

### 9. Main data file contains collected raw records

`L1/raw_records.json` should contain the records the collectors actually
collected from the enabled source groups.

It should not be the place where manifest-window exclusion or downstream
story-map keep/drop decisions happen. Those belong in `L2`.

Common collector/source details should stay flat on the record itself, for
example:
- `collector`
- `source_name`
- `trust_tier`
- `provider`
- `summary`

Do not hide these under a nested `metadata` dict in the rebuild.

`summary.json` must still report:
- fetched count
- collected count
- any collector-side filtered count

### 10. Fetch-then-filter is allowed, but it must be visible

Some sources will support precise window filtering at fetch time.
Some will not.

So for the rebuild:
- fetch-then-filter is acceptable when the source demands it
- but the summary must make this explicit
- manifest-window filtering should happen in `L2`, not inside `L1`

Per collector or source group, the summary should make it easy to see:
- fetched count
- kept count
- filtered-out count
- why items were filtered out

### 11. Normalize placeholder bodies as partial content

If a source returns placeholder text such as:
- `ONLY AVAILABLE IN PAID PLANS`

do not treat that as meaningful article body text.

Instead, normalize it as partial content, for example:
- empty or reduced body content
- metadata flag indicating truncated or unavailable full text

This improves downstream script quality because later layers will not mistake
API plan-limit placeholders for factual evidence.

### 12. Separate enabled groups from successful groups

The `L1` summary should distinguish:
- source groups enabled by the manifest
- source groups that actually produced collected records

Both are useful. They are not the same metric.

### 13. Do not introduce "primary docs" in the first `L1`

Trust-tier-based concepts such as "primary docs" are useful later, but they are
not necessary for the first rebuild slice of collection.

For the new `L1`:
- collect and normalize records
- report content availability honestly
- defer trust-tier quality interpretation to `L2` unless collection behavior
  truly depends on it

This keeps `L1` simpler and easier to understand.

### 14. Validation should target the normalized output schema only

If the first `L1` validates its output, it should validate only the normalized
record contract, not every source-specific field returned by upstream APIs.

That means validating fields such as:
- source identity
- source type
- content
- normalized metadata

Not every raw payload key.

## Why These Decisions Help Script Quality Later

These choices improve future scripts by improving the evidence entering the
system:
- clearer topic scope from one channel identity
- less config ambiguity
- fewer dead runtime knobs
- cleaner collection counts
- fewer misleading placeholder article bodies
- easier-to-reason-about collector output

The first rebuild slice should help later script quality by making collection
cleaner and more legible, not by trying to encode future script policy too
early.
