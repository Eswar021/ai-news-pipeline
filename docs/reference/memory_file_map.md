# Memory File Map

This note explains which files in `memory/` are authoritative records, which are
derived summaries, and which belong to the publishing-channel sync workflow.

## Core rule

- Layer 0 does **not** generate memory files.
- Layer 0 only plans memory policy and snapshots memory paths into the run manifest.
- Layer 10 writes the durable cross-run editorial/evidence memory after a run is verified.
- `publishing_memory.py` updates publishing-platform state after OAuth sync or after a prepared run becomes a real published video.

## Authoritative Layer 10 memory records

These are the primary durable records written by `run_layer_10.py`.

### `video_memory.jsonl`

- Written by: `video_memory_writer.py`
- Purpose: one prepared-or-published video record per run
- Read by: Layer 5 novelty, `chatgpt_export.py`, publishing-state updater, channel sync, repetition checker
- Status: core authoritative memory

### `story_coverage_memory.jsonl`

- Written by: `story_coverage_memory_writer.py`
- Purpose: which stories were covered by which video
- Read by: `memory_snapshot_builder.py`, `memory_index_builder.py`, `chatgpt_export.py`
- Status: core authoritative memory

### `claim_ledger.jsonl`

- Written by: `claim_ledger_writer.py`
- Purpose: durable ledger of verified claims that were actually used
- Read by: `memory_index_builder.py`, future verification/memory consumers
- Status: authoritative memory, currently light active consumption

### `entity_topic_memory.jsonl`

- Written by: `entity_topic_memory_writer.py`
- Purpose: cross-run coverage history for entities and topics
- Read by: `learning_signal_builder.py`, `memory_snapshot_builder.py`, `memory_index_builder.py`
- Status: authoritative memory

### `source_memory.jsonl`

- Written by: `source_memory_writer.py`
- Purpose: source/domain usage and trust-tier history
- Read by: `learning_signal_builder.py`, `memory_snapshot_builder.py`, `memory_index_builder.py`
- Status: authoritative memory

### `editorial_pattern_memory.jsonl`

- Written by: `editorial_pattern_memory_writer.py`
- Purpose: hook, title-angle, thumbnail-text, and framing memory
- Read by: `chatgpt_export.py`, publishing sync, repetition checker, derived snapshot builders
- Status: authoritative memory

### `followups.jsonl`

- Written by: `followup_tracker.py`
- Purpose: unresolved follow-up opportunities for future runs
- Read by: Layer 5 novelty, `learning_signal_builder.py`, `memory_snapshot_builder.py`, `memory_index_builder.py`
- Status: authoritative memory

### `evidence_gap_watchlist.jsonl`

- Written by: `evidence_gap_watchlist_writer.py`
- Purpose: track evidence gaps worth watching across runs
- Read by: `memory_index_builder.py`, future follow-up/risk workflows
- Status: authoritative memory

### `rejected_claim_patterns.jsonl`

- Written by: `rejected_claim_pattern_writer.py`
- Purpose: store risky/rejected claim patterns that should not be recycled later
- Read by: future Layer 8/9 risk consumers
- Status: authoritative memory, mostly future-facing today

## Publishing-channel and analytics memory

These are maintained by `publishing_memory.py` and related publishing helpers.

### `performance_memory.jsonl`

- Written by: `performance_memory_writer.py` through publish-state updates and owner-channel sync
- Purpose: real YouTube performance metrics attached to published videos
- Read by: `learning_signal_builder.py`, `memory_snapshot_builder.py`
- Status: authoritative publishing-performance memory

### `publishing_channel_state.json`

- Written by: `publishing_channel_sync.py`
- Purpose: authenticated owner-channel metadata and current channel state
- Read by: operators and publishing workflow
- Status: authoritative publishing-platform state

### `published_video_inventory.jsonl`

- Written by: `publishing_channel_sync.py`
- Purpose: inventory of videos currently published on the owned channel
- Read by: operators and publishing workflow
- Status: authoritative publishing-platform state

## Derived memory artifacts

These are rebuilt from the authoritative records above.

### `learning_signals.jsonl`

- Written by: `learning_signal_builder.py`
- Purpose: compact reusable learning hints derived from current memory state
- Read by: mainly human/debug/reference today
- Status: derived artifact

### `memory_index.json`

- Written by: `memory_index_builder.py`
- Purpose: searchable cross-file index for quick lookup by video/story/entity/topic/source
- Read by: `memory_snapshot_builder.py`, future convenience consumers
- Status: derived artifact

### `memory_snapshot.json`

- Written by: `memory_snapshot_builder.py`
- Purpose: compact published-memory guidance for later layers and handoff/export
- Read by: Layer 5-adjacent workflows, `chatgpt_export.py`, future Layer 7 consumers
- Status: derived artifact

## Which files are actually needed now

The short answer is yes, the folder is valid, but not every file has the same role.

- Core files needed right now:
  - `video_memory.jsonl`
  - `story_coverage_memory.jsonl`
  - `editorial_pattern_memory.jsonl`
  - `followups.jsonl`
  - `memory_snapshot.json`
  - `memory_index.json`
  - `publishing_channel_state.json`
  - `published_video_inventory.jsonl`
  - `performance_memory.jsonl`
- Important but more future-facing:
  - `claim_ledger.jsonl`
  - `entity_topic_memory.jsonl`
  - `source_memory.jsonl`
  - `evidence_gap_watchlist.jsonl`
  - `rejected_claim_patterns.jsonl`
  - `learning_signals.jsonl`

The final architecture does not require every memory file to be heavily consumed today.
Some exist because Layer 10 is meant to be a durable channel-memory layer, not only a
minimal cache for the currently active features.
