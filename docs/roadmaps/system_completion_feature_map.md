# System Completion Feature Map

This document reorganizes the remaining system work by **feature / capability**, not by layer.

The goal is to answer:

- what capability is still incomplete
- which layers participate in it
- why it was deferred earlier
- why it is worth building now
- what “done” should mean when we implement it

This document is intentionally planning-oriented. It is not a changelog.

## How to read this

### Priority labels

- `Now` means the capability closes a real correctness, observability, or workflow gap in the current supported pipeline.
- `Next` means the capability completes important system behavior after the current core gaps are closed.
- `Later` means the capability is part of the full design but depends on strategy expansion, published-video history, or additional external data.

### Sources used

This map was derived from:

- [master_system_design.md](../system_design_docs/master_system_design.md)
- [architecture_decisions.md](../implementation_decisions/architecture_decisions.md)
- the active `pipeline.py` code path and current layer orchestrators

## Executive View

The remaining work clusters into these feature areas:

1. Manifest-driven collection control and source orchestration
2. Run-profile control plane and config ownership
3. Cross-run memory feedback loop completion
4. Publication lifecycle and YouTube analytics ingestion
5. Repetition and similarity safety
6. Multi-format expansion beyond roundup and deep dive
7. Unified async LLM runtime, provider abstraction, and observability
8. Verification and provenance hardening
9. Compiled run-state / run-graph artifact
10. Strategy-driven ChatGPT handoff system
11. Output contract and run completeness enforcement
12. Story intelligence and recurrence upgrades
13. Manifest authority and config ownership cleanup

## Priority Summary

### Build now

- Cross-run memory feedback loop completion

### Build next

- Verification and provenance hardening
- Compiled run-state / run-graph artifact
- Strategy-driven ChatGPT handoff system
- Story intelligence and recurrence upgrades
- Multi-format expansion beyond supported profiles

### Build later

No additional later-only feature bucket is currently called out beyond future strategy and channel expansion.

---

## 1. Manifest-Driven Collection Control and Source Orchestration

**Priority:** `Now`

### What this feature is

Make Layer 0’s collection policy actually control Layer 1 behavior:

- time windows
- source-specific windows
- collection limits
- channel-aware YouTube collection
- future memory-driven source priority and watchlist queries

### Why it exists in the design

The design expects Layer 0 to determine:

- what the run is trying to collect
- from which source groups
- for what time horizon
- with what collection policy

Then Layer 1 should execute that plan, not an approximate version of it.

### Layers involved

- Layer 0
- Layer 1
- Layer 10 later for source-priority / watchlist feedback

### Current implementation

Implemented:

- Layer 0 computes collection and memory windows
- Layer 0 writes source scope and memory policy to the manifest
- Layer 0 now snapshots runtime timezone settings into `resolved_config.runtime`
- Layer 1 now reads enabled source groups and query themes from the correct `collection_strategy` manifest fields
- Layer 1 now applies manifest-driven collection windows to the raw document corpus
- collectors that support it already can also receive fetch-side `days_back` narrowing from the manifest window
- Layer 0 run profiles now own the active Layer 1 collector caps
- `extraction_manifest.json` now records the applied collection policy for the run
- YouTube is now part of the main Layer 1 orchestration path through the manifest-backed YouTube snapshot and the YouTube transcript wrapper
- Layer 0 now resolves collection windows from named run profiles instead of hardcoded Python window rules
- Layer 4 now reads its evidence-loader story cap from the manifest instead of a hardcoded default

Missing or incomplete:

- some source groups still rely on post-fetch window filtering because their current wrappers do not expose clean server-side date constraints
- Layer 10 source-priority feedback is not yet fed back into Layer 1
- YouTube channel selection is still registry-driven rather than dynamically narrowed per run

### Why it was deferred earlier

From the implementation decisions:

- existing collectors were wrapped rather than rewritten
- the time-window fields were added to the manifest first
- YouTube orchestration was separated because it needed API key + channel IDs
- the main goal then was to get the end-to-end workflow running with existing collectors

### Why build it now

- the current system already depends on run manifests as the contract
- the user expects config-controlled collection behavior
- incomplete time-window enforcement makes results harder to reason about
- YouTube is explicitly part of the design and config, but not part of the real run path

### What “done” should mean

