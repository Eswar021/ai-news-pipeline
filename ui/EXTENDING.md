# Extending Run Desk

This guide keeps future UI work discoverable without coupling the canonical
pipeline to frontend concerns.

## Central Inspector Catalog

`ui/backend/app/catalog.py` is the shared presentation registry for:

- stage and module order, names, purposes, inputs, and outputs
- source, LLM, media-model, deterministic, and mixed generation classes
- module output field groups and their ownership
- reusable help text
- reusable glossary definitions

The frontend loads this registry from `GET /api/catalog`. `HelpTip`,
`GlossaryTip`, `OriginBadge`, headings, metrics, stage navigation, and module
navigation all consume it. Add or revise an explanation there first instead of
copying tooltip text into components.

To expose a newly persisted pipeline module:

1. Add one `MODULE_REGISTRY` entry and place its key in the correct stage.
2. Add a curated read model in `ui/backend/app/repository.py` only when generic
   summary/input/output/artifact inspection is insufficient.
3. Add a specialized React reader only for data that benefits from a domain
   presentation such as a slate, script, timeline, or media player.
4. Add deterministic repository/API fixtures and browser coverage.

The generic module inspector automatically provides Summary, Produced data,
Inputs, Outputs, Activity, Config, Artifacts, Read, and Raw views.

## Controller Boundary

`ui/controller/` is deliberately separate from the read-only repository.
`control_catalog.py` is the security allowlist for runnable stages and module
boundaries. `planner.py` turns validated Pydantic plans into argument arrays for
the canonical runner. It never accepts shell commands from the browser.

Changes to execution capabilities require all of the following:

1. Confirm the canonical runner already supports the option.
2. Extend the controller model and allowlist.
3. Render the exact generated command in the plan review.
4. Classify provider or final-media risk and require confirmation where needed.
5. Add planner, API, one-writer, cancellation, and restart-recovery tests.

Do not move controller imports into `src/pipeline`, write controller state into a
run directory, pass credentials through the API, or add arbitrary output/config
paths. Review notes, config revisions, process events, and job state belong in
`ui/.local/controller/`.

## Read Models

Human-readable views are the primary UI. Preserve the exact persisted artifact
as a separate Raw view and load it only when requested.

Repository readers should:

- tolerate missing, partial, failed, resumed, and malformed outputs
- use structured JSON/YAML parsing rather than string guessing
- paginate JSONL records and load full call payloads only after expansion
- report unknown or unavailable fields honestly
- avoid deriving pipeline status from file existence when orchestration state is
  available
- keep media URLs behind the allowlisted byte-range endpoint

Run comparison follows the same rule: compare a bounded set of editorial and
operational fields on demand rather than loading both artifact trees.

## Provenance

Use these generation classes consistently:

- `source`: collected or normalized source material
- `llm`: language-model judgment or authored text
- `model`: non-language media generation such as speech synthesis
- `deterministic`: repeatable code projection, validation, or rendering
- `mixed`: semantic model output combined with deterministic rules

Module-level provenance comes from the central catalog and persisted call
ledgers. Record/story/section provenance currently searches ledger metadata for
stable identifiers and labels the result as contextual. Do not claim exact
field attribution until pipeline artifacts persist stable call references.

When that contract becomes available, add the reference to repository read
models and resolve it lazily to the existing call-record endpoint. The inspector
must not infer exact authorship from prompt text similarity.

## Config Studio

Config Studio edits only existing YAML beneath `src/pipeline/config/`. Keep all
of its protections together in `ui/controller/app/config_store.py`:

- containment and symlink checks
- duplicate-key YAML rejection
- inline credential rejection
- optimistic SHA conflict detection
- canonical full-profile validation
- atomic replacement
- UI-owned revision history
- write lock while a run job is active

New configuration creation, renaming, deletion, and rollback are not supported.
Any future addition needs explicit ownership and failure semantics before a UI
control is added.

## UX Conventions

Use editorial production-desk layouts: ordered tables, rails, timelines,
side-by-side redlines, and dense readable sheets. Avoid generic admin card
grids. Keep module headings compact and preserve stable dimensions for controls.

Use Lucide icons for familiar commands, tooltips for unfamiliar terms, semantic
buttons and tabs, visible keyboard focus, and responsive overflow checks at both
desktop and mobile sizes. Add fixture routes to
`ui/frontend/tests/fixtures/browser-data.mjs` so browser tests do not depend on
production output.

## Deferred Capabilities

The following remain intentional product decisions, not missing scaffolding:

- exact field-to-call links after artifacts expose stable references
- normalized provider pricing after ledgers persist billable usage/cost
- authentication and remote deployment
- publishing actions
- run or artifact deletion
- arbitrary config-file creation or filesystem browsing
