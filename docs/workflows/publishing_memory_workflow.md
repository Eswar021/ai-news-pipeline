# Publishing Memory Workflow

This is the operational workflow for connecting published YouTube videos back into the pipeline memory system.

## Purpose

This workflow handles:

- OAuth authorization for the owned publishing channel
- authenticated channel sync
- publish-state updates for prepared runs
- analytics ingestion into `performance_memory.jsonl`
- memory rebuild after publication changes

## Current state

As of 2026-05-13:

- OAuth authorization is complete
- authenticated owner-channel sync is complete
- canonical channel ID is `UCp4tfcoFDQIFu7Cnodrqq_w`
- current published video inventory is `0`
- platform-state memory is valid, but editorial/content memory has been reset to a clean baseline before the first real production run

## Files involved

- OAuth client JSON:
  - `secrets/youtube_oauth_client.json`
- OAuth token:
  - `secrets/youtube_oauth_token.json`
- Prepared/published video memory:
  - `memory/video_memory.jsonl`
- Published channel state:
  - `memory/publishing_channel_state.json`
- Published video inventory:
  - `memory/published_video_inventory.jsonl`
- Performance history:
  - `memory/performance_memory.jsonl`

## Commands

### 1. Check local auth status

```bash
python publishing_memory.py status
```

### 2. Run first-time authorization

```bash
python publishing_memory.py auth
```

This opens the browser and stores the refresh token locally.

If you prefer to open the URL yourself:

```bash
python publishing_memory.py auth --no-browser
```

### 3. Sync the owned channel

```bash
python publishing_memory.py sync-channel
```

This updates:

- `publishing_channel_state.json`
- `published_video_inventory.jsonl`
- `performance_memory.jsonl` for already-mapped published videos

### 4. Mark a prepared run as published

```bash
python publishing_memory.py mark-published \
  --run-id <run_id> \
  --youtube-video-id <youtube_video_id>
```

Optional fields:

- `--published-at <ISO timestamp>`
- `--video-url <full video URL>`
- `--no-analytics`

This updates:

- `memory/video_memory.jsonl`
- `memory/story_coverage_memory.jsonl`
- `memory/editorial_pattern_memory.jsonl`
- `memory/performance_memory.jsonl`
- `memory/learning_signals.jsonl`
- `memory/memory_index.json`
- `memory/memory_snapshot.json`

### 5. Optional pre-run channel sync

```bash
python pipeline.py --sync-publishing-channel --preset with_facts
```

Use this when you want the pipeline to refresh publishing-channel state before a normal content run.

## Recommended operating pattern

1. Run Layer 10 after a prepared script is ready.
2. Publish the actual YouTube video.
3. Run `mark-published` with the run ID and the real YouTube video ID.
4. Run `sync-channel` before future runs when you want the latest channel state and analytics reflected in memory.

## Fresh-start cleanup rule

If the channel has no real published videos yet, it is correct to keep:

- `publishing_channel_state.json`
- `published_video_inventory.jsonl`

and reset:

- prepared/editorial memory JSONL files
- `learning_signals.jsonl`
- `memory_index.json`
- `memory_snapshot.json`

Then rebuild the snapshot/index from the empty state. This keeps platform auth/state
intact without polluting the first real runs with exploratory draft history.

## Current limitations

- The first authorization still needs to be performed interactively in the browser.
- Analytics completeness depends on YouTube Analytics availability and time delay.
- Multi-channel publishing workflows are intentionally deferred.
