# Pipeline v2

`src/pipeline_v2/` is the experimental application-oriented rewrite of the
rebuild pipeline.

The earlier copied numbered-layer snapshot has been removed. The current v2
tree is centered on standalone apps plus app-like media subsystems.

## Target Direction

Pipeline v2 should be grouped by functionality:

```text
src/pipeline_v2/
|-- apps/
|   |-- news_collection/
|   |-- evidence_prep/
|   |-- story_mapping/
|   |-- video_packaging/
|   |-- script_generation/
|   |-- metadata_creator/
|   |-- verification/
|   `-- memory_update/
|-- handoffs/
|-- voiceover/
|-- visuals/
`-- shared/
```

There is intentionally no central `src/pipeline_v2/runner.py` yet. For now,
use two notebooks:

- `notebooks/v2_apps_workbench.ipynb` runs the pure app sequence through the
  currently migrated apps.
- `notebooks/v2_chatgpt_voiceover_workbench.ipynb` resumes from an App 4
  `video_packaging` run, exports a ChatGPT content-packet handoff, then runs
  voiceover from manually saved script text.

The notebooks read operator-facing defaults from
`src/pipeline_v2/config/workbench.yaml`. Keep that file simple and
module-wise: set `provider` and `model` directly under the LLM-using module
configs such as `story_mapping.story_label`, `script_generation`, and
`metadata_creator`. The apps still receive those settings only through their
JSON/dict input envelopes; app cores should not read this YAML directly.

Each app should expose:

```python
def run(input_json: dict) -> dict:
    ...
```

The app core should accept a JSON/dict input and return a JSON/dict output.
File I/O, CLI parsing, run-folder paths, and current-manifest loading belong in
notebooks under `notebooks/` or future adapter code, not inside the app core.

Currently migrated apps:

- `apps/news_collection`
- `apps/evidence_prep`
- `apps/story_mapping`
- `apps/video_packaging`
- `apps/script_generation`
- `apps/metadata_creator`

App-like media modules:

- `voiceover`
- `visuals`

Standalone handoff utilities:

- `handoffs/chatgpt_exporter`
- `handoffs/publish_handoff`

`voiceover` is intentionally parallel to `apps/` because its core output is
audio files. It still accepts a JSON/dict input and returns a JSON/dict result,
but it is allowed to write WAV/package artifacts under a caller-provided
`output_v2` directory.

`visuals` is intentionally parallel to `voiceover` because its core output is
rendered media files. It is a small subsystem with a pure planner plus
media-writing resolver/render steps. The active visual language is motion-first:
source article scenes, logo reveal scenes, and kinetic type scenes. Do not bring
back generic title/timeline/entity/card renderers as primary output.

The Remotion renderer lives under `visuals/remotion_engine/`. Before rendering
clips on a fresh machine, run `npm install` in that directory. The notebook then
uses `visuals.render` to write per-scene MP4 clips under `output_v2/visuals/`.
After that, `visuals.assembly` concatenates those clips and muxes the selected
voiceover WAV into a final review MP4 under the same run folder.

The v2 voiceover module currently supports `kokoro_local` for lightweight local
draft audio and `chatterbox_local` for more expressive local narration.
Chatterbox settings such as device, exaggeration, CFG weight, optional reference
audio, and Hugging Face cache directory are passed through the input config.
The workbench stores model downloads under `output_v2/model_cache/` so large
runtime assets stay out of source control.

If a migration decision is unclear, ask before adding orchestration, output
paths, central runners, compatibility shims, or deleting app folders.

## Migration Rule

Reuse first.

When migrating from v1, copy useful existing code into the relevant app folder
and refactor it to the v2 boundary. Do not regenerate the system from scratch
unless the existing code is genuinely the wrong abstraction.

Keep behavior config-driven. If a value affects runtime behavior, pass it in
through the app input/config contract instead of hardcoding it in code.

For the full contract, read:

- `docs/rebuild/pipeline_v2_application_architecture.md`
