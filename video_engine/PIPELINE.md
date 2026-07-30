# video_engine — the visual stage

`video_engine/` is a **self-contained** HyperFrames motion-graphics tool that turns a
voiceover into a rendered episode. It lives inside this repo so it ships and versions
with the project, but it has **no dependency on the pipeline** (and the pipeline's
Python has no dependency on it). The only contact is one subprocess call across a
narrow, documented contract — so the same engine can drive any project that produces
that contract.

## The contract (what the engine consumes)

Two files, nothing else:

1. **`voiceover_package.json`** — our voiceover-package shape (audio units, per-beat
   timing, section/story structure).
2. **`full_voiceover.wav`** — the narration the timing refers to.

The engine reads *only* these. It never reaches into a run directory, never imports
pipeline code, and writes only inside `video_engine/` (working files) and the
`--out-dir` you give it.

## Portable entrypoint — `scripts/pipeline/render-episode.mjs`

Project-agnostic. Give it explicit paths; it stages them into a gitignored
`.work/<tag>/`, runs art-director → asset resolver → build → render, and copies the
finished MP4 into `--out-dir`.

```bash
node scripts/pipeline/render-episode.mjs \
  --voiceover-package /path/to/voiceover_package.json \
  --audio             /path/to/full_voiceover.wav \
  --out-dir           /where/the/mp4/should/go
# options: --units N   --deterministic (no-LLM bridge)   --skip-render   --tag NAME   --out NAME
```

Requirements: `npm install` (once, for `js-yaml`), Node on PATH, `DEEPSEEK_API_KEY`
in the environment for the LLM art-director (skip with `--deterministic`), and the
`media-use` skill on PATH for real logos/photos.

## How this pipeline triggers it (the visuals stage)

Production never calls Node by hand. The orchestration runs a **thin Python stage**
(`src/pipeline/orchestration/stages/visuals.py`) that resolves the run's selected
voiceover package (`orchestration/voiceover_selection.json`) and invokes the portable
entrypoint over a subprocess boundary:

```bash
python3 -m src.pipeline.orchestration.runner visuals --run-id current
#   options: --deterministic  --units N  --skip-render
#            --video-engine-dir video_engine  --node-bin node
```

The MP4 lands in `<run_dir>/visuals/<run_id>-ad.mp4`; a `visuals_stage_result.json`
and a `visuals.log` are written under `<run_dir>/orchestration/`.

## Dev convenience — `scripts/pipeline/from-run.mjs`

Pipeline-aware shim for manual runs: point it at a run directory and it resolves the
package + WAV for you, then delegates to `render-episode.mjs`.

```bash
node scripts/pipeline/from-run.mjs --run-dir <run dir> [--units N] [--deterministic] [--skip-render]
```

## What's committed vs. generated

Committed: `compositions/`, `scripts/`, `assets/`, hand-authored `content/*-demo.yaml`
+ `content/registry.yaml`, `package.json`. Everything else is generated and gitignored
(`node_modules/`, `renders/`, `index.html`, `.work/`, `.media/`, `reference/`,
`gallery/`, and generated `content/*-ad*.yaml` / `*-resolved.yaml` / `run*.yaml`).
