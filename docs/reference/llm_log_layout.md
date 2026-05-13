# LLM Log Layout

This document describes the current active LLM log structure for the async pipeline runtime.

## Source of truth

The active runtime logger is:

- `llm/async_llm_runtime.py`

All active async LLM modules in Layers 4, 5, 7, 8, and 9 now log through that shared runtime.

## Layout

Logs are stored under:

- `output/llm_logs/{run_id}/`

Within each run:

- one folder per layer
- one JSONL file per active module
- one root summary file

Example:

```text
output/llm_logs/run_2026_05_13_48h_roundup/
  llm_log_summary.json
  layer_4/
    claim_extractor.jsonl
  layer_5/
    viewer_value_analyzer.jsonl
    editorial_brief_builder.jsonl
  layer_7/
    hook_planner.jsonl
    title_thumbnail_planner.jsonl
  layer_8/
    roundup_script_writer.jsonl
    deep_dive_script_writer.jsonl
  layer_9/
    sentence_support_verifier.jsonl
```

## Why this layout

The previous per-call file layout made it hard to answer simple questions like:

- how many calls happened in Layer 4?
- which module is generating the most traffic?
- did a module fail repeatedly in this run?

The new layout makes those answers available without opening hundreds of files.

## Summary file

Each run root now has:

- `llm_log_summary.json`

It tracks:

- total calls for the run
- status counts for the run
- totals per layer
- totals per module
- the JSONL path for each module
- last request name and completion timestamp per module

## Current module-to-layer mapping

- `claim_extractor` → `layer_4`
- `viewer_value_analyzer` → `layer_5`
- `editorial_brief_builder` → `layer_5`
- `hook_planner` → `layer_7`
- `title_thumbnail_planner` → `layer_7`
- `roundup_script_writer` → `layer_8`
- `deep_dive_script_writer` → `layer_8`
- `sentence_support_verifier` → `layer_9`

## Notes

- The log path returned to callers now points to the module JSONL file, not to a unique per-call JSON file.
- The runtime keeps this centralized so new active LLM modules can inherit the same logging behavior without each module needing custom logging logic.
