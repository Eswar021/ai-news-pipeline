AI Content Creation — Rebuild Instructions

This file is loaded automatically at the start of every Codex session for this
repository. Treat it as the standing engineering contract for future work.

Before planning or building new pipeline code, read:
- `docs/rebuild/system_blueprint.md`
- `docs/rebuild/l0_l1_decisions.md`
- `docs/rebuild/pipeline_v2_application_architecture.md` when working in
  `src/pipeline_v2/`

The current `pipelines/`, `config/`, `memory/`, and historical `data/runs/`
trees are the legacy system. They are useful for reference, but they are not
the target architecture for new work.

## Rebuild Goal

We are rebuilding this project into a simpler, cleaner, fresh pipeline.

Build new architecture under `src/`.

Do not extend the old system unless the user explicitly asks for maintenance on
legacy code. When building new functionality:
- use the old repo only as reference
- do not copy old complexity forward by default
- do not import new code from legacy `pipelines/`
- prefer rewriting a clean direct version over adapting a tangled old module

## Active Pipeline Versions

There are now two rebuild pipeline tracks:

- `src/pipeline/` is the stable v1 rebuild runtime. Keep it working and do not
  reorganize it for v2 unless the user explicitly asks.
- `src/pipeline_v2/` is the experimental application-oriented rewrite. New
  modularization work should happen here.

When changing v2:
- treat v1 as the working reference implementation
- reuse v1 code when it is useful, but adapt it to the v2 contract
- do not make v2 import runtime modules from `src.pipeline.*` after a component
  has been migrated
- keep v2 changes isolated from v1 unless a bug fix is intentionally shared

## Pipeline v2 Application Rules

Pipeline v2 is grouped by functionality, not by layer number. Each major
function should behave like a small application with one explicit trigger.

Target v2 shape:

```text
src/pipeline_v2/
├── apps/
│   ├── news_collection/
│   ├── evidence_prep/
│   ├── story_mapping/
│   ├── fact_packet/
│   ├── editorial_selection/
│   ├── content_packaging/
│   ├── script_generation/
│   ├── verification/
│   └── memory_update/
└── shared/
```

For now, do not add a central `src/pipeline_v2/runner.py`. Individual v2 apps
are exercised through `output_v2/v2_apps_workbench.ipynb` while the app
contracts stabilize.

V2 clarification rule:
- do not assume new orchestration, runner, notebook, output folder, config
  location, or deletion behavior when the user has not specified it
- if a v2 decision changes how an app is invoked, where app outputs are written,
  whether an old copied folder is removed, or whether config is app-local, ask
  the user before implementing
- prefer one short clarification over building temporary compatibility code the
  user did not ask for

Each app should expose a core entrypoint like:

```python
def run(input_json: dict) -> dict:
    ...
```

Core app rules:
- accept only JSON/dict input at the application boundary
- return one JSON/dict result containing the main data and summary
- keep file reads, file writes, CLI parsing, and run-folder paths in adapters or
  orchestration code, not in the app core
- own app-local config, contracts, utils, prompts, and collectors when they are
  specific to that function
- use `shared/` only for genuinely universal helpers and contracts
- keep behavior config-driven through the input/config contract
- do not hardcode daily story names, one-off company names, article titles,
  current-run examples, thresholds, model names, prompt versions, source caps,
  or editorial rules in application code
- if a value affects behavior, pass it through config or the app input envelope
- fail loudly when required config, prompts, inputs, or schema fields are
  missing

Reuse policy for v2:
- do not regenerate the whole system from scratch just because the folder shape
  is changing
- copy or move existing v1 modules into the relevant v2 app when the logic is
  still valid
- refactor copied code only as needed to remove global filesystem/config
  dependencies and satisfy the JSON/dict app contract
- prefer small, reviewable migrations such as `news_collection` first, then
  `evidence_prep`, then later apps

## Target Project Shape

