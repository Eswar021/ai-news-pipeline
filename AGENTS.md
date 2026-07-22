# AI Content Creation Engineering Instructions

This file is the standing contract for work in this repository.

Before changing pipeline code, read:

- `docs/current_system_architecture.md`
- `src/pipeline/visuals/README.md` when changing visual implementation

## Canonical Runtime

`src/pipeline/` is the only active pipeline. The old numbered-layer runtime
was retired after the application-oriented system became canonical. Do not
reintroduce `pipeline_v2`, `L0-L9`, root `src/config`, root `src/llm`, or root
`src/prompts` trees.

The active shape is:

```text
src/pipeline/
├── ingestion/
│   └── news_collection/
├── content/
│   ├── evidence_prep/
│   ├── editorial_triage/
│   ├── story_mapping/
│   ├── editorial_selection/
│   ├── video_packaging/
│   ├── script_generation/
│   └── metadata_creator/
├── contracts/
├── handoffs/
├── orchestration/
├── publishing/
│   ├── metadata_finalizer/
│   └── publish_handoff/
├── voiceover/
├── visuals/
└── config/
    ├── workbench.yaml
    ├── environments/{dev|staging|prod}.yaml
    └── profiles/{profile}/{ingestion|content|voiceover|visuals|publishing}/
```

Production automation uses one thin CLI router with four explicit stage
modules:

```text
src/pipeline/orchestration/runner.py
src/pipeline/orchestration/stages/ingestion.py
src/pipeline/orchestration/stages/content.py
src/pipeline/orchestration/stages/voiceover.py
src/pipeline/orchestration/stages/visuals.py
```

The runner owns sequencing, paths, resumability, run state, and logging. It
must call existing `run(input_json)` boundaries rather than importing app
private implementation. Focused notebooks remain interactive operator and
debugging surfaces:

Launch the stage runner with the main project Python environment.
`.venv-voiceover` is a specialized synthesis runtime that the voiceover stage
invokes internally; do not activate it for content or visual orchestration.

```text
notebooks/production/content_pipeline.ipynb
notebooks/production/voiceover_generation.ipynb
notebooks/production/visual_production.ipynb
notebooks/handoffs/chatgpt_handoffs.ipynb
notebooks/labs/visual_assets_lab.ipynb
```

## Application Contract

Every functional app exposes one obvious boundary:

```python
def run(input_json: dict) -> dict:
    ...
```

Application rules:

- accept JSON/dict input only at the core boundary
- validate boundaries with Pydantic v2
- return one JSON/dict envelope with `status`, `data`, `summary`, and `handoff`
- add `llm_calls` when an app uses an LLM
- keep app-specific config, prompts, contracts, and helpers inside the app
- do not import orchestration logging/telemetry helpers or accept log-file paths;
  return diagnostics and call records for the orchestrator to persist
- keep file I/O, CLI parsing, and output paths in adapters, stage routers, or notebooks
- do not import one app's private implementation from another app
- carry forward source context needed by the next app instead of reading older outputs
- fail clearly when required input, config, prompts, or provider settings are missing

Media modules may write files because WAV, PNG, and MP4 files are their core
products. Their control boundary should still be JSON/dict-in and JSON/dict-out.

## Config Policy

Behavior must be config-driven.

- `src/pipeline/config/workbench.yaml` is the profile manifest; module authoring
  config lives below `src/pipeline/config/profiles/{profile}/{stage}/`
- `src/pipeline/config/environments/{dev|staging|prod}.yaml` contains sparse overlays;
  do not duplicate complete profile trees per environment
- deterministic fixture scenarios are test inputs, not deployment environments;
  keep them under `tests/fixtures/` and write their artifacts under `output/tests/`
- a production run stores an immutable initial composed profile in
  `run_context.json` for identity and reproducibility
- stage runners load each module's current YAML immediately before execution by
  default and write that effective config to the module's `config_snapshot.json`
- use runner `--config-mode frozen` only for exact initial-profile reproduction
- content apps receive their effective config in the input envelope
- content apps do not read YAML directly
- operator notebooks reload module YAML when the corresponding execution cell runs
- model caches live under `.cache/ai_content_creation/models/`, not output folders

Do not hardcode current-run company names, story titles, thresholds, model
names, prompt versions, source caps, output paths, or editorial rules in
application code. If a value changes behavior, make it part of config or the
input contract.

Do not silently fall back when a required config value is absent. A deliberate
fallback must be named in config and visible in the returned summary.

## Run And Output Policy

New outputs use a run-first layout:

```text
output/
├── current_run.json
├── runs/{run_id}/
│   ├── run_context.json
│   ├── news_collection/
│   ├── evidence_prep/
│   ├── editorial_triage/
│   ├── story_mapping/
│   ├── editorial_selection/
│   ├── video_packaging/
│   ├── script_generation/
│   ├── metadata_creator/
│   ├── metadata_finalizer/
│   ├── orchestration/
│   ├── voiceover/
│   └── visuals/
├── tests/
└── labs/
```

`output_v2/` is historical generated data only. New code must not write there
or use it as runtime input by default.

Each orchestrator-owned module folder should contain its input envelope, canonical
result, main package/artifact, and summary. Avoid overlapping debug artifacts.

Committed notebooks must have cleared execution counts and outputs. Do not
commit machine-specific absolute paths or generated media.

## Data Flow

The primary state transitions are:

