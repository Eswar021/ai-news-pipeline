# Pipeline v2

`src/pipeline_v2/` is the experimental application-oriented rewrite of the
rebuild pipeline.

The earlier copied numbered-layer snapshot has been removed. The current v2
tree is centered on standalone apps plus the app-like voiceover module.

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
|-- voiceover/
`-- shared/
```

There is intentionally no central `src/pipeline_v2/runner.py` yet. For now,
run individual apps through `output_v2/v2_apps_workbench.ipynb`.

Each app should expose:

```python
def run(input_json: dict) -> dict:
    ...
```

The app core should accept a JSON/dict input and return a JSON/dict output.
File I/O, CLI parsing, run-folder paths, and current-manifest loading belong in
notebooks under `output_v2/` or future adapter code, not inside the app core.

Currently migrated apps:

- `apps/news_collection`
- `apps/evidence_prep`
- `apps/story_mapping`
- `apps/video_packaging`
- `apps/script_generation`
- `apps/metadata_creator`

App-like media modules:

- `voiceover`

`voiceover` is intentionally parallel to `apps/` because its core output is
audio files. It still accepts a JSON/dict input and returns a JSON/dict result,
but it is allowed to write WAV/package artifacts under a caller-provided
`output_v2` directory.

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
