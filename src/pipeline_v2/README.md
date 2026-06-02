# Pipeline v2

`src/pipeline_v2/` is the experimental application-oriented rewrite of the
rebuild pipeline.

The current files were copied from `src/pipeline/` as a working snapshot. That
snapshot is not the final v2 architecture.

## Target Direction

Pipeline v2 should be grouped by functionality:

```text
src/pipeline_v2/
|-- runner.py
|-- apps/
|   |-- news_collection/
|   |-- evidence_prep/
|   |-- story_mapping/
|   |-- fact_packet/
|   |-- editorial_selection/
|   |-- content_packaging/
|   |-- script_generation/
|   |-- verification/
|   `-- memory_update/
`-- shared/
```

Each app should expose:

```python
def run(input_json: dict) -> dict:
    ...
```

The app core should accept a JSON/dict input and return a JSON/dict output.
File I/O, CLI parsing, run-folder paths, and current-manifest loading belong in
runner or adapter code, not inside the app core.

## Migration Rule

Reuse first.

When migrating from v1, copy useful existing code into the relevant app folder
and refactor it to the v2 boundary. Do not regenerate the system from scratch
unless the existing code is genuinely the wrong abstraction.

Keep behavior config-driven. If a value affects runtime behavior, pass it in
through the app input/config contract instead of hardcoding it in code.

For the full contract, read:

- `docs/rebuild/pipeline_v2_application_architecture.md`
