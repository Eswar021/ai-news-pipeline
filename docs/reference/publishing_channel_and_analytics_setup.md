# Publishing Channel and Analytics Setup

This note captures the current implementation assumptions for the publish-state and analytics workflow.

## Current decision

- Build for a single publishing channel first.
- Future multi-channel support remains in scope, but is deferred.

## Local credential placement

Keep the downloaded OAuth client JSON in:

- `secrets/youtube_oauth_client.json`

Keep the OAuth token generated after first authorization in:

- `secrets/youtube_oauth_token.json`

The project now reads these through `.env`:

- `YOUTUBE_OAUTH_CLIENT_SECRET_PATH`
- `YOUTUBE_OAUTH_TOKEN_PATH`
- `YOUTUBE_PUBLISHING_CHANNEL_HANDLE`

## Current publishing channel

- Current public handle: `https://www.youtube.com/@Eswar-P2`
- This handle is not a stable long-term system identifier because handles can change.
- The system should resolve and store the canonical YouTube `channel_id` after authenticated channel sync.
- Canonical `channel_id` has now been resolved as `UCp4tfcoFDQIFu7Cnodrqq_w`.

## Why single-channel first

Single-channel and multi-channel workflows are related, but they should not be treated as identical.

Single-channel first means:

- one channel thesis
- one audience/config identity
- one publishing-memory namespace
- one analytics owner context
- one prompt/editorial strategy surface

Multi-channel later would likely require:

- per-channel thesis/config
- per-channel memory partitions
- per-channel publishing credentials or owner mapping
- per-channel prompt and handoff strategy selection
- routing logic for which run targets which channel

## Recommended sync model

For an owned publishing channel, a lightweight sync before each run is recommended.

Recommended pre-run sync scope:

- canonical `channel_id`
- current published video inventory
- publish timestamps
- title / metadata refresh for already-published videos
- recent analytics snapshots for videos that are still inside the active learning window

Not recommended as pre-run sync behavior:

- overwriting channel thesis or prompt strategy from YouTube metadata
- rebuilding the full memory store from scratch every run
- treating platform metadata as the source of truth for editorial configuration

Recommended ownership split:

- YouTube sync updates platform-state memory
- local config plus Layer 0 manifest remain the source of truth for editorial behavior

## Current channel history state

- published video count to backfill: `0`
- no historical analytics backfill is currently needed

## Auth requirement

The existing `YOUTUBE_API_KEY` is not enough for the full publish-memory workflow.

It is fine for public-data collection use cases such as:

- searching public videos
- reading public metadata from monitored channels
- transcript/source discovery in Layer 1

It is not sufficient for:

- reading authenticated owner-channel data as `mine=true`
- reading private or owner-scoped channel/video state
- pulling YouTube Analytics metrics for the publishing channel

For full publishing-memory and analytics support, the project needs OAuth 2.0 credentials.

Recommended initial scope for this project:

- YouTube Data API v3
- YouTube Analytics API
- OAuth client for a local/desktop app flow

Suggested first-pass OAuth scopes:

- `https://www.googleapis.com/auth/youtube.readonly`
- `https://www.googleapis.com/auth/yt-analytics.readonly`

If later we want programmatic upload or metadata updates, broader scopes may be needed.

## Current auth and sync status

Completed on 2026-05-13:

- OAuth authorization was completed successfully
- local token storage is now in use on this machine
- authenticated owner-channel sync completed successfully
- canonical channel metadata is stored in `memory/publishing_channel_state.json`
- current published inventory is `0` videos, so there is no historical analytics backfill to ingest yet

The canonical `channel_id` did not need to be provided manually because the system resolved it through authenticated channel sync.

## Implemented workflow surface

The project now has a local CLI for the publishing-memory workflow:

- `python publishing_memory.py status`
- `python publishing_memory.py auth`
- `python publishing_memory.py sync-channel`
- `python publishing_memory.py mark-published --run-id <run_id> --youtube-video-id <youtube_video_id>`

There is also an optional pipeline hook:

- `python pipeline.py --sync-publishing-channel ...`

This hook is explicit rather than automatic by default so a failed channel sync does not silently interfere with unrelated pipeline runs.

## Official references

- YouTube Data API OAuth guide:
  https://developers.google.com/youtube/v3/guides/authentication
- YouTube Analytics OAuth guide:
  https://developers.google.com/youtube/reporting/guides/authorization
- OAuth credential setup:
  https://developers.google.com/youtube/reporting/guides/registering_an_application