- Layer 1 collector calls accept manifest-derived lookback or date bounds
- the Layer 0 snapshot of `channels.yaml` is wired into run execution cleanly
- YouTube collection is an orchestrated source group, not a manual side path
- future Layer 10 source-priority and watchlist guidance can influence Layer 1 query/collection policy
- the policy for undated/unparseable documents is explicit rather than incidental

### Status note

The core manifest-driven behavior is now implemented for the active path. The remaining work here is about richer source selection, stricter fetch-side narrowing, and efficiency, not basic Layer 0 → downstream policy ownership.

### Key files

- `config/policies/run_profiles.yaml`
- `config/policies/run_defaults.yaml`
- `config/policies/source_strategy.yaml`
- `config/registries/sources.yaml`
- `config/registries/channels.yaml`
- `pipelines/layer_0_control/time_window_resolver.py`
- `pipelines/layer_1_extraction/run_layer_1.py`

---

## 2. Run-Profile Control Plane and Config Ownership

**Priority:** `Now`

### What this feature is

Use named run profiles as the primary control surface for:

- collection horizon
- source-plan policy
- query theme set
- YouTube fetch caps
- forced-format vs auto-route editorial behavior

### Current implementation

Implemented:

- config files are now split into `config/registries/` and `config/policies/`
- Layer 0 resolves `config/policies/run_profiles.yaml`
- `pipeline.py` and `run_layer_0.py` now support `--run-profile`
- `daily_48h_all_sources` now exists as a strict all-sources 48-hour monitoring profile
- explicit roundup and deep-dive selectors resolve to named profiles
- Layer 5 now respects `decision_mode` and `allowed_formats` from the manifest
- explicit forced-format runs now produce format-specific `create_video` or `no_video`
- active per-source collector caps and Layer 4 story-selection caps are now resolved from the selected profile into the manifest

Missing or incomplete:

- evergreen, comparison, and follow-up profiles are not yet defined
- some standalone helper utilities still need cleanup and clearer docs

### Why it matters now

- this is the control-plane foundation for future format expansion
- collection policy and editorial routing now share one manifest-driven source of truth
- it removes another category of hidden downstream config drift

### Key files

- `config/policies/run_profiles.yaml`
- `docs/reference/run_profile_control_plane.md`
- `pipelines/layer_0_control/run_profile_resolver.py`
- `pipelines/layer_0_control/run_layer_0.py`
- `pipelines/layer_5_editorial_intelligence/run_layer_5.py`

---

## 2A. Dynamic Workload Reporting

**Priority:** `Now`

### What this feature is

Remove misleading hardcoded API-call estimates from the pipeline runner and make workload reporting come from the layers after they inspect real inputs.

### Current implementation

Implemented:

- `pipeline.py` no longer prints hardcoded `~218`, `~12`, `~11`, or `~9` API-cost summaries
- `pipeline_config.yaml` preset descriptions no longer claim fixed API totals
- the pipeline runner now labels LLM work as dynamic and lets the layers report real run-derived workload sizes

Missing or incomplete:

- some layers could expose clearer pre-dispatch estimates before starting their LLM work
- run-level summaries still do not aggregate actual request counts from the shared runtime logs

### Why it matters now

- static cost banners were materially misleading
- LLM workload depends on selected spans, stories, sections, and verifiable content units
- the layers already know the real work shape better than the orchestrator does

### What “done” should mean

- pipeline-level output never claims static API usage for dynamic layers
- each LLM layer reports its own real run-derived workload
- future observability can summarize actual request counts from logs rather than from assumptions

---

## 2B. Output Tree Hygiene

**Priority:** `Now`

### What this feature is

Stop creating empty runtime folders that the active pipeline does not actually use.

### Current implementation

Implemented:

- the active async LLM runtime now creates only `output/llm_logs/...` instead of calling a broad directory-creation helper
- active layer orchestrators no longer eagerly create per-run `layer_X/` directories before outputs are written
- output directories are now created by the modules that actually write files

Why it matters:

- the old behavior left confusing empty top-level `data/...` folders behind
- failed runs could leave empty per-layer directories that looked like partial outputs

Remaining work:

- legacy and inactive helper paths still keep broader compatibility helpers around
- those should be cleaned only when we do the legacy-folder removal pass

---

## 3. Cross-Run Memory Feedback Loop Completion

**Priority:** `Now`

### What this feature is

Complete the design’s memory loop so memory is not only written, but also selectively reused across the pipeline.

This includes:

