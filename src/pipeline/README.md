# Pipeline Runtime

`src/pipeline/` is the canonical application-oriented runtime.

```text
src/pipeline/
├── ingestion/       # normalized external data collection
├── content/         # pure JSON/dict content applications
├── contracts/       # public cross-module artifact identity contracts
├── handoffs/        # manual/external adapters
├── orchestration/   # run context, stage routers, state, and logging
├── publishing/      # audio-timed metadata and manual publish handoff
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

Repeatable production automation uses four explicit stage commands:

```bash
python3 -m src.pipeline.orchestration.runner collect --profile daily_48h_all_sources --environment prod
python3 -m src.pipeline.orchestration.runner content --run-id current
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

New content runs store an immutable composed profile in
`output/runs/{run_id}/run_context.json`. By default, each stage reloads the
current YAML for the module it is about to execute and records the exact value
in that module's `config_snapshot.json`. Use `--config-mode frozen` for an
exact initial-profile reproduction. Module artifacts live below the same run
directory. Local model caches live outside run output under
`.cache/ai_content_creation/models/`.

Current ingestion application:

- `ingestion/news_collection`

Current pure content applications:

- `content/evidence_prep`
- `content/editorial_triage`
- `content/story_mapping`
- `content/editorial_selection`
- `content/video_packaging`
- `content/script_generation/formats/roundup`
- `content/metadata_creator`

Current publishing applications:

- `publishing/metadata_finalizer`
- `publishing/publish_handoff`

Current media/handoff modules:

- `handoffs/chatgpt_exporter`
- `handoffs/chatgpt_script_parser`
- `handoffs/chatgpt_visual_plan_parser`
- `voiceover`
- `visuals`

Both native and manual ChatGPT routes produce one section-aware script contract
with stable audiovisual beats. Voiceover preserves those IDs in timed audio
units, masters the final WAV without changing timing, emits SRT/VTT captions,
and both visual-planning routes consume the same aligned beat timeline.
Downstream code must never branch on a manual-only data shape or infer story
boundaries from `full_script`.

Canonical beats can carry provider-neutral `delivery_direction` metadata.
Hosted speech adapters translate it into provider instructions while spoken
narration and captions remain clean text.

Canonical scripts and all downstream media packages carry deterministic
fingerprints. Notebook artifact selection is explicit or unambiguous and never
uses newest-file-wins behavior. Metadata creation is a draft stage; actual
chapter timestamps are finalized from voiceover section audio units.

Read:

- `docs/current_system_architecture.md`
- `src/pipeline/content/script_generation/formats/roundup/README.md`
- `src/pipeline/visuals/README.md`
