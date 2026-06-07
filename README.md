# AI Content Creation Pipeline

This repository is being rebuilt into a cleaner AI content production system for
collecting AI news, mapping stories, producing YouTube scripts, creating
metadata, and generating voiceover audio.

The old root `pipelines/` runtime has been retired. Current development happens
under `src/`.

## Active Tracks

There are two active pipeline tracks:

- `src/pipeline/`: stable v1 rebuild runtime. Keep this working.
- `src/pipeline_v2/`: experimental application-oriented rewrite. New modular
  app work happens here.

Pipeline v2 apps expose direct JSON/dict boundaries:

```python
def run(input_json: dict) -> dict:
    ...
```

The v2 app workbench is currently the orchestration surface while contracts
stabilize:

```text
output_v2/v2_apps_workbench.ipynb
```

## Current v2 Flow

The current v2 flow is functionality-first, not layer-number-first:

```text
news_collection
  -> evidence_prep
  -> story_mapping
  -> video_packaging
  -> script_generation/formats/roundup
  -> metadata_creator
  -> voiceover
```

The core apps do not write files. The notebook owns JSON output writing under
`output_v2/`. The v2 voiceover module is the exception because audio generation
must produce WAV files.

## Useful Commands

Run the stable v1 rebuild pipeline:

```bash
python -m src.pipeline.runner 0 1 2 3 4 5 6 7 8 9 --run-profile daily_48h_all_sources
```

Compile the active v2 apps:

```bash
python3 -B -m compileall src/pipeline_v2/apps
```

Compile the v2 voiceover module with its Python 3.12 environment:

```bash
.venv-voiceover/bin/python -B -m compileall src/pipeline_v2/voiceover
```

Run v2 voiceover from a prepared input JSON:

```bash
.venv-voiceover/bin/python -m src.pipeline_v2.voiceover.cli --input-json output_v2/voiceover_inputs/example.json
```

Export a stable v1 ChatGPT handoff:

```bash
python3 -m src.chatgpt_exporter --run-id current
python3 -m src.chatgpt_exporter --run-id current --profile script_review
```

## Key Docs

Start here before changing architecture:

- `AGENTS.md`
- `docs/rebuild/system_blueprint.md`
- `docs/rebuild/l0_l1_decisions.md`
- `docs/rebuild/pipeline_v2_application_architecture.md`
- `src/pipeline_v2/README.md`
- `src/pipeline_v2/voiceover/README.md`

Current architecture diagrams:

- `docs/architecture_showcase.mmd`
- `docs/architecture_showcase_technical.mmd`
- `docs/architecture_showcase.svg`

## Project Shape

```text
src/
├── config/              # stable rebuild config
├── llm/                 # stable rebuild LLM helpers
├── pipeline/            # stable v1 rebuild runtime
├── pipeline_v2/         # application-oriented v2 rewrite
├── chatgpt_exporter.py  # stable v1 handoff exporter
└── voiceover/           # stable voiceover reference implementation

prompts/                 # shared stable v1 prompt files
output/                  # generated v1 outputs, git-ignored
output_v2/               # generated v2 workbench outputs, git-ignored
docs/rebuild/            # current rebuild architecture notes
```

## Cleanup Notes

The legacy root `pipelines/`, `config/`, `llm/`, and `schemas/` trees, old root
pipeline wrappers, and old system design documents have been removed. If older
behavior is needed for reference, use git history rather than reintroducing
legacy imports into new code.

Root `prompts/` is still intentionally kept because stable `src` modules load
shared prompt files from there.