- novelty and prior coverage
- follow-up context
- prior hooks and title angles
- blocked editorial patterns
- prior claim/risk memory
- future source-priority and story-family memory

### Why it exists in the design

The design treats Layer 10 as a channel memory system that should support future layers, not just archive past runs.

### Layers involved

- Layer 0
- Layer 1 later
- Layer 3 later
- Layer 5
- Layer 6 later
- Layer 7 later
- Layer 8 later
- Layer 9 later
- Layer 10
- `chatgpt_export.py`

### Current implementation

Implemented:

- Layer 10 writes persistent memory
- Layer 5 reads `video_memory.jsonl` and `followups.jsonl`
- Layer 0 writes memory policy and paths into the manifest
- `chatgpt_export.py` reads `memory_snapshot.json`

Missing or incomplete:

- Layer 6 does not consume evergreen/follow-up/claim-ledger memory
- Layer 7 does not consume prior hooks/title/style memory
- Layer 8 does not consume blocked phrase or prior-risk memory
- Layer 9 does not yet consume repetition/risk memory directly
- Layer 1 and Layer 3 do not consume memory-derived guidance yet

### Why it was deferred earlier

- early implementation focused on completing the forward pipeline
- before Layer 10 existed, memory flags were only placeholders
- before memory had real records, several consumers would have been empty or misleading

### Why build it now

- Layer 10 exists and produces real memory files
- we already encountered published vs prepared memory issues
- repetition, follow-up routing, and editorial continuity now depend on this loop being explicit

### What “done” should mean

- every intended memory consumer either uses memory directly or is explicitly marked deferred
- memory consumption is aligned with published-only vs prepared-run semantics
- memory influence is visible in run outputs, not just hidden inside internal helpers

### Key files

- `pipelines/layer_0_control/memory_context_planner.py`
- `pipelines/layer_5_editorial_intelligence/novelty_checker.py`
- `pipelines/layer_10_memory_learning/*`
- `memory/memory_snapshot.json`

---

## 4. Publication Lifecycle and YouTube Analytics Ingestion

**Priority:** `Now`

### What this feature is

Add the missing bridge between a prepared pipeline output and a truly published channel artifact.

This includes:

- marking a prepared run as published
- attaching a real `youtube_video_id`
- storing the publish timestamp
- ingesting actual performance metrics later

### Why it exists in the design

The design’s durable memory is meant to represent real channel history, not just internal draft history.

Performance memory is also meant to inform:

- future format choice
- hook style
- pacing
- title/thumbnail decisions

### Layers involved

- Layer 9
- Layer 10
- future external YouTube ingest path
- `chatgpt_export.py` indirectly

### Current implementation

Implemented:

- Layer 10 records prepared videos
- memory snapshot / novelty now correctly distinguish published vs unpublished in key consumers
- publish-state updater exists through `publishing_memory.py mark-published`
- authenticated owner-channel sync exists through `publishing_memory.py sync-channel`
- `performance_memory.jsonl` now has a concrete ingestion path
- memory rebuild after publish-state changes is automated

Still pending in practice:

- first real published video flowing through the workflow
- enough real performance history for analytics-driven learning signals to become meaningful

Completed in practice:

- live OAuth authorization on the local machine
- authenticated owner-channel sync
- canonical channel resolution to `UCp4tfcoFDQIFu7Cnodrqq_w`
- fresh-start memory reset so the first production runs begin from clean editorial memory

Current project assumptions captured for this feature:

- single publishing channel first
- current public handle is `@Eswar-P2`
- canonical `channel_id` should be discovered via authenticated sync, not treated as a permanent manual input
- no historical video backfill is needed yet
- full analytics ingest requires OAuth credentials, not only `YOUTUBE_API_KEY`

### Why it was deferred earlier

From the implementation decisions:

- no videos had been published yet
- there was no real `youtube_video_id` or analytics to ingest

### Why build it now

- without it, durable memory remains semantically mixed
- performance learning stays permanently empty
- manual JSON editing is fragile and easy to do inconsistently

### What “done” should mean

- a published run can be marked with timestamp and platform video ID
- the system can resolve the authenticated publishing channel and sync its published-video state
- `performance_memory.jsonl` has a supported ingestion path
- memory snapshot/index rebuild automatically after publication-state changes

### Key files

