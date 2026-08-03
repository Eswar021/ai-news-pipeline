# Run Inspector UI Design

Status: Approved for implementation

Last updated: 2026-07-23

## 1. Goal

Build a small application that makes the pipeline observable without requiring
the operator to browse large JSON files manually. The UI should discover run
history from `output/`, show every stage and module artifact, play generated
media, inspect logs and model calls, and explain the configuration used by each
run.

The first milestone is an inspector, not another orchestrator. It is read-only,
does not modify pipeline artifacts, does not edit YAML, and does not execute,
resume, delete, or publish runs. Execution controls remain a separately owned
future feature after the inspection surface is reliable.

## 2. Confirmed Data Sources

The UI reads only from two allowlisted roots:

```text
output/
src/pipeline/config/
```

It must never read or expose `.env`, `secrets/`, credentials, model caches, or
arbitrary filesystem paths.

### Historical run data

```text
output/current_run.json
output/runs/{run_id}/run_context.json
output/runs/{run_id}/orchestration/run_state.json
output/runs/{run_id}/orchestration/logs/*.log
output/runs/{run_id}/{module}/*_input.json
output/runs/{run_id}/{module}/*_result.json
output/runs/{run_id}/{module}/summary.json
output/runs/{run_id}/{module}/config_snapshot.json
output/runs/{run_id}/{module}/llm_calls.jsonl
output/runs/{run_id}/voiceover/{variant}/...
output/runs/{run_id}/visuals/...
```

Run folders may be incomplete, failed, resumed, or contain multiple voiceover
variants and both preview/final visual products. Missing optional files are
normal and must be represented as unavailable rather than treated as an
application error.

### Authoring configuration

```text
src/pipeline/config/workbench.yaml
src/pipeline/config/environments/{environment}.yaml
src/pipeline/config/profiles/{profile}/profile.yaml
src/pipeline/config/profiles/{profile}/{stage}/{module}.yaml
```

The UI should distinguish three different configuration views:

1. **Current authoring YAML**: files currently present in source control.
2. **Initial run profile**: the immutable composed `profile_config` stored in
   `run_context.json`.
3. **Effective module snapshot**: the exact configuration in each module's
   `config_snapshot.json`, which may reflect live-mode changes after the run
   began.

Do not recreate pipeline config precedence independently in frontend code. The
MVP can show raw current YAML plus the two historical composed snapshots. If a
live effective-config preview is later required, expose it through one narrow
backend adapter using the public config repository.

## 3. Approved Separation

The UI must remain separate from `src/pipeline/` and must not be imported by
pipeline apps or orchestration code.

The application lives at the repository root beside `src/`:

```text
ui/
├── backend/                # FastAPI application and filesystem adapters
├── frontend/               # React/Vite TypeScript application
├── README.md               # local setup and launch commands
└── ...                     # app-owned tests and dependency manifests
```

This keeps dependencies, build output, and deployment independent from the
pipeline. The backend may read the two approved roots through its own adapters,
but neither frontend nor backend becomes part of `src/pipeline/`.

No pipeline artifact schema should be changed merely for the UI. The inspector
adapts existing canonical results into view models.

## 4. Approved Technology

Use FastAPI plus React/Vite with TypeScript.

### Why this fits

- Python backend can safely traverse files, stream large media with range
  requests, parse JSONL incrementally, and optionally use the public config
  repository later.
- React provides a stronger artifact browser, synchronized audio/visual views,
  timeline interaction, filters, and future comparison screens.
- The API and frontend remain independently testable and can later support
  comparisons or a separately designed control surface.

### Alternatives not selected

- Streamlit is faster to scaffold but too restrictive for polished timelines,
  media review, large artifact trees, and future comparison workflows.
- Next.js would provide a strong frontend but would either duplicate Python
  config behavior or require an additional Python boundary later.

## 5. Information Architecture

### Runs

The default page lists every directory below `output/runs/` and derives a small
index from `run_context.json` and `run_state.json`:

- run ID, created time, profile, environment, and trigger
- stage status and last completed module
- selected script and voiceover variant
- script word count, audio duration, scene count, and final-video availability
- failed/partial state and concise failure reason
- preview/final badges

The initial implementation should scan on startup and refresh on demand. It
does not need a database. Cache lightweight file metadata in memory and lazily
load large artifacts only when opened.

### Run overview

Show a horizontal stage flow:

```text
Ingestion -> Content -> Voiceover -> Visuals -> Publish review
```

Each stage expands into module cards with status, duration, provider/model when
applicable, summary metrics, reuse state, input/result links, config snapshot,
and log location.

### Ingestion and content

- collected source groups, source-level counts, warnings, and candidate ledger
- prepared records and reversible evidence decisions
- editorial triage advance/reserve/quarantine decisions
- story clusters with every source record and mapping rationale
- selected slate, reserve stories, ordering, and video packet
- script sections and beats, full narration, visual briefs, source references,
  writer/reviewer calls, and script fingerprint
- metadata title options, thumbnail concepts, description, chapters, tags, and
  source URLs

### Voiceover

- variant selector when several packages match one script
- provider, model, voice, speed, style, duration, and mastering measurements
- in-browser WAV player
- section/beat timing table and alignment
- captions download/preview
- chunk list and provider-neutral `tts_requests.jsonl` ledger
- script and voiceover parent fingerprints

### Visuals

- visual-research needs grouped by story and sequence
- trusted asset catalog with source thumbnails, identity quality, provenance,
  and unresolved candidates
- scene timeline grouped by intro, story, and closing
- scene recipe, payload, narration interval, selected asset, source URL, and
  planner/editor rationale
