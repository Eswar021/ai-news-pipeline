# ChatGPT Handoff Strategy

This is the current, code-accurate reference for ChatGPT handoff generation.

## Purpose

The pipeline stops at a chosen point, exports structured artifacts, and lets ChatGPT do the final writing work where narrative judgment matters most.

The exporter is [chatgpt_export.py](../../chatgpt_export.py).

## Output files

Each export run writes three files to `output/chatgpt_handoffs/{run_id}/`:

- `01_instructions.md`
- `02_stories.md`
- `03_dump.md`

The exporter requires a completed Layer 3 handoff minimum.

If a run does not have `layer_3/ranked_stories.json`, the exporter now stops with a clear error instead of generating an empty story handoff.

## What drives the handoff

### Shared config

- `config/chatgpt_prompts.yaml` provides shared prompt blocks and wording.

### Dynamic run inputs

- `data/runs/{run_id}/run_manifest.json`
- Layer 3 ranked stories and story map
- Layer 4 fact sheets and verified claims when present
- Layer 5 selected brief when present
- Layer 6 research packet when present
- Layer 7 script writer brief when present
- Layer 8 generated script when present

## How the exporter decides the active format

The exporter resolves the actual selected format from downstream artifacts, not just from Layer 0 eligibility.

Current resolution order:

1. Layer 8 `generated_script.json`
2. Layer 7 `script_writer_brief.json`
3. Layer 6 `research_packet.json`
4. Layer 5 `selected_video_brief.json`
5. Run-manifest fallback

This matters for `auto` runs, where the manifest may list multiple eligible formats but the pipeline later selects one concrete format.

## Memory behavior

`01_instructions.md` may include a repetition-avoidance section, but only published-video history should be used for that.

Current rule:

- raw run memory can exist for prepared runs
- published-memory guidance in the handoff only comes from records that have `timestamps.published_at`

This prevents unpublished drafts from being treated like channel history.

## Current strategy split

Right now the exporter has:

- shared prompt content from config
- code-defined format-specific blocks for `roundup` and `deep_dive`

If more strategies become active later, the clean next step is to make those strategy blocks config-driven too.

## Related docs

- [System Audit — 2026-05-12](../audits/2026-05-12_system_audit.md)
- [Layer Output Map](../reference/layer_output_map.md)