- `pipelines/layer_10_memory_learning/video_memory_writer.py`
- `pipelines/layer_10_memory_learning/memory_snapshot_builder.py`
- `pipelines/layer_10_memory_learning/learning_signal_builder.py`
- `docs/reference/publishing_channel_and_analytics_setup.md`
- `docs/workflows/publishing_memory_workflow.md`

---

## 5. Repetition and Similarity Safety

**Priority:** `Now`

### What this feature is

Prevent the system from covering the same story, angle, hook, title, thumbnail framing, or takeaway too repeatedly across runs.

This is not just novelty at story selection time. It is also script- and metadata-level repetition control.

### Why it exists in the design

The design separates:

- editorial novelty before selection
- repetition safety after the script is written

That distinction matters because the same story can be covered with a genuinely new angle or with a repetitive one.

### Layers involved

- Layer 5
- Layer 7
- Layer 9
- Layer 10
- `chatgpt_export.py`

### Current implementation

Implemented:

- Layer 5 novelty checks against video memory and followups
- Layer 7 already produces blocked title angles
- Layer 10 stores editorial pattern memory
- handoff exporter uses published-memory repetition guidance
- Layer 9 `repetition_safety_checker.py` now checks published-memory story/title reuse before final approval

Still incomplete:

- richer Layer 7 direct memory use for title/hook repetition avoidance
- explicit takeaway/thumbnail repetition checks
- stronger cross-video family logic beyond direct story/title reuse

### Why it was deferred earlier

From the implementation decisions:

- this was skipped because the memory system did not exist yet
- empty memory would have produced false confidence

### Why build it now

- Layer 10 now exists
- editorial pattern memory now exists
- repetition control becomes more important once channel output starts accumulating

### What “done” should mean

- repetition checks exist before selection and after script generation
- the system can explain why a title/hook/thumbnail angle is being blocked
- the repetition outcome is visible in Layer 9 outputs

### Key files

- `pipelines/layer_5_editorial_intelligence/novelty_checker.py`
- `pipelines/layer_7_content_planning/title_thumbnail_planner.py`
- `pipelines/layer_10_memory_learning/editorial_pattern_memory_writer.py`
- `pipelines/layer_9_verification_firewall/repetition_safety_checker.py`

---

## 6. Multi-Format Expansion Beyond Roundup and Deep Dive

**Priority:** `Later`

### What this feature is

Complete the full format strategy path for:

- `evergreen`
- `comparison`
- `follow_up`

across routing, packet building, planning, writing, and verification.

### Why it exists in the design

The design is clearly multi-format. Roundup and deep dive are not the whole system.

### Layers involved

- Layer 0
- Layer 5
- Layer 6
- Layer 7
- Layer 8
- Layer 9
- Layer 10

### Current implementation

Implemented:

- format config structure exists
- Layer 5 has some awareness of more than one format
- active supported end-to-end path is roundup + deep dive

Missing:

- routing-ready support for evergreen/comparison/follow_up
- packet builders for these formats
- planning templates for these formats
- script writers for these formats
- verification rules specific to comparison/follow-up claims

### Why it was deferred earlier

From the implementation decisions:

- formats were disabled in `format_config.yaml`
- upstream support did not exist
- follow-up specifically was blocked by empty memory
- building those branches earlier would have created dead code paths

### Why not first

This is system-completion work, but not the first thing to build.

Why:

- current supported path still has correctness and workflow gaps
- adding more strategies on top of incomplete memory, logging, and collection policy would increase complexity faster than value

### What “done” should mean

- format routing can genuinely choose these formats
- Layer 6 packets exist and are evidence-safe
- Layer 7 plans exist
- Layer 8 writers exist
- Layer 9 verification knows how to assess their unique failure modes

### Key files

- `config/policies/format_config.yaml`
- `pipelines/layer_5_editorial_intelligence/*`
- `pipelines/layer_6_research_packets/*`
- `pipelines/layer_7_content_planning/*`
- `pipelines/layer_8_script_generation/*`
- `pipelines/layer_9_verification_firewall/*`

---

## 7. Unified Async LLM Runtime, Provider Abstraction, and Observability

**Priority:** `Now`

### What this feature is

Create one shared async LLM runtime for the active pipeline that handles:

- provider routing
- model selection from config
- API quirks like unsupported temperature args
- structured request/response logging
- per-run log destinations

### Why it exists in the design

The system is already increasingly LLM-orchestrated in Layers 4, 5, 7, 8, and 9.
Operationally, those calls need to be inspectable and configurable.

### Layers involved

