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
2. Cross-run memory feedback loop completion
3. Publication lifecycle and YouTube analytics ingestion
4. Repetition and similarity safety
5. Multi-format expansion beyond roundup and deep dive
6. Unified async LLM runtime, provider abstraction, and observability
7. Verification and provenance hardening
8. Compiled run-state / run-graph artifact
9. Strategy-driven ChatGPT handoff system
10. Output contract and run completeness enforcement
11. Story intelligence and recurrence upgrades

## Priority Summary

### Build now

- Manifest-driven collection control and source orchestration
- Cross-run memory feedback loop completion
- Publication lifecycle and YouTube analytics ingestion
- Repetition and similarity safety
- Unified async LLM runtime, provider abstraction, and observability
- Output contract and run completeness enforcement

### Build next

- Verification and provenance hardening
- Compiled run-state / run-graph artifact
- Strategy-driven ChatGPT handoff system
- Story intelligence and recurrence upgrades

### Build later

- Multi-format expansion beyond roundup and deep dive

This one is important to the full design, but it should be built after the current supported strategy path is stronger.

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
- Layer 1 reads enabled source groups and query themes

Missing or incomplete:

- Layer 1 does not fully enforce manifest time windows
- collector dispatch still relies on fixed-style limits and default behaviors
- YouTube is configured but skipped in the main orchestrator
- Layer 10 source-priority feedback is not yet fed back into Layer 1

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
- `channels.yaml` is wired into run execution cleanly
- YouTube collection is an orchestrated source group, not a manual side path
- future Layer 10 source-priority and watchlist guidance can influence Layer 1 query/collection policy

### Key files

- `config/run_defaults.yaml`
- `config/source_strategy.yaml`
- `config/sources.yaml`
- `config/channels.yaml`
- `pipelines/layer_0_control/time_window_resolver.py`
- `pipelines/layer_1_extraction/run_layer_1.py`

---

## 2. Cross-Run Memory Feedback Loop Completion

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

## 3. Publication Lifecycle and YouTube Analytics Ingestion

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

Missing:

- publish-state updater
- channel sync path
- performance-memory ingestion
- real analytics-driven learning loop

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
- `performance_memory.jsonl` has a supported ingestion path
- memory snapshot/index rebuild automatically after publication-state changes

### Key files

- `pipelines/layer_10_memory_learning/video_memory_writer.py`
- `pipelines/layer_10_memory_learning/memory_snapshot_builder.py`
- `pipelines/layer_10_memory_learning/learning_signal_builder.py`

---

## 4. Repetition and Similarity Safety

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

Missing:

- Layer 9 `repetition_safety_checker.py`
- richer Layer 7 direct memory use for title/hook repetition avoidance
- explicit takeaway/thumbnail repetition checks

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
- future `repetition_safety_checker.py`

---

## 5. Multi-Format Expansion Beyond Roundup and Deep Dive

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

- `config/format_config.yaml`
- `pipelines/layer_5_editorial_intelligence/*`
- `pipelines/layer_6_research_packets/*`
- `pipelines/layer_7_content_planning/*`
- `pipelines/layer_8_script_generation/*`
- `pipelines/layer_9_verification_firewall/*`

---

## 6. Unified Async LLM Runtime, Provider Abstraction, and Observability

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
- some active modules read that config correctly

Missing:

- shared async client wrapper
- full provider abstraction for the active async path
- complete LLM logging for the active pipeline

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

### Key files

- `config/llm_config.py`
- `llm/llm_client.py`
- `llm/llm_logger.py`
- active async LLM modules in Layers 4, 5, 7, 8, and 9

---

## 7. Verification and Provenance Hardening

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

## 8. Compiled Run-State / Run-Graph Artifact

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

## 9. Strategy-Driven ChatGPT Handoff System

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

## 10. Output Contract and Run Completeness Enforcement

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
- handoff exporter now refuses missing Layer 3 handoff inputs

Missing or incomplete:

- output contract and minimum document expectations are still largely decorative
- some expected run-state completeness checks are not centralized

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

---

## 11. Story Intelligence and Recurrence Upgrades

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

## Suggested Build Order

### Phase 1 — Core system completion

1. Manifest-driven collection control and source orchestration
2. Cross-run memory feedback loop completion
3. Publication lifecycle and YouTube analytics ingestion
4. Repetition and similarity safety
5. Unified async LLM runtime, provider abstraction, and observability
6. Output contract and run completeness enforcement

### Phase 2 — Strengthen supported strategy path

1. Verification and provenance hardening
2. Compiled run-state / run-graph artifact
3. Strategy-driven ChatGPT handoff system
4. Story intelligence and recurrence upgrades

### Phase 3 — Expand strategic surface area

1. Multi-format expansion beyond roundup and deep dive

## Related docs

- [System Audit — 2026-05-12](../audits/2026-05-12_system_audit.md)
- [Run Dataflow and Run-State Recommendation](../reference/run_dataflow_and_run_state.md)
- [Layer Output Map](../reference/layer_output_map.md)