- media-discovery and asset-resolution status
- per-scene MP4 playback when available
- preview/final video player
- contact sheet and embedded or linked story review report
- render/assembly settings, cache statistics, failures, and fingerprints

### Logs and calls

- per-stage log viewer with search, severity filter, and tail mode
- module LLM-call table with provider, model, role, latency, attempts, token
  usage, response status, and expandable prompt/response records
- show the complete persisted prompt, structured response, raw response, and
  parsing diagnostics when the operator explicitly expands a call
- TTS request ledger displayed separately from LLM calls
- no secret values and no environment-variable contents; visibility is limited
  to records already persisted by the pipeline

### Configuration

- profile/environment tree from current authoring YAML
- run-frozen profile viewer
- module effective snapshot viewer
- structural diff between current YAML, frozen run profile, and module snapshot
- provider/model summary across all modules
- source configuration and visual/render settings

The first version is view-only. Editing configuration requires a separate
design because validation, comments, YAML formatting, and deployment safety
have different risks.

## 6. Proposed API Boundary

Exact URLs depend on the chosen stack, but the backend should expose narrow
read-only operations equivalent to:

```text
GET /api/runs
GET /api/runs/{run_id}
GET /api/runs/{run_id}/state
GET /api/runs/{run_id}/modules/{module}
GET /api/runs/{run_id}/artifacts?path={relative_path}
GET /api/runs/{run_id}/logs/{stage}
GET /api/runs/{run_id}/llm-calls/{module}
GET /api/runs/{run_id}/voiceovers
GET /api/runs/{run_id}/visual-scenes
GET /api/media?path={allowlisted_relative_path}
GET /api/config/manifest
GET /api/config/source?path={allowlisted_relative_path}
GET /api/runs/{run_id}/config
```

Artifact and media routes must accept only normalized relative paths below an
allowlisted root. Resolve the path and verify containment before reading it.
Media responses should support byte ranges so WAV and MP4 playback does not
load entire files into memory.

Backend view models should tolerate schema additions. Preserve raw JSON access
alongside curated summaries so the UI remains useful while pipeline contracts
evolve.

## 7. UX Direction

Use an editorial production-desk visual language rather than a generic dark
admin dashboard:

- warm neutral canvas, near-black text, and one restrained status accent
- expressive editorial serif for run/story headings and a readable condensed
  or humanist sans for operational data
- stage rail and artifact hierarchy instead of a wall of identical cards
- real contact sheets, article captures, waveforms, and video frames as the
  primary visual material
- compact status chips only where they communicate state
- responsive desktop-first layout with a usable tablet/mobile run summary
- clear empty, partial, failed, loading, and stale-file states

Large JSON should appear in a virtualized tree or code viewer and never block
initial page rendering.

## 8. Security and Reliability

- bind to `127.0.0.1` by default
- read-only filesystem access in the MVP
- local-only operation with no authentication in the first milestone
- never expose `.env`, `secrets/`, API keys, cookies, or arbitrary absolute paths
- reject path traversal and symlink escapes
- cap JSON/text response size and paginate JSONL records
- stream audio/video rather than buffering complete files
- handle malformed, truncated, or actively-written JSON with a visible retry
  state
- do not infer success from file existence alone; prefer canonical status and
  handoff fields
- never modify `current_run.json` or run artifacts

## 9. Implementation Phases

### Phase 1: Read model and run index

- scaffold `ui/backend` and `ui/frontend` with independent test commands
- implement allowlisted filesystem repository
- discover runs and parse run context/state
- add tests for missing, partial, malformed, and multiple-variant runs

### Phase 2: Run and module inspection

- runs list and run overview
- stage/module summaries
- raw input/result/config viewers
- logs and LLM/TTS ledgers

### Phase 3: Media inspection

- voiceover variant selector and audio playback
- visual scene timeline and asset previews
- scene/final-video playback
- contact sheet and story-review integration

### Phase 4: Configuration inspection

- authoring YAML browser
- frozen/effective config views
- structural config diff and provider/model matrix

### Phase 5: Quality and comparisons

- compare two runs or two voiceover/render variants
- script, metadata, cost/usage, and config diffs
- saved local review notes only after storage ownership is designed

Run execution/resume controls, config editing, artifact deletion, publishing,
authentication, and remote deployment are explicitly deferred. A future
control surface must use a separate API boundary and process supervisor rather
than adding write behavior to the read-only artifact repository.

## 10. Acceptance Criteria

- all runs under `output/runs/` are discoverable without a hardcoded run ID
- failed and partial runs remain inspectable
- every canonical module input, result, summary, config snapshot, and log can be
  reached from the selected run
- multiple voiceover variants and preview/final visual artifacts are distinct
- audio and video support seekable browser playback
- the scene timeline exposes narration, recipe, asset, and provenance together
- current, frozen, and effective module config are clearly distinguished
- large files are loaded lazily and do not freeze the UI
- no route can read outside `output/` and `src/pipeline/config/`
- no pipeline source module depends on the UI
- deterministic repository/API tests use fixture runs rather than production
  output

## 11. Confirmed Decisions

- FastAPI backend plus React/Vite TypeScript frontend
- root-level `ui/` application, independent from `src/pipeline/`
- read-only first milestone
- run/resume controls deferred to a separate future control boundary
- local-only binding with no authentication
- complete persisted LLM prompt/response records visible on explicit expansion
- secrets, environment contents, and non-allowlisted files remain inaccessible

No product clarification is currently required to begin Phase 1.