- Layer 4
- Layer 5
- Layer 7
- Layer 8
- Layer 9
- `config/llm_config.py`
- `llm/`

### Current implementation

Implemented:

- model/temperature profiles in `config/llm_config.py`
- Layer 0 snapshots effective LLM runtime profiles into the run manifest
- shared async runtime now centralizes AsyncOpenAI calls for active LLM modules in Layers 4, 5, 7, 8, and 9
- logs now write to `output/llm_logs/{run_id}/{layer}/{module}.jsonl`
- each run now has a root `llm_log_summary.json`

Still incomplete:

- full multi-provider abstraction for the active async path
- centralized timeout / retry policy
- migrating remaining standalone/inactive LLM paths onto the same runtime

### Why it was deferred earlier

- getting the end-to-end behavior working took priority
- reusing direct `AsyncOpenAI` calls was faster in the short term
- logging infrastructure remained attached to legacy LangChain-style modules

### Why build it now

- model-config centralization is already a stated project goal
- missing logs are now a user-visible problem
- provider-specific drift is becoming a maintenance risk

### What “done” should mean

- active LLM modules stop instantiating provider SDK clients ad hoc
- logs exist for every active LLM call path
- the same runtime enforces config and logging consistently

### Status note

The shared runtime and the new layer/module log layout are now implemented. The remaining work here is resilience and future provider abstraction.

### Key files

- `config/llm_config.py`
- `llm/async_llm_runtime.py`
- `docs/reference/llm_log_layout.md`
- active async LLM modules in Layers 4, 5, 7, 8, and 9

---

## 8. Verification and Provenance Hardening

**Priority:** `Next`

### What this feature is

Strengthen the script-to-evidence contract beyond the current workable version.

This includes:

- richer sentence-to-claim provenance where needed
- stronger contradiction / unresolved-gap blocking
- format-specific verification for future comparison/follow-up behavior
- metadata-package completeness where downstream tools may need separate files

### Why it exists in the design

The design treats verification as more than just “did we cite something.”
It is meant to stop overclaiming, unsupported comparison, repetitive framing, and missing caution.

### Layers involved

- Layer 4
- Layer 8
- Layer 9
- Layer 10 later through risk memory

### Current implementation

Implemented:

- Layer 9 verifies against source spans, which is strong
- cautious language and overclaim checks exist
- metadata safety and source attribution checks exist

Missing or lighter than design:

- sentence mapping is section-level rather than fully sentence-specific
- contradiction/evidence-gap handling is mostly informational
- repetition safety module is absent
- comparison-specific verification paths are absent because comparison format is absent

### Why it was deferred earlier

- full sentence-level mapping is costly and complex
- contradiction blocking was less urgent in a dataset with few real contradictions
- comparison verification was unreachable while that format stayed disabled

### Why build it next

- the current verification path is good enough for the supported path
- hardening is most useful after memory, logging, and collection semantics are improved

### What “done” should mean

- the system can explain provenance at the granularity the chosen verification mode requires
- contradiction and unresolved-gap handling has clear blocking rules
- verification semantics are explicit for each supported format

---

## 9. Compiled Run-State / Run-Graph Artifact

**Priority:** `Next`

### What this feature is

Add a derived run-wide artifact, such as:

- `run_state.json`
- `run_graph.json`

to make the full run inspectable without replacing the current per-layer outputs.

### Why it exists in the design

This one is not an explicit original-design module. It is an architectural recommendation based on how the current pipeline actually behaves.

### Layers involved

- Layer 2 through Layer 10
- exports and tooling

### Current implementation

Implemented:

- several checkpoint-style master artifacts already exist
- per-layer authoritative outputs are clear

Missing:

- one compiled run-level object graph tying documents, spans, stories, claims, sections, and sentences together

### Why it was deferred earlier

- earlier work focused on getting the core forward pipeline to exist
- each layer checkpoint was enough to keep moving

### Why build it next

- downstream joins are now clearly visible as a complexity source
- export, debugging, and future tooling would benefit from one inspectable run graph

### What “done” should mean

- per-layer outputs stay authoritative
- one derived run-state artifact is rebuilt safely by orchestrators
- helper tooling can prefer the compiled artifact without hiding provenance

### Key files

- all orchestrators from Layer 2 onward
- future run-state builder(s)

---

## 10. Strategy-Driven ChatGPT Handoff System

**Priority:** `Next`