```text
raw records
  -> prepared records plus reversible candidate/decision ledgers
  -> authoritative editorial triage with advance/reserve/quarantine decisions
  -> semantically mapped stories carrying full records
  -> LLM-selected editorial roundup slate
  -> structural video packet carrying the selected stories
  -> section-aware script package
  -> metadata draft and beat-aware voiceover
  -> audio-timed metadata finalization and visual production
  -> fingerprint-validated final video and publish review
```

The current production path intentionally does not include the retired
fact-packet layer. Script generation receives the full selected story records.
Do not add a fact-packet dependency unless a new, demonstrated requirement
justifies it.

Current handoffs must name real consumers:

- news collection -> evidence prep
- news collection and evidence prep -> authoritative editorial triage
- evidence prep plus editorial triage -> story mapping
- story mapping -> editorial selection
- editorial selection plus story mapping -> video packaging
- video packaging -> script generation
- script generation -> metadata draft and voiceover
- voiceover -> metadata finalization and visual planning
- finalized metadata plus final video -> manual publish review

## LLM Policy

Use LLMs for semantic judgment and code for stable guardrails.

Good LLM responsibilities:

- candidate relevance, uncertainty, and editorial triage
- story identity and editorial value
- episode slate selection, diversity, and editorial ordering
- episode direction, story-local beat writing, bounded targeted repair, and bookend continuity
- viewer-facing metadata
- visual direction and semantic scene planning
- contextual media suitability, identity matching, and B-roll moment selection

Good deterministic responsibilities:

- collection and normalization
- source and record provenance
- format routing and resource/selection caps after semantic choices are made
- section order, source ownership, observed timing, and audiovisual alignment checks
- Pydantic structured-output validation
- asset resolution, rendering, and assembly

Do not turn categorical script judgments into code gates. Engagement, tone,
hook quality, attribution style, claim interpretation, humor, and prose quality
belong to the LLM reviewer and human editorial review. Code may validate
structure, identity, source ownership, known references, projections,
provenance, and bounded-loop behavior, but must not approve or reject narration
with keyword lists, regexes, semantic-overlap thresholds, metric matching, or
similar prose heuristics.

Use LangChain structured output with Pydantic models where an LLM must return
structure. Keep `llm_client.py` limited to provider/model construction and keep
LLM logging separate. Prompt text belongs in versioned files, not inline Python.

Review/revision loops must have a config-driven hard maximum. Approved story
bodies must not be replaced by a whole-episode rewrite. Never allow an
unbounded agent loop.

## Script Compatibility

App-generated and manual ChatGPT scripts must use the same canonical
`script_generation_result` contract. The manual path is normalized by
`handoffs/chatgpt_script_parser`; downstream voiceover, metadata, and visuals
must not contain a second manual-script schema.

Require explicit script sections: intro, one section per selected story, then
closing. Each section carries stable audiovisual beats and source/visual
briefs; `section.narration_text` and `full_script` are deterministic
projections. Preserve section, story, and beat IDs outside spoken narration so
voiceover and visual planning never reconstruct boundaries from prose.

Script length is content-driven. Role-specific word suggestions may guide an
LLM prompt, but word counts, beat counts, and nominal episode duration are not
approval quotas. Keep observed word and estimated-duration telemetry for
inspection only. Actual synthesized voiceover timing is authoritative for
visual planning and final assembly.

Every successful canonical script must include a deterministic content
fingerprint. Voiceover, visual planning, media discovery, asset resolution,
rendering, assembly, metadata finalization, and publish handoff must propagate
and verify parent fingerprints. Never select downstream artifacts by
modification time.

## Visual Policy

Visual planning and asset/render production are separate responsibilities.

- asset cataloging turns selected source pages, source-owned hero images, and resolvable identities into story-owned asset IDs before planning
- the planner chooses renderable scene kinds against voiceover-aligned script beats; LLMs do not author raw seconds
- media discovery first resolves exact catalog asset IDs; optional external image/video research must be explicitly enabled
- semantic media verification rejects irrelevant or identity-ambiguous external candidates when that paid review path is enabled
- asset resolution obtains screenshots, logos, and discovered media
- Remotion renders short independent scene clips
- assembly joins clips and voiceover into the final video
- review creates a sampled contact sheet for required human visual inspection

Do not let a keyword search or numeric relevance score make the final semantic
asset choice. The default production profile is `trusted_only`: use selected
source pages, source-owned media, and resolvable identities without an extra
vision call, and leave unavailable external media visibly unresolved. A later
vision-review profile may be enabled deliberately when its added cost is
justified.

Visual iteration uses a low-resolution preview profile, persistent scene cache,
and optional scene/story selection. Final-quality rendering is a separate
explicit pass. Keep scene and frame concurrency bounded; do not increase worker
counts merely because more processes are available.

Avoid PPT-style cards, walls of text, decorative charts, tiny labels, and
visuals unrelated to the active narration beat. Prefer explanatory motion,
source proof, contextual media, process diagrams, comparisons, and restrained
kinetic text.

## Reuse And Clarification

Reuse working modules and notebook cells when their behavior remains valid.
Do not regenerate large components merely to change directory structure.

Ask before making a decision that changes invocation, output ownership,
deletion behavior, provider cost, or a public contract when the intended choice
cannot be determined from code and current instructions. Do not create temporary
compatibility layers for an assumption the user did not request.

## Verification

Use the committed deterministic fixture for media work:

```text
tests/fixtures/media_roundup_reference/
```

At minimum, run relevant checks:

```bash
python3 -B -m compileall src/pipeline
python3 -m pytest -q
cd src/pipeline/visuals/remotion_engine && npm run typecheck
```

For visual changes, also render the fixture or focused visual-lab examples and
inspect actual frames or clips. Metadata alone is not visual QA.
