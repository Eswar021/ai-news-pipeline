# AI Content Creation Pipeline

An application-oriented AI news production system that collects source
material, maps stories, writes story-local audiovisual beats for a coherent roundup, creates YouTube metadata,
generates voiceover, plans motion visuals, renders scene clips, and assembles a
final video.

## Architecture

The canonical runtime is `src/pipeline/`. Functional applications use a direct
JSON/dict boundary:

```python
from src.pipeline.apps.story_mapping import run

result = run(input_json)
```

Each app owns its Pydantic contracts, configuration defaults, prompts, LLM
provider adapter, and local helpers. Core apps return data and do not write
files. Notebooks own orchestration and run artifacts; voiceover and visual
modules may write media files because those files are their product.

```text
src/pipeline/
├── apps/            # collection through metadata
├── contracts/       # stable artifact identity and lineage
├── handoffs/        # ChatGPT and publish adapters
├── orchestration/   # frozen run context helpers
├── voiceover/       # local TTS providers and WAV packaging
├── visuals/         # planning, media, assets, rendering, assembly
└── config/          # workbench.yaml
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

Edit `src/pipeline/config/workbench.yaml` to select providers, models, voices,
visual capabilities, rendering quality, and policy limits. A production content
run freezes the selected profile and config hash into `run_context.json`; media
notebooks use that frozen profile.

The default voiceover is free local Kokoro. Other local providers remain
available but may require additional models or reference audio.

## Development Checks

```bash
python3 -B -m compileall src/pipeline
python3 -m pytest -q

cd src/pipeline/visuals/remotion_engine
npm run typecheck
```

Current architecture, source map, workflow diagram, and synchronization contract:

- `docs/current_system_architecture.md`