### What this feature is

Move the ChatGPT handoff system from partially code-defined behavior to a more strategy-driven configuration model.

This includes:

- strategy-specific instruction blocks
- required output formats
- review checklists
- memory sections relevant to each strategy

### Why it exists in the design

The handoff system is a real operating mode of this repo. It should reflect the actual selected format and evidence state, not generic prompt logic.

### Layers involved

- handoff exporter
- run artifacts from Layer 0, 3, 4, 5, 6, 7, 8
- memory snapshot

### Current implementation

Implemented:

- dynamic format resolution from downstream artifacts
- partial config-driven shared prompt blocks
- deep-dive vs roundup differentiation
- partial-run export guard

Missing:

- fully strategy-driven prompt families
- support for additional formats once enabled
- cleaner contract between handoff level and required upstream artifacts

### Why it was deferred earlier

- first objective was to get a usable handoff flow with current supported formats
- a code-defined exporter was faster to stabilize than a more abstract prompt system

### Why build it next

- the handoff path is central to current usage
- more strategies will make hardcoded exporter behavior harder to maintain

### What “done” should mean

- prompt behavior is clearly separated into shared config vs strategy-specific config
- artifact requirements are explicit per handoff level
- the exporter stays aligned with supported formats as they expand

---

## 11. Output Contract and Run Completeness Enforcement

**Priority:** `Now`

### What this feature is

Turn planning contracts into actual guardrails around incomplete or misleading runs.

This includes:

- validating minimum expected outputs where useful
- refusing invalid handoff states
- making run incompleteness visible early

### Why it exists in the design

The design already models expected outputs and run contracts. Those are only valuable if failures are surfaced clearly.

### Layers involved

- Layer 0
- layer validation gates
- handoff exporter

### Current implementation

Implemented:

- manifests carry `output_contract`
- individual layers have validation gates
- the active output contract was aligned on 2026-05-12 to the real run-scoped layer outputs
- `pipeline.py` now enforces each layer's minimum required artifacts and honors the layer's existing validation report
- stale manifest contracts now fail clearly instead of falling back
- handoff exporter now refuses missing Layer 3 handoff inputs

Missing or incomplete:

- Layer 0 `minimum_expected_documents` is still not enforced as a centralized runner threshold
- contract enforcement is intentionally minimal and only covers core artifacts, not every derivative file
- some expected run-state completeness checks remain distributed inside per-layer validation gates rather than one shared contract engine

### Why it was deferred earlier

From the implementation decisions:

- output contract fields were treated as planning aids, not enforcement mechanisms
- per-layer validation was prioritized first

### Why build it now

- the repo now has enough layers built that incomplete-run behavior causes confusion
- users are already encountering partial-run export situations

### What “done” should mean

- incomplete runs fail in predictable places with helpful reasons
- handoff/export tools do not silently generate misleading artifacts
- contract enforcement is strong enough to prevent “looks complete but isn’t” states
- optional later work can add threshold-style checks without replacing the current lightweight enforcement model

### Status note

The lightweight enforcement layer is now implemented for the active path. The remaining work here is broader shared policy, not the existence of completeness guardrails.

---

## 12. Story Intelligence and Recurrence Upgrades

**Priority:** `Next`

### What this feature is

Strengthen the system’s ability to understand how stories relate over time, not just within one run.

This includes:

- topic recurrence
- story families
- previous story IDs in processing
- future memory-assisted clustering
- revisiting near-duplicate strategy if corpus diversity changes

### Why it exists in the design

The design expects future layers and memory to reason about:

- previous coverage
- recurring story lines
- follow-up evolution
- durable themes that may become evergreen or comparison candidates

### Layers involved

- Layer 3
- Layer 5
- Layer 6
- Layer 10
- Layer 1 later through follow-up source targeting

### Current implementation

Implemented:

- Layer 3 does exact duplicate detection
- Layer 10 stores story coverage, followups, and entity/topic memory

Missing:

- explicit story-family machinery
- memory-fed recurrence support back into Layer 3
- richer follow-up clustering / recurrence-aware story processing

### Why it was deferred earlier

- observed data was well handled by exact URL dedup and current clustering
- the first priority was producing usable story clusters and editorial candidates

### Why build it next

- it becomes more valuable as the archive grows
- it helps follow-up, evergreen, and comparison strategy paths

### What “done” should mean

