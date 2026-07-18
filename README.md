# AI Content Creation Pipeline

An application-oriented AI news production system that collects source
material, maps stories, writes story-local audiovisual beats for a coherent roundup, creates YouTube metadata,
generates voiceover, plans motion visuals, renders scene clips, and assembles a
final video.

## Architecture

The canonical runtime is `src/pipeline/`. Functional applications use a direct
JSON/dict boundary:

```python
from src.pipeline.content.story_mapping import run

result = run(input_json)
```

Each app owns its Pydantic contracts, configuration defaults, prompts, LLM
provider adapter, and local helpers. Core apps return data and do not write
files. Notebooks own orchestration and run artifacts; voiceover and visual
modules may write media files because those files are their product.

```text
src/pipeline/
├── content/         # collection through metadata
├── contracts/       # stable artifact identity and lineage
├── handoffs/        # ChatGPT and publish adapters
├── orchestration/   # run context, live module config, state, and logging
├── voiceover/       # local TTS providers and WAV packaging
├── visuals/         # planning, media, assets, rendering, assembly
└── config/          # profile manifest plus stage/module YAML
```

## Notebooks

Use focused notebooks instead of one stateful end-to-end workbench:

- `notebooks/production/content_pipeline.ipynb`: Apps 1–6 through metadata draft.
- `notebooks/handoffs/chatgpt_handoffs.ipynb`: manual script and visual-plan handoffs.
- `notebooks/production/voiceover_generation.ipynb`: canonical script to WAV and audio-timed metadata.
- `notebooks/production/visual_production.ipynb`: plan, assets, clips, final video, and publish review.
- `notebooks/labs/visual_assets_lab.ipynb`: isolated visual-family experiments.

The production media notebooks support a deterministic fixture mode and a real
run mode. Start with fixture mode when checking installation or renderer changes.

## Outputs

New runs use a run-first layout:

```text
output/runs/{run_id}/
├── run_context.json
├── news_collection/
├── evidence_prep/
├── story_mapping/
├── video_packaging/
├── script_generation/
├── metadata_creator/
├── metadata_finalizer/
├── orchestration/
├── voiceover/
└── visuals/
```

`output/current_run.json` identifies the latest notebook-created run.
`output_v2/` contains historical pre-canonicalization runs and is not used by
new workflows. Model caches live under `.cache/ai_content_creation/models/`.

## Reference Media Test

The committed fixture provides a polished section-aware script and curated
visual scene plan without network or LLM dependencies:

```text
tests/fixtures/media_roundup_reference/
```

Set `INPUT_MODE = "fixture"` in the voiceover and visual production notebooks.
Generated test media is written under `output/tests/media_roundup_reference/`.

## Configuration

Edit the relevant YAML below `src/pipeline/config/profiles/` to select
providers, models, voices, visual capabilities, rendering quality, and policy
limits. A production run stores its initial composed profile in
`run_context.json`; runners and notebooks load current module YAML by default
and record the effective value in each module's `config_snapshot.json`.

The current production voice is Gemini 3.1 Flash TTS with Puck and
provider-neutral beat delivery direction. Free local Kokoro remains available.

## Development Checks

```bash
python3 -B -m compileall src/pipeline
python3 -m pytest -q

cd src/pipeline/visuals/remotion_engine
npm run typecheck
```

Current architecture, source map, workflow diagram, and synchronization contract:

- `docs/current_system_architecture.md`
