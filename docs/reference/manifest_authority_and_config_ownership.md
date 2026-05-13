# Manifest Authority and Config Ownership

This document captures the architecture rule for configuration ownership in the pipeline and the current implementation state.

## Implementation status

As of 2026-05-13, the active supported runtime path is manifest-backed and run-profile-driven.

The config directory is now intentionally split into:

- `config/registries/` for source, channel, audience, and taxonomy registries
- `config/policies/` for run behavior, strategy, and editorial policy

See [run_profile_control_plane.md](./run_profile_control_plane.md).

Layer 0 writes a `resolved_config` section into `run_manifest.json` with snapshots for:

- active source registry subset
- enabled YouTube channel subset
- effective LLM profiles
- entity/topic taxonomy
- ChatGPT handoff prompt config
- runtime run-profile metadata

The active downstream runtime path now reads those snapshots in:

- Layer 1 source registry loading
- Layer 1 YouTube orchestration
- Layer 3 entity/topic mapping
- Layer 5 format/runtime decisions
- active LLM modules in Layers 4, 5, 7, 8, and 9
- `chatgpt_export.py`

Downstream runtime modules no longer fall back to live repo config files when a required manifest snapshot is missing. The run must be rebuilt from Layer 0 instead.

## Short answer

Yes, the design direction should be:

- Layer 0 reads the source configs
- Layer 0 resolves them into one run-scoped contract
- downstream layers read the run manifest, not the original config files

That is also what the Layer 0 design says explicitly:

- "Downstream layers should not separately read random config files. They should read one `run_manifest.json`."

See [layer_0.md](../system_design_docs/layer_0.md).

## The right architectural split

The clean model is not "delete all config files."

The clean model is:

- authoring configs live in `config/`
- Layer 0 reads them once
- Layer 0 writes a resolved run snapshot into `data/runs/{run_id}/run_manifest.json`
- every downstream layer uses that snapshot as its source of truth for the run

In other words:

- `config/*.yaml` and `config/llm_config.py` are authoring inputs
- `run_manifest.json` is the immutable run contract

## What should be manifest-driven

Anything that can affect behavior for a specific run should be resolved into the run manifest and consumed downstream from there.

This includes:

- channel thesis and audience profile
- eligible formats and selected format requirements
- selected run profile and decision mode
- collection windows and source-group policy
- resolved source registry subset for the run
- resolved YouTube channel subset for the run
- quality policy
- memory policy and memory paths
- depth limits
- effective LLM profiles, module overrides, and model choices used for the run
- prompt/handoff strategy used for the run when reproducibility matters

## What can remain as authoring config

These files still exist and remain easy to edit:

- `config/registries/channel_thesis.yaml`
- `config/registries/audience_profiles.yaml`
- `config/policies/format_config.yaml`
- `config/registries/sources.yaml`
- `config/policies/source_strategy.yaml`
- `config/registries/channels.yaml`
- `config/policies/quality_rules.yaml`
- `config/policies/chatgpt_prompts.yaml`
- `config/registries/entity_topic_taxonomy.yaml`
- `config/llm_config.py`

In the current layout those live under:

- `config/registries/`
- `config/policies/`

But downstream runtime behavior should not depend on re-reading them directly once the run has started.

## Recommended rule

Use this rule going forward:

1. Layer 0 is the only layer allowed to resolve authoring config into run behavior.
2. Downstream layers should consume only the run manifest plus upstream layer outputs.
3. If a downstream layer currently needs something from `config/`, that value should first be copied into the manifest as a resolved snapshot.

## Important nuance

The goal is not to dump every raw config file into the manifest with no structure.

The goal is to store the resolved subset that was actually used by the run.

That means:

- not the entire global source registry if only some sources were in scope
- not every possible LLM profile if only certain modules were active
- not every possible YouTube channel if only some were enabled for the run

The manifest should carry the effective run snapshot, not an uncontrolled mirror of the whole config folder.

## Why this matters

This gives the system:

- reproducibility
- auditability
- mid-run config safety
- easier debugging
- clearer ownership boundaries

Without this, a later config edit can change downstream behavior for an already-created run, which breaks the whole point of the run manifest.

## Current repo state

The active runtime path now follows the intended architecture.

Manifest-driven already:

- Layer 0 selected run profile and decision mode
- Layer 1 collection windows
- Layer 1 enabled source groups and query themes
- Layer 1 query theme set and per-run YouTube fetch caps
- Layer 1 resolved source registry subset
- Layer 1 resolved YouTube channel subset
- Layer 3 entity/topic taxonomy
- Layer 5 format requirements and format-routing scope
- active LLM profile selection
- ChatGPT handoff prompt config
- memory policy and output contracts written by Layer 0

Still not fully strict:

- Layer 0 reads authoring config files by design
- some standalone/inactive utilities still read config files directly because they are authoring helpers, not supported runtime consumers

## Why the system drifted

This was not entirely accidental.

The implementation decisions show that the intended architecture was manifest-driven, but some direct config reads remained because the earlier priority was to make the workflow functional end-to-end before finishing the control-plane cleanup.

Two specific patterns caused the drift:

- existing collectors and helpers were wrapped rather than fully rewritten
- several later modules kept direct config reads because their logic was built before the manifest snapshot was fully carried through every layer

See [architecture_decisions.md](../implementation_decisions/architecture_decisions.md).

## Remaining cleanup direction

The main active-path rollout is done. What remains is tightening around tooling and clarity:

- keep the manifest ownership rules explicit in docs and validation
- classify every config file as either:
  - authoring input only
  - run-scoped snapshot required
  - global runtime-only infrastructure
- migrate any remaining standalone utilities to manifest-first behavior where useful
- keep the config files only as Layer 0 inputs, not downstream runtime dependencies

## LLM config note

`config/llm_config.py` should probably remain the authoring surface for humans, but downstream modules should still stop importing it directly.

The better architecture is:

- Layer 0 resolves the effective LLM settings for the run
- the manifest stores those effective settings
- a shared runtime helper loads them from the manifest

That preserves both:

- editability
- run reproducibility

## Source registry note

`sources.yaml` and `channels.yaml` should continue to exist, but they should act as registries that Layer 0 resolves into:

- active source groups
- active source definitions
- active channel list
- active per-source policies

Those resolved subsets should then be stored in the manifest for the run.

## Recommendation

Architecturally, the strongest rule is:

- all downstream behavior should be driven from the Layer 0 run manifest

Practically, that should mean:

- keep `config/` as authoring input
- stop using `config/` as downstream runtime input
- snapshot effective values into the manifest instead
