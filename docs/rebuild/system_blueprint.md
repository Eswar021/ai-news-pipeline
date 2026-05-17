# System Rebuild Blueprint

This document defines the target architecture for the fresh rebuild of the AI
content system. It is intentionally simpler than the current legacy pipeline.

For the first active rebuild slice, also read:
- `docs/rebuild/l0_l1_decisions.md`

## Why We Are Rebuilding

The current system has valuable ideas:
- manifest-driven runtime
- strong provenance
- verification before memory
- publishing and performance feedback

But it also accumulated too much structural complexity:
- too many layers
- too many artifacts per layer
- too many advisory configs that do not actively drive runtime
- too many places where intent is spread across code, prompts, and yaml

The rebuild should preserve only the parts that matter to output quality and
operational trust.

## Reference Project Lessons

The `Stock_Researcher` project is a good reference because it gets a few things
very right:
- one clear runner
- one manifest step
- one main data file per layer
- simple, numbered layer boundaries
- no backward dependency maze
- strong "reference old system, but build fresh" discipline

We should copy those architectural principles, not the domain logic.

## Target Pipeline

```text
L0  Manifest
L1  Collection
L2  Evidence Prep
L3  Story Map
L4  Fact Packet
L5  Editorial
L6  Package
L7  Script
L8  Verify
L9  Memory
```

This is the target end-state pipeline, not a requirement to build everything at
once. The rebuild should grow sequentially. If only `L0-L2` exist, then only
those layers and their configs should exist in the active rebuild.

## State Transition Model

The rebuild uses four primary working-state shapes.

### 1. Record state
- unit: one collected document / transcript / article / post
- layers: `L1`, `L2`

### 2. Story state
- unit: one clustered story that carries its relevant supporting records inside it
- layers: `L3`, `L4`, `L5`

### 3. Production state
- unit: one selected video/package with all required planning and factual context
- layers: `L6`, `L7`

### 4. Decision state
- unit: one verified or revisable publish package
- layers: `L8`, `L9`

Important rule:
- the pipeline should carry state forward layer by layer
- the top-level shape may change when the unit of work changes
- downstream layers should not need to reopen older layers to rebuild context
- for now, duplication is acceptable if it keeps each layer self-contained

This means we prefer:
- record list -> richer record list
- richer record list -> story objects
- story objects -> selected production package
- production package -> verification decision package

Not:
- a thin downstream artifact that forces later layers to join back to multiple old outputs

## Layer Contracts

## Incremental Build Rule

Build only what the current layer needs.

- do not create config files for future layers just because the legacy system had them
- do not pre-populate the manifest with speculative keys for unbuilt layers
- do not guess the final schema of later layers too early
- add new config only when a new layer genuinely requires runtime policy

This means:
- early rebuild stages may have a very small manifest
- the manifest should grow as new layers are added
- the config surface should stay small until real use cases force it to expand

For the first active rebuild slice:
- use only `src/config/settings.py`, `src/config/l0_config.yaml`, and `src/config/l1_config.yaml`
- do not recreate horizontal config files from the legacy system yet
- follow `docs/rebuild/l0_l1_decisions.md` as the concrete `L0/L1` contract

### L0 — Manifest
Reads:
- authoring config in `src/config/`

Writes:
- `output/{run_id}/run_manifest.json`

Purpose:
- freeze all runtime decisions before any downstream execution
- include only the config required by currently implemented layers
- do not write a separate audit snapshot unless a real operator need appears later

### L1 — Collection
Reads:
- manifest

Writes:
- `raw_records.json`

Purpose:
- collect source records only
- write only kept downstream records to the main data file
- make fetch-versus-kept counts explicit in the summary when collectors must filter after fetch

### L2 — Evidence Prep
Reads:
- manifest
- `L1/raw_records.json`

Writes:
- `prepared_records.json`

Purpose:
- clean, normalize, dedup, reliability-tag, preserve provenance-ready text
- keep record state, carrying forward enough upstream data for story building

### L3 — Story Map
Reads:
- manifest
- `L2/prepared_records.json`

Writes:
- `stories.json`

Purpose:
- group records into ranked story objects
- transition from record state to story state
- each story should carry the record context needed by the next layer

### L4 — Fact Packet
Reads:
- manifest
- `L3/stories.json`

Writes:
- `fact_packets.json`

Purpose:
- extract and verify story facts in a document-first way
- keep story state, now enriched with authoritative factual grounding

