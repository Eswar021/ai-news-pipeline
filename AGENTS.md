# AI Content Creation Engineering Instructions

This file is the standing contract for work in this repository.

Before changing pipeline code, read:

- `docs/architecture/pipeline_application_architecture.md`
- `docs/architecture/media_modules.md` for handoff, voiceover, or visual work
- `docs/architecture/visuals_roadmap.md` and `src/pipeline/visuals/README.md`
  for visual work

## Canonical Runtime

`src/pipeline/` is the only active pipeline. The old numbered-layer runtime
was retired after the application-oriented system became canonical. Do not
reintroduce `pipeline_v2`, `L0-L9`, root `src/config`, root `src/llm`, or root
`src/prompts` trees.

The active shape is:

```text
src/pipeline/
├── apps/
│   ├── news_collection/
│   ├── evidence_prep/
│   ├── story_mapping/
│   ├── video_packaging/
│   ├── script_generation/
│   └── metadata_creator/
├── handoffs/
├── orchestration/
├── voiceover/
├── visuals/
└── config/workbench.yaml
```

There is intentionally no central pipeline runner. The contracts are still
stabilizing and the operator workflows live in focused notebooks:

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
- keep file I/O, CLI parsing, and output paths in adapters or notebooks
- do not import one app's private implementation from another app
- carry forward source context needed by the next app instead of reading older outputs
- fail clearly when required input, config, prompts, or provider settings are missing

Media modules may write files because WAV, PNG, and MP4 files are their core
products. Their control boundary should still be JSON/dict-in and JSON/dict-out.

## Config Policy

Behavior must be config-driven.

- authoring config lives in `src/pipeline/config/workbench.yaml`
- a production run freezes its selected profile into `run_context.json`
- apps receive their effective config in the input envelope
- apps do not read YAML directly
- media notebooks use the frozen profile for production runs
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
│   ├── story_mapping/
│   ├── video_packaging/
│   ├── script_generation/
│   ├── metadata_creator/
│   ├── voiceover/
│   └── visuals/
├── tests/
└── labs/
```

`output_v2/` is historical generated data only. New code must not write there
or use it as runtime input by default.

Each notebook-owned module folder should contain its input envelope, canonical
result, main package/artifact, and summary. Avoid overlapping debug artifacts.

Committed notebooks must have cleared execution counts and outputs. Do not
commit machine-specific absolute paths or generated media.

## Data Flow

The primary state transitions are:

```text
raw records
  -> prepared records
  -> ranked stories carrying records
  -> selected video packet carrying stories
  -> section-aware script package
  -> metadata and media production
```

The current production path intentionally does not include the retired
fact-packet layer. Script generation receives the full selected story records.
Do not add a fact-packet dependency unless a new, demonstrated requirement
justifies it.

Current handoffs must name real consumers:

- news collection -> evidence prep
- evidence prep -> story mapping
- story mapping -> video packaging
- video packaging -> script generation
- script generation -> metadata creation
- metadata creation -> media production/manual publish review

## LLM Policy

Use LLMs for semantic judgment and code for stable guardrails.

Good LLM responsibilities:

- story identity and editorial value
- coherent full-script writing and bounded reflection
- viewer-facing metadata
- visual direction and semantic scene planning

Good deterministic responsibilities:

- collection and normalization
- source and record provenance
- format routing and selection caps
- timing, duration, and section checks
- Pydantic structured-output validation
- asset resolution, rendering, and assembly

Use LangChain structured output with Pydantic models where an LLM must return
structure. Keep `llm_client.py` limited to provider/model construction and keep
LLM logging separate. Prompt text belongs in versioned files, not inline Python.

Reflection/revision loops must have a config-driven hard maximum. Never allow
an unbounded agent loop.

## Script Compatibility

App-generated and manual ChatGPT scripts must use the same canonical
`script_generation_result` contract. The manual path is normalized by
`handoffs/chatgpt_script_parser`; downstream voiceover, metadata, and visuals
must not contain a second manual-script schema.

Prefer explicit script sections: intro, one section per selected story, then
closing. Preserve section IDs outside spoken narration so visual planning can
map exact story boundaries without leaking internal IDs into audio.

## Visual Policy

Visual planning and asset/render production are separate responsibilities.

- the planner chooses renderable scene kinds and produces semantic timing
- media discovery finds contextual images/video only when requested
- asset resolution obtains screenshots, logos, and discovered media
- Remotion renders short independent scene clips
- assembly joins clips and voiceover into the final video

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
