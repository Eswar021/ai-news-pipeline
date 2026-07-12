# Pipeline Runtime

`src/pipeline/` is the canonical application-oriented runtime.

```text
src/pipeline/
├── apps/            # pure JSON/dict applications
├── contracts/       # public cross-module artifact identity contracts
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
- `apps/metadata_finalizer`

Current media/handoff modules:

- `handoffs/chatgpt_exporter`
- `handoffs/chatgpt_script_parser`
- `handoffs/chatgpt_visual_plan_parser`
- `handoffs/publish_handoff`
- `voiceover`
- `visuals`

Both native and manual ChatGPT routes produce one section-aware script contract
with stable audiovisual beats. Voiceover preserves those IDs in timed audio
units, and both visual-planning routes consume the same aligned beat timeline.
Downstream code must never branch on a manual-only data shape or infer story
boundaries from `full_script`.

Canonical scripts and all downstream media packages carry deterministic
fingerprints. Notebook artifact selection is explicit or unambiguous and never
uses newest-file-wins behavior. Metadata creation is a draft stage; actual
chapter timestamps are finalized from voiceover section audio units.

Read:

- `docs/current_system_architecture.md`
- `src/pipeline/apps/script_generation/formats/roundup/README.md`
- `src/pipeline/visuals/README.md`