### L5 — Editorial
Reads:
- manifest
- `L4/fact_packets.json`
- memory context if needed

Writes:
- `editorial_decision.json`

Purpose:
- decide whether to make a video, in what format, from which stories
- keep enough story-state context in the decision output so packaging does not read backward

### L6 — Package
Reads:
- manifest
- `L5/editorial_decision.json`

Writes:
- `content_packet.json`

Purpose:
- build the compact packet the writer actually needs
- transition from story state to production state

### L7 — Script
Reads:
- manifest
- `L6/content_packet.json`

Writes:
- `script_package.json`

Purpose:
- generate spoken narration, metadata, and structured visual notes
- keep production state, carrying forward all context needed for verification

### L8 — Verify
Reads:
- manifest
- `L7/script_package.json`

Writes:
- `verification_package.json`

Purpose:
- approve, block, or request revision
- transition from production state to decision state

### L9 — Memory
Reads:
- manifest
- `L8/verification_package.json`

Writes:
- `memory_update.json`

Purpose:
- update durable memory from approved runs

## Key Simplification Decisions

### 1. Fewer durable artifacts
Each layer should produce one main artifact plus summary. Rich internal state
can exist in memory while the layer runs, but it should not automatically become
a durable file.

This does not mean downstream layers should be starved of context. It means each
layer should produce one self-contained working-state artifact rather than many
partial artifacts.

### 2. Document-first factual extraction
We should not return to span-first extraction. Chunk only when model limits force
it, then merge back into one document result.

### 3. Fact contract over debug artifact sprawl
Downstream layers should consume one authoritative fact object, not several
parallel files that each partially describe evidence.

### 3A. Prefer duplication over backward dependency
If the next layer needs upstream context, carry it forward inside the new main
artifact even if that duplicates some data. The cost of duplication is lower
than the cost of multi-layer joins and hidden dependency chains.

### 3B. One layer can still have multiple modules
The rebuild should keep one application per layer, but that does not mean one
file per layer.

Use multiple modules when they map to real steps in the layer, for example:
- `runner.py`
- `loader.py`
- `resolver.py`
- `writer.py`
- `collectors/<source>.py`

Avoid:
- turning one simple layer into many tiny files with little value
- introducing plugin registries, dynamic dispatch, or base classes too early

The rule is:
- one clear runner
- one clear main input artifact
- one clear main output artifact
- as many internal modules as the logic genuinely needs

For small layers:
- start with one `runner.py`
- split only when the code clearly becomes harder to understand in one file
- do not create helper files just because a layer could theoretically be modular

### 4. Editorial choice should be small and legible
The editorial layer should answer:
- is there a video?
- which format?
- which story/story set?

It should not be a maze of near-duplicate score reports.

### 5. Script vs visual directions must stay separate
Narration is what gets verified.
Visual notes are editor metadata.
Do not mix them into one text stream.

### 6. Revision is a first-class outcome
Verification should not pretend the system crashed when it is really asking for
revision. Approved, revisable, and failed are different states.

## New Source Tree

```text
src/
├── config/
│   ├── settings.py
│   ├── run_profiles.yaml
│   ├── sources.yaml
│   ├── channels.yaml
│   ├── format_rules.yaml
│   ├── prompt_config.yaml
│   └── layer_<n>.yaml
├── llm/
│   ├── client.py
│   ├── prompt_loader.py
│   └── logger.py
└── pipeline/
    ├── runner.py
    ├── L0_manifest/
    ├── L1_collection/
    ├── L2_evidence_prep/
    ├── L3_story_map/
    ├── L4_fact_packet/
    ├── L5_editorial/
    ├── L6_package/
    ├── L7_script/
    ├── L8_verify/
    └── L9_memory/
```

## What The Legacy System Is Still Good For

Use the current repo to answer:
- which source types mattered
- which verification checks were worth keeping
- which publishing/memory feedback loops mattered
- which outputs were actually useful in debugging

Do not preserve:
- stale config vocabulary
- duplicate channel identity fields
- dead config files
- excessive cross-layer file dependence
- artifact sprawl

## Rebuild Rule

When in doubt, choose the design that a new engineer can understand in one
reading session.

For `L0` and `L1` specifically:
- `L0` should start and stay in one runner while it is still small
- only split `L0` after the code proves a real readability problem
- `L1` should be expected to use multiple modules because source collection naturally separates by collector

When choosing between:
- building a little now and extending later
- or prebuilding many future configs and abstractions

choose the smaller current build.
