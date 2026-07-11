# Pipeline Runtime

`src/pipeline/` is the canonical application-oriented runtime.

```text
src/pipeline/
├── apps/            # pure JSON/dict applications
├── handoffs/        # manual/external adapters
├── orchestration/   # notebook run context
├── voiceover/       # local TTS and WAV packaging
├── visuals/         # planning through video assembly
└── config/          # operator authoring config
```

Pure apps expose:

```python
def run(input_json: dict) -> dict:
    ...
```

They validate with Pydantic, receive effective config in the request, return a
canonical envelope, and do not choose output paths. Voiceover and visual media
modules use the same control style but may write caller-directed media files.

There is no central runner. Use:

- `notebooks/production/content_pipeline.ipynb`
- `notebooks/handoffs/chatgpt_handoffs.ipynb`
- `notebooks/production/voiceover_generation.ipynb`
- `notebooks/production/visual_production.ipynb`
- `notebooks/labs/visual_assets_lab.ipynb`

New content runs freeze `config/workbench.yaml` into
`output/runs/{run_id}/run_context.json`. Module artifacts live below the same
run directory. Local model caches live outside run output under
`.cache/ai_content_creation/models/`.

Current pure applications:

- `apps/news_collection`
- `apps/evidence_prep`
- `apps/story_mapping`
- `apps/video_packaging`
- `apps/script_generation/formats/roundup`
- `apps/metadata_creator`

Current media/handoff modules:

- `handoffs/chatgpt_exporter`
- `handoffs/chatgpt_script_parser`
- `handoffs/chatgpt_visual_plan_parser`
- `handoffs/publish_handoff`
- `voiceover`
- `visuals`

Both native and manual ChatGPT routes must produce the same script and visual
planning contracts. Downstream code should never branch on a manual-only data
shape.

Read:

- `docs/architecture/pipeline_application_architecture.md`
- `docs/architecture/media_modules.md`
- `docs/architecture/visuals_roadmap.md`
- `src/pipeline/visuals/README.md`
