# Pipeline v2 Application Architecture

This document is the standing architecture contract for `src/pipeline_v2/`.
Pipeline v2 starts from the working v1 rebuild code, but it changes the module
boundary from "numbered layer runner" to "functional application."

## Current Status

`src/pipeline/` is the stable v1 rebuild runtime.

`src/pipeline_v2/` is the experimental v2 workspace. It was initially copied
from v1 so the working logic is available for reuse. Do not treat the copied
layer folders as the final v2 architecture.

## Goal

Each v2 module should be a small self-contained application:

- one clear trigger
- one JSON/dict input contract
- one JSON/dict output contract
- app-local config, contracts, utils, prompts, and source-specific modules
- no hidden dependency on run folders, current manifest files, or global config
  reads inside the app core

The orchestrator can still load files and write outputs, but the app itself
should be callable in memory with a dictionary.

## Target Tree

```text
src/pipeline_v2/
|-- apps/
|   |-- news_collection/
|   |   |-- app.py
|   |   |-- config.py
|   |   |-- contract.py
|   |   |-- utils.py
|   |   `-- collectors/
|   |-- evidence_prep/
|   |-- story_mapping/
|   |-- video_packaging/
|   |-- script_generation/
|   |-- metadata_creator/
|   |-- verification/
|   `-- memory_update/
`-- shared/
    |-- io.py
    |-- contracts.py
    `-- run_context.py
```

There is intentionally no central `src/pipeline_v2/runner.py` yet. During the
early v2 migration, use notebooks under `output_v2/` to build app inputs, call
individual apps, and write notebook-run outputs.

Create subfolders only when the app is actively being migrated. Do not prebuild
empty applications.

## Clarification Rule

For v2, ask before implementing any unclear orchestration or boundary choice.

Do not assume:

- a central runner should exist
- an app should write files directly
- notebook outputs should use a specific folder shape
- config should be shared or app-local
- old copied layer folders should be kept, deleted, or shimmed
- a compatibility adapter should be added for downstream layers

If the user has not specified one of those choices, stop and clarify before
writing code.

## Application Contract

Each app should expose:

```python
def run(input_json: dict) -> dict:
    ...
```

The app may split internally into modules, but `app.py` should remain the
obvious functional entrypoint.

The preferred input envelope is:

```json
{
  "run": {
    "run_id": "run_...",
    "generated_at": "ISO-8601 timestamp"
  },
  "config": {},
  "input": {}
}
```

The preferred output envelope is:

```json
{
  "status": "ok",
  "data": {},
  "summary": {},
  "handoff": {}
}
```

The exact `data` shape may change by app. Continuity matters more than forcing
every stage to pretend it still has the same object type.

## File I/O Boundary

Core app code should not:

- read `output/current_manifest.json`
- read `output/{run_id}/...` directly
- write durable artifacts directly
- import `OUTPUT_DIR`, `CURRENT_MANIFEST_PATH`, or other path globals
- parse CLI arguments

Those responsibilities belong in:

- notebooks under `output_v2/` during the early app migration
- app-specific adapters, if needed later
- small shared I/O helpers used only outside the app core

This keeps each app testable with plain Python dictionaries.

## Config Ownership

Pipeline v2 must stay config-driven.

If a value changes behavior, it belongs in one of these places:

- the app input envelope under `config`
- an app-local config object resolved into that envelope
- a prompt file selected by config
- a notebook-built config snapshot passed into the app

Do not hardcode:

- daily story text
- company names or article titles from a current run
- source caps
- score thresholds
- selected formats
- model names
- prompt versions
- editorial rules
- verification severity policy

Durable rules belong in config or contracts. Code should enforce them after
they are resolved, not invent them inline as one-off constants.

## LLM and Prompt Policy

Apps that use LLMs should own their prompt selection at the app boundary, but
the durable prompt text must live in prompt files.

The app input config should specify:

- model or model profile
- prompt name
- prompt version
- worker/concurrency settings when relevant
- logging behavior

The app should use LLMs for meaning and code for guardrails:

- LLM: labels, viewer value, editorial judgment, factual interpretation,
  rewrite suggestions
- code: schema validation, source caps, evidence thresholds, provenance
  requirements, output shape, timing budgets, status decisions

## Reuse-First Migration

Do not rewrite the whole pipeline from scratch.

When migrating a function:

1. Identify the v1 files that already implement useful behavior.
2. Copy or move those files into the relevant `apps/<function>/` folder.
3. Replace absolute imports from `src.pipeline.*` with app-local or
   `src.pipeline_v2.shared.*` imports.
4. Move app-specific helpers into the app folder.
5. Keep only genuinely universal helpers in `shared/`.
6. Convert the core entrypoint to `run(input_json: dict) -> dict`.
7. Keep file I/O in notebooks or future adapter code.
8. Add validation for required config and input keys.

The goal is not a cosmetic folder shuffle. The goal is a cleaner callable
contract around working logic.

## Functional App Map

Initial mapping from v1 layers to v2 apps:

```text
L1_collection      -> apps/news_collection
L2_evidence_prep   -> apps/evidence_prep
L3_story_map       -> apps/story_mapping
L4/L5/L6 package   -> apps/video_packaging
L7_script          -> apps/script_generation
L7 metadata        -> apps/metadata_creator
L8_verify          -> apps/verification
L9_memory          -> apps/memory_update
```

`L0_manifest` should become orchestration/config snapshot logic rather than a
business app. During the notebook-first phase, keep that logic outside app
cores until the v2 runtime contract is clearer.

## Migration Order

Migrate one function at a time:

1. `news_collection`
2. `evidence_prep`
3. `story_mapping`
4. `video_packaging`
5. `script_generation`
6. `metadata_creator`
7. `verification`
8. `memory_update`

After each migration, the app should be runnable with an in-memory dict and,
where practical during this phase, through the shared `output_v2/` workbench
notebook.

## Success Criteria

A v2 app is considered migrated when:

- `app.py` exposes `run(input_json: dict) -> dict`
- required input/config keys are validated
- file I/O is outside the core app
- app-specific config and helpers live with the app
- no migrated app imports from `src.pipeline.*`
- output contains one main `data` object and one `summary`
- LLM calls, if any, use config-selected prompt files
- no run-specific facts or one-off examples are hardcoded in code