```text
src/
├── config/
│   ├── paths.py
│   ├── l0_config.yaml
│   ├── l1_config.yaml
│   └── l<n>_config.yaml        # only when a later layer truly needs its own policy
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

Important:
- this is the target end-state shape
- do not prebuild every config file and every layer directory on day one
- build the system incrementally, layer by layer
- only add config for a layer when that layer is actually being implemented
- for the first rebuild slice, keep `src/config/` declarative
- `src/config/paths.py` should hold path constants only, not manifest/date/yaml helper logic

## Core Architecture Rules

### 1. One-way data flow
- each layer reads:
  - `run_manifest.json`
  - the prior layer's main data file
- each layer writes:
  - one main data file
  - one `summary.json`
  - `llm_calls.jsonl` only if that layer uses an LLM

### 1A. Carry state forward, do not rejoin backward
- each layer should carry forward the upstream data the next layer will need
- for now, duplication is acceptable if it keeps the next layer self-contained
- do not force downstream layers to reopen older layer folders to recover context
- treat each layer as its own small application with one explicit input artifact and one explicit output artifact

### 2. No backward reads
- downstream layers should not reopen arbitrary older layer folders
- if a downstream layer needs something, the intermediate layer should carry it forward

### 2A. Shape changes are expected
- the output shape is allowed to change when the unit of work changes
- do not keep pretending everything is still a document record after the pipeline becomes story-centric or package-centric
- the important rule is continuity of state, not identical schema forever

### 3. Config is frozen in L0
- authoring config lives in `src/config/`
- runtime config lives only in `run_manifest.json`
- no layer except L0 reads yaml directly
- keep `src/config/` declarative; if a layer needs non-path helper logic, keep it in that layer's runner or layer-local modules

### 3A. Config is added only when needed
- do not create config files for future layers just because we expect those layers to exist later
- when only `L0-L2` exist, the manifest should only carry the config those layers actually need
- as new layers are implemented, extend the manifest and config surface at that time
- do not copy old-system yaml structure into the rebuild preemptively
- for the initial `L0/L1` build, follow `docs/rebuild/l0_l1_decisions.md` as the concrete config and manifest contract

### 4. No silent fallbacks
- missing config key: fail
- missing input file: fail
- stale manifest shape: fail
- missing prompt file: fail

### 5. Keep contracts lean
- avoid report sprawl
- avoid multiple overlapping outputs that say nearly the same thing
- prefer one rich structured artifact over many debug artifacts

### 6. Use LLMs only where they add real value
- collection, normalization, joins, routing, and validation should be rule-based unless LLMs are truly necessary
- do not create one LLM call per tiny fragment if a document-level call is sufficient

### 6A. Use LLMs for meaning; use code for stable guardrails
- do not hardcode daily story text, one-off company names, article titles, or current-run examples into code
- LLMs should interpret meaning: story labels, viewer value, editorial angle, why a story matters, blocked angles, and script usefulness
- code should enforce stable rules: manifest choices, source trust and relationship, provenance requirements, evidence thresholds, selection caps, diversity limits, format contracts, segment roles, and timing budgets
- the good pattern is: LLM returns structured judgment with reasons, then code applies deterministic guardrails
- the bad pattern is: keyword mazes, title-specific if-statements, or one-run fixes pretending to understand the story
- when a current run exposes a quality problem, generalize it through durable properties such as source type, evidence strength, content mismatch, format fit, or provenance quality

### 7. No premature abstractions
- no plugin-style layer registries
- no dynamic dispatch systems
- no base classes unless multiple real callers justify them

### 7A. A layer is one application, not one file
- a layer may contain multiple internal modules when the logic genuinely splits into real processing steps
- `runner.py` remains the single obvious entrypoint for the layer
- internal modules should map to real work such as loading, resolving, writing, or source-specific collection
- avoid both extremes:
  - one giant unreadable runner
  - too many tiny files and frameworky indirection
- prefer a small number of direct modules over abstraction-heavy designs
- for small layers, start with one `runner.py`
- split a layer only after the code proves a real readability gain

## Target Layer Intent

## Working State Shapes

There are four primary state shapes in the rebuild:

### Record state
- unit: one collected document / transcript / article / post
- layers: `L1`, `L2`

### Story state
- unit: one clustered story with its supporting records carried inside it
- layers: `L3`, `L4`, `L5`

### Production state
- unit: one selected video / package with all needed planning and factual context
- layers: `L6`, `L7`

### Decision state
- unit: one verified or revisable publish package
- layers: `L8`, `L9`

When the pipeline moves from one state shape to another, it is correct to
restructure the top-level object. Keep the new object self-contained enough that
the next layer does not need to read backward.

### Format-aware path after L4
- `L0-L4` are the shared evidence trunk for every video type
- `L5` decides or receives the target video format, such as `auto`, `roundup`, or `deep_dive`
- from `L5` onward, layers may branch internally by format when the work genuinely differs
- do not create separate full 10-layer pipelines per video type
- keep one layer contract and one main artifact per layer, even when internal format modules exist
- use format-specific code for stable structure and format-specific prompts for meaning and narration
- add format-specific modules only when the implemented layer needs them; do not prebuild empty branches

### L0 — Manifest
- snapshot all config into one run manifest
- for the first slice, resolve only channel scope, run profile, source scope, and collection window
- only include config for layers that currently exist in the rebuild
- should stay in one `runner.py` while it is still small
- split only if the manifest logic becomes materially harder to read in one file
- do not write a separate audit snapshot like `run_config_snapshot.json` unless a real operator need appears later
- also write `output/current_manifest.json` as a latest-run convenience copy

### L1 — Collection
- collect raw source records into one flat list
- no editorial decision here
- is expected to be multi-module because collectors naturally separate by source or source family
- write collected raw records to the main data file
- keep common fields flat on the record itself; avoid hiding collector/source fields in a nested `metadata` dict
- L1 may apply source-scope filtering that is intrinsic to collection, but manifest-window exclusion and downstream keep/drop decisions belong in L2
- if a collector fetches first and filters during collection, the summary should report both fetched and collected counts clearly
- do not introduce trust-tier-derived ideas like "primary docs" in the first slice unless they materially affect collection behavior

### L2 — Evidence Prep
- clean, normalize, soft-dedup, and build provenance-ready records
- preserve enough text for later factual grounding
- keep record state and output only the cleaned records that should continue downstream
- keep exclusion visibility in `summary.json` instead of carrying excluded records forward in the main `L2` data file
- do not create clusters here; `L3` is the first story-shaping layer

### L3 — Story Map
- cluster documents into stories
- `L2` owns duplicate removal; do not re-create exact-match dedup in `L3`
- use strict semantic embedding grouping for clear same-story coverage, not plain keyword grouping
- if LLM labels are used, apply them after clustering to describe and rank story objects, not as hard per-record merge gates
- story labels should capture entity, product/project, action, story type, and editorial value rather than loose keyword tags
- rank stories
- keep this layer about story identity, not script writing
- output should move from record state to story state

### L4 — Fact Packet
- document-first extraction of verified facts per story
- produce one authoritative fact contract for downstream use

### L5 — Editorial
- decide whether to make a video
- decide or respect the target format, such as `auto`, `roundup`, or `deep_dive`
- choose the story or story set that fits that format
- produce one `selected_video_brief.json`
- keep selected L4 fact packets carried forward so L6 does not read backward

### L6 — Package
- assemble the selected brief into a format-specific research/content packet
- this layer can merge planning context that used to be spread across multiple layers
- output should move from story state to production state
- do not rely on prompt changes alone when the format needs different structure

### L7 — Script
- generate format-specific narration and metadata from the L6 package
- keep spoken narration separate from visual/editor notes
- keep roundup, deep-dive, and future script shapes explicit when their structure genuinely differs

### L8 — Verify
- verify script support and policy compliance
- output either approved deliverables or a revision package
- output should move from production state to decision state

### L9 — Memory
- update durable memory from approved runs
- post-publish sync can remain a separate workflow, but memory contracts should live here

## Output Philosophy

Per run:
```text
output/{run_id}/run_manifest.json
output/{run_id}/L1/<data>.json
output/{run_id}/L1/summary.json
...
```

Allowed third file for LLM layers only:
```text
output/{run_id}/L{N}/llm_calls.jsonl
```

Do not recreate the current pattern of many semi-duplicate artifacts unless the
user explicitly asks for them.

For now, carrying forward duplicated upstream context is acceptable if it keeps
each layer independent and understandable. Prefer duplication over backward
dependency.

## Build Order Policy

- build the rebuild sequentially
- implement the current layer and only the config it genuinely needs
- let `run_manifest.json` grow over time as the pipeline grows
- avoid writing speculative config for layers that are not implemented yet
- avoid pretending we already know the final config surface for later layers

## Prompt Policy

- prompt text lives in versioned files, not inline in Python
- code may interpolate dynamic data, but durable instruction text belongs in prompt files
- prompt version selection is manifest-driven

## Legacy System Policy

Legacy folders include:
- `pipelines/`
- `config/`
- `memory/`
- historical `data/runs/`
- `data/`

Use them for:
- understanding domain requirements
- seeing what data was useful
- comparing outputs

Do not use them for:
- copying architecture blindly
- importing new runtime code
- preserving old artifact sprawl
- writing new rebuild outputs

## Runner Policy

- the main runner should be explicit
- avoid silent defaults for important run choices
- require the operator to be clear about run profile and layer range whenever practical
- the runner should make the layer flow easy to discover even when the layer has several internal modules

## What Success Looks Like

A new engineer should be able to open a layer runner and understand:
- what it reads
- what it writes
- why it exists
- where the LLM is used
- what the next layer receives

If a design makes that hard, simplify it before building.
