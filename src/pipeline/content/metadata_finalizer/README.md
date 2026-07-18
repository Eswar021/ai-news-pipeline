# Metadata Finalizer

`metadata_finalizer.run(input_json)` is the deterministic second stage of
YouTube metadata production. `metadata_creator` generates the viewer-facing
draft; this app replaces provisional chapter times with actual
`voiceover.audio_units[].start_seconds` values and rebuilds the description.

It requires matching script, metadata-draft, and voiceover fingerprints. It
does not call an LLM or write files. The voiceover notebook owns output under:

```text
output/runs/{run_id}/metadata_finalizer/
```

Only this final package sets `chapters_finalized=true` and is accepted by the
publish handoff.