- the system can recognize when a story is part of an ongoing family
- later runs can see prior family context without manual joining
- follow-up/evergreen/comparison routing gains better historical grounding

---

## 13. Manifest Authority and Config Ownership Cleanup

**Priority:** `Now`
**Status:** Active runtime implementation completed on 2026-05-12. Remaining work is standalone/inactive utility cleanup plus adjacent LLM-runtime/logging work.

### What this feature is

Make the Layer 0 run manifest the actual runtime control plane for the whole pipeline.

This means:

- Layer 0 reads authoring config once
- Layer 0 writes the resolved run-scoped snapshot into the manifest
- downstream layers stop re-reading original config files directly

### Why it exists in the design

The Layer 0 design is explicit that downstream layers should read one `run_manifest.json`, not separately read random config files.

This is the mechanism that makes a run:

- reproducible
- auditable
- safe from mid-run config edits

### Layers involved

- Layer 0
- Layer 1
- Layer 3
- Layer 5
- Layer 7
- Layer 8
- Layer 9
- `chatgpt_export.py`
- the shared LLM runtime path

### Current implementation

Implemented:

- Layer 0 already assembles the main run manifest
- Layer 1 now uses the manifest for collection windows, enabled source groups, and query themes
- Layer 0 now writes `resolved_config` snapshots for source registry, YouTube channels, LLM runtime, entity/topic taxonomy, and ChatGPT handoff prompts
- Layer 1 now reads source/channel registry data from manifest snapshots in the active path
- Layer 3 now reads entity/topic taxonomy from the manifest in the active path
- Layer 5 now reads effective format requirements from the manifest in the active path
- active LLM modules in Layers 4, 5, 7, 8, and 9 now read manifest-backed runtime profiles
- `chatgpt_export.py` now reads manifest-backed handoff prompt config

Missing or incomplete:

- some standalone or inactive utilities still read config directly
- Layer 0 authoring helpers still read config directly by design
- unified provider abstraction is still a separate unfinished feature

### Why it was deferred earlier

From the implementation decisions and current code shape:

- the initial goal was to make the workflow function end-to-end first
- existing helpers were easier to wrap than to fully convert to manifest snapshots
- some config reads looked harmless while the system was still evolving quickly

### Why it mattered now

- the architecture intent was already clear in the design docs
- the pipeline had become stable enough that control-plane cleanup was worth doing
- this reduces hidden drift between runs and makes debugging much easier
- it also sets up the future unified LLM runtime work on a cleaner foundation

### What “done” should mean

- Layer 0 is the only place that resolves authoring config into run behavior
- downstream layers consume the manifest plus upstream artifacts
- resolved run-scoped snapshots exist for:
  - source registry subset
  - YouTube channel subset
  - format requirements
  - effective LLM profiles and module overrides
  - handoff strategy if needed
- direct config reads in downstream runtime paths are either removed or explicitly justified as global infrastructure

### Key files

- `pipelines/layer_0_control/run_manifest_builder.py`
- `config/policies/run_profiles.yaml`
- `config/policies/format_config.yaml`
- `config/registries/sources.yaml`
- `config/policies/source_strategy.yaml`
- `config/registries/channels.yaml`
- `config/policies/chatgpt_prompts.yaml`
- `config/registries/entity_topic_taxonomy.yaml`
- `config/llm_config.py`
- `docs/reference/manifest_authority_and_config_ownership.md`

---

## Suggested Build Order

### Phase 1 — Core system completion

1. Cross-run memory feedback loop completion
2. Verification and provenance hardening
3. Compiled run-state / run-graph artifact
4. Strategy-driven ChatGPT handoff system
5. Story intelligence and recurrence upgrades

### Phase 2 — Strengthen supported strategy path

1. Multi-format expansion beyond supported profiles
2. richer Layer 1 source/channel selection
3. future provider abstraction in the shared async LLM runtime

### Phase 3 — Expand strategic surface area

1. additional strategy families and multi-channel support

## Related docs

- [System Audit — 2026-05-12](../audits/2026-05-12_system_audit.md)
- [Run Dataflow and Run-State Recommendation](../reference/run_dataflow_and_run_state.md)
- [Manifest Authority and Config Ownership](../reference/manifest_authority_and_config_ownership.md)
- [Run Profile Control Plane](../reference/run_profile_control_plane.md)
- [LLM Log Layout](../reference/llm_log_layout.md)
- [Layer Output Map](../reference/layer_output_map.md)
