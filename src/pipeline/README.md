# Pipeline Runtime

`src/pipeline/` is the canonical application-oriented runtime.

```text
src/pipeline/
├── apps/            # pure JSON/dict applications
├── contracts/       # public cross-module artifact identity contracts
├── handoffs/        # manual/external adapters
├── orchestration/   # run context, stage routers, state, and logging
├── voiceover/       # local TTS, loudness mastering, captions, and WAV packaging
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

Repeatable production automation uses three explicit stage commands:

```bash
python3 -m src.pipeline.orchestration.runner content --profile daily_48h_all_sources
python3 -m src.pipeline.orchestration.runner voiceover --run-id current --script-source app
python3 -m src.pipeline.orchestration.runner visuals --run-id current --render-mode preview
```

Launch the stage runner from the main project Python environment. Do not
activate `.venv-voiceover` first; that environment is intentionally limited to
local TTS dependencies, and the voiceover stage invokes it automatically.
The CLI loads secrets from the selected project root's `.env` before importing
or running a stage. Enabled credentialed collectors are checked together before
collection starts, without logging secret values.
Run stages one at a time, or join commands with `&&`, so a failed upstream
stage cannot start downstream stages against incomplete artifacts.

Focused notebooks remain available for interactive operation and inspection:

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
- `apps/editorial_triage`
- `apps/story_mapping`
- `apps/editorial_selection`
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
units, masters the final WAV without changing timing, emits SRT/VTT captions,
and both visual-planning routes consume the same aligned beat timeline.
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
