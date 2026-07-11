# Pipeline Application Architecture

## Purpose

The pipeline is organized by production capability rather than numbered
layers. Each capability is a small application with a Pydantic-validated
JSON/dict boundary. Notebooks orchestrate those applications while contracts
and operational behavior stabilize.

## Runtime Shape

```text
src/pipeline/
├── apps/
│   ├── news_collection/
│   ├── evidence_prep/
│   ├── story_mapping/
│   ├── video_packaging/
│   ├── script_generation/formats/roundup/
│   └── metadata_creator/
├── handoffs/
│   ├── chatgpt_exporter/
│   ├── chatgpt_script_parser/
│   ├── chatgpt_visual_plan_parser/
│   └── publish_handoff/
├── orchestration/run_context.py
├── voiceover/
├── visuals/
└── config/workbench.yaml
```

There is no central runner. Current operator workflows are:

```text
notebooks/production/content_pipeline.ipynb
notebooks/handoffs/chatgpt_handoffs.ipynb
notebooks/production/voiceover_generation.ipynb
notebooks/production/visual_production.ipynb
notebooks/labs/visual_assets_lab.ipynb
```

## Core Contract

Pure applications expose:

```python
def run(input_json: dict) -> dict:
    request = RequestModel.model_validate(input_json)
    ...
    return response.model_dump(mode="json")
```

The returned envelope contains:

```json
{
  "status": "ok|partial|failed",
  "data": {},
  "summary": {},
  "handoff": {},
  "llm_calls": []
}
```

`llm_calls` is present only where relevant. A handoff names the real next
consumer and must not preserve retired architectural stages.

## State Flow

```text
news_collection
  raw records
    -> evidence_prep
  normalized prepared records
    -> story_mapping
  ranked story objects carrying full records
    -> video_packaging
  selected format-specific video packet
    -> script_generation
  section-aware narration package
    -> metadata_creator and media production
```

Downstream applications do not reopen arbitrary older output folders. Context
needed later must be carried forward in the input artifact. This can duplicate
data, but it keeps each boundary explicit and testable.

The current system intentionally skips the retired fact-packet stage. Selected
stories carry full records into script generation. Exact claim verification can
be added later as an optional application if demonstrated quality needs justify
its cost and complexity.

## File Ownership

Pure `apps/`:

- receive config and upstream artifacts in the input dict
- return a dict
- do not choose output paths
- do not write run files
- do not read YAML

Adapters and notebooks:

- load authoring config
- freeze a run context
- build app input envelopes
- write canonical inputs/results/summaries
- invoke CLI adapters when a separate runtime is required

Media subsystems may write WAV, image, and MP4 artifacts under caller-provided
directories. Their control and summary interfaces still use JSON.

## Configuration

`src/pipeline/config/workbench.yaml` is the operator authoring surface. A new
content run creates:

```text
output/runs/{run_id}/run_context.json
output/current_run.json
```

The context stores the selected profile, full frozen profile config, config
hash, trigger, orchestrating notebook, and canonical run directory. Production
media notebooks use this frozen profile instead of rereading changed YAML.

App-local defaults are implementation defaults only. Any value that materially
changes a run belongs in the input contract and frozen profile.

## LLM Boundaries

LLM applications use provider construction in `llm_client.py`, versioned prompt
files, LangChain prompt chains, Pydantic structured output, and separate
in-memory call logging.

LLMs handle semantic work:

- story identity and editorial value
- coherent script writing and bounded revision
- metadata language
- visual direction

Code handles stable rules:

- collection windows and normalization
- selection caps and diversity
- timing and section structure
- source keys and provenance
- schema validation
- media resolution and rendering

Reflection loops require a config-driven hard maximum.

## Canonical Outputs

New outputs are run-first:

```text
output/runs/{run_id}/{module}/
```

Every notebook-owned module folder should contain its exact input envelope,
canonical result, main artifact/package, and summary. This makes a run easy to
resume and inspect without notebook memory.

`output_v2/` is historical data. It is not an active configuration or lookup
root.

## Compatibility

Both native script generation and manual ChatGPT writing produce the same
`script_generation_result` envelope. `chatgpt_script_parser` normalizes the
manual response, preserves explicit section boundaries, and removes internal
section markers from spoken narration.

Visual planning has the same rule: generated and ChatGPT plans produce the same
`visual_scene_planning_result` envelope before media discovery and rendering.

## Success Criteria

A module is healthy when:

- its boundary validates with Pydantic
- its behavior is driven by input config
- it has no hidden global output dependency
- its output names the real next consumer
- it can run against a small deterministic fixture
- failures include actionable reasons
- notebooks can resume from written artifacts instead of prior cell state
