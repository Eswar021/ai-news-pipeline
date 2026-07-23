# Run Desk UI

Run Desk is the local production and inspection surface for the canonical
pipeline. It has three independent processes:

- `ui/backend`: read-only FastAPI repository for persisted run artifacts
- `ui/controller`: local FastAPI supervisor for allowlisted runs, config writes,
  and UI-owned review notes
- `ui/frontend`: React/Vite application

The pipeline does not import any UI package. The controller invokes only
`src.pipeline.orchestration.runner` through validated argument lists.

## Install

Run these commands from the repository root:

```bash
python3 -m venv ui/.venv
source ui/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ui/backend/requirements-dev.txt -r ui/controller/requirements-dev.txt

cd ui/frontend
npm install
npx playwright install chromium
```

The controller must invoke the Python environment that already runs the
canonical pipeline. Capture that interpreter before activating `ui/.venv`, or
set `RUN_DESK_PIPELINE_PYTHON` to its exact path.

## Development

Start the three processes in separate terminals.

Terminal 1, read-only artifact API:

```bash
cd /path/to/AI_Content_Creation
source ui/.venv/bin/activate
python -m uvicorn ui.backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Terminal 2, local run controller:

```bash
cd /path/to/AI_Content_Creation
export RUN_DESK_PIPELINE_PYTHON="$(command -v python3)"
source ui/.venv/bin/activate
python -m uvicorn ui.controller.app.main:create_app --factory --host 127.0.0.1 --port 8001
```

If the canonical pipeline uses a virtual environment, activate it before
capturing `RUN_DESK_PIPELINE_PYTHON`. Do not use Uvicorn reload for the
controller while a run is active because a reload terminates its supervised
process.

Terminal 3, frontend:

```bash
cd /path/to/AI_Content_Creation/ui/frontend
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to port `8000` and `/control`
to port `8001`. The header shows a clear disconnected state if the optional
controller is not running; artifact inspection still works.

## Test And Build

Backend and controller tests use deterministic temporary fixtures:

```bash
cd /path/to/AI_Content_Creation
source ui/.venv/bin/activate
python -m pytest -q ui/backend/tests ui/controller/tests
```

Frontend typechecking and deterministic desktop/mobile browser tests:

```bash
cd /path/to/AI_Content_Creation/ui/frontend
npm test
```

Production frontend build:

```bash
cd /path/to/AI_Content_Creation/ui/frontend
npm run build
```

Python syntax check:

```bash
cd /path/to/AI_Content_Creation
source ui/.venv/bin/activate
python -m compileall -q ui/backend ui/controller
```

## Product Map

The global navigation has five work areas:

- **Run desk** shows the current persisted run, production stage status, recent
  runs, and the entry points for a new or continued run.
- **New run** builds a reviewed execution plan. Choose New pipeline, Continue
  run, or Replay/retry; then select stage boundaries and modes. The controller
  shows every exact canonical command and requires explicit confirmation before
  provider calls or final media generation.
- **History** discovers every directory beneath `output/runs/` and polls while
  the browser tab is visible. Complete, partial, failed, resumed, and malformed
  runs remain inspectable.
- **Compare** loads two runs on demand and compares workflow state, narration,
  metadata, voice variants, LLM/TTS usage, and frozen configuration.
- **Config** edits existing authoring YAML only. Saves require a change summary
  and confirmation, reject stale or secret-bearing writes, validate the full
  composed profile, and retain a UI-owned revision trail.

Opening a run provides four focused areas:

- **Overview** summarizes persisted status, timing, output counts, failures, and
  module completion.
- **Workflow** follows ingestion, content, voiceover, visuals, and publish review
  in canonical order. Each module exposes Summary, Produced data, Inputs,
  Outputs, Activity, Config, and Artifacts.
- **Record lineage** follows one article through preparation, semantic triage,
  story mapping, selection, script, audio, visuals, and publish review. A
  filtered or not-reached step is shown explicitly.
- **Run diagnostics** contains stage logs, all safe artifacts, frozen/current
  config inspection, structural diffs, and UI-owned operator review notes.

Use **Read** for human-readable editorial views and **Raw** for exact persisted
JSON or text. Large JSON, JSONL ledgers, logs, and artifact trees load only when
opened. WAV and MP4 playback supports browser seeking through HTTP byte ranges.

Source, LLM, media-model, deterministic-code, and mixed products have consistent
badges and tooltips. On applicable record/story/section views, **Find related
LLM calls** opens contextual ledger matches and then lazily loads complete
prompts, parsed responses, raw responses, and diagnostics. Current artifacts do
not persist a precise field-to-call ID, so those matches are clearly labeled
contextual rather than exact.

Article tags are not produced as a separate per-article package. Source metadata
begins in news collection, evidence preparation normalizes it, editorial triage
adds semantic decisions, and story mapping forms event/entity identity.
`metadata_creator` produces episode-level YouTube titles, description, tags,
thumbnail concepts, and provisional chapters.

## Safety And Ownership

All services bind to `127.0.0.1`; there is no authentication or remote mode.

The inspector API reads only below `output/` and `src/pipeline/config/`. It
rejects traversal, absolute paths, symlink escapes, and secret-looking paths,
and never exposes `.env`, credential, cookie, secret, or model-cache files.

The controller owns only `ui/.local/controller/` state. It permits one active
writer, uses idempotent requests, supports cancellation, records restart
interruptions honestly, never accepts shell text, and does not expose
credentials. Config Studio can replace an existing YAML file atomically but
cannot create arbitrary files. No UI surface deletes runs, edits run artifacts,
publishes content, or changes pipeline contracts.

## Intentional Limits

- Persisted ledgers do not currently contain normalized currency cost, so the
  comparison view reports calls, tokens, latency, and routes without inventing
  dollar estimates.
- Exact field-to-LLM-call provenance requires future pipeline artifacts to
  persist stable call references.
- Authentication and remote deployment are deliberately absent.
- Deletion and publishing controls are deliberately absent.

See [`EXTENDING.md`](EXTENDING.md) before adding modules, help text, provenance
classes, or controller capabilities.
