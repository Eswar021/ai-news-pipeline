# 2026-05-12 System Audit

## Scope

This audit covers:

- LLM model selection and hardcoded model usage
- Config ownership and whether config is actually being consumed
- Time-window behavior and source collection behavior
- Layer-by-layer output files that matter downstream
- ChatGPT handoff generation behavior
- Memory behavior, especially published vs prepared runs
- Legacy pipeline folders still present in the repo
- Functional gaps between the current pipeline and the design docs
- Why LLM logs are missing for current runs

The live pipeline audited here is the `pipeline.py` flow that runs:

`layer_0_control` → `layer_1_extraction` → `layer_2_canonicalization` → `layer_3_story_processing` → `layer_4_evidence_intelligence` → `layer_5_editorial_intelligence` → `layer_6_research_packets` → `layer_7_content_planning` → `layer_8_script_generation` → `layer_9_verification_firewall` → `layer_10_memory_learning`

---

## Executive Summary

- `config/llm_config.py` is the intended model source, and the last known hardcoded `gpt-4o-mini` usages were removed from Layer 8 and Layer 9 on 2026-05-12.
- Layer 0 correctly computes run-time collection windows, but Layer 1 still does not fully enforce those windows when dispatching collectors.
- YouTube collection is configured, but the main Layer 1 orchestrator still skips it.
- ChatGPT handoff generation had a format-selection bug for `auto` runs; this was fixed on 2026-05-12 so the exporter now infers the actual selected format from downstream outputs.
- The handoff memory block was also corrected on 2026-05-12 so unpublished runs no longer show up as past-video repetition guidance.
- Raw Layer 10 memory still records prepared runs, which is useful for audit, but only published runs should drive novelty and repetition decisions.
- The legacy folders `layer_2_processing`, `layer_3_intelligence`, and `layer_4_content` are not part of the current pipeline path.
- LLM logs are missing for the modern pipeline because the active async OpenAI modules bypass `llm/llm_logger.py`.

---

## 1. LLM Model Config Audit

### Current source of truth

The intended source of truth is [config/llm_config.py](../../config/llm_config.py).

- `ACTIVE_PROFILE` controls the global default profile.
- `MODULE_OVERRIDES` can override individual modules.
- Each profile currently carries `provider`, `model`, and `temperature`.

### Hardcoded model usage found and fixed

The following files had direct `gpt-4o-mini` usage and were updated to read from `get_profile(...)` instead:

- [pipelines/layer_8_script_generation/roundup_script_writer.py](../../pipelines/layer_8_script_generation/roundup_script_writer.py)
- [pipelines/layer_8_script_generation/deep_dive_script_writer.py](../../pipelines/layer_8_script_generation/deep_dive_script_writer.py)
- [pipelines/layer_9_verification_firewall/sentence_support_verifier.py](../../pipelines/layer_9_verification_firewall/sentence_support_verifier.py)

### Other LLM modules using the config correctly

These modules already read model settings from `config/llm_config.py`:

- `layer_4_evidence_intelligence/claim_extractor.py`
- `layer_5_editorial_intelligence/viewer_value_analyzer.py`
- `layer_5_editorial_intelligence/editorial_brief_builder.py`
- `layer_7_content_planning/hook_planner.py`
- `layer_7_content_planning/title_thumbnail_planner.py`

### Remaining limitation

`llm_config.py` is only partially authoritative today.

- Model and temperature are centralized.
- Provider routing is not fully abstracted.
- Several active modules still instantiate `AsyncOpenAI` directly, so a non-OpenAI provider in `llm_config.py` will not work transparently everywhere.

### Recommendation

High priority:

1. Introduce one shared async LLM client wrapper for the active pipeline.
2. Make every modern LLM module call that wrapper instead of `AsyncOpenAI` directly.
3. Route logging through that same wrapper so model selection and LLM logging stay coupled.

---

## 2. Config Inventory and Ownership

### What each config file currently does

| Config file | Current purpose | Main consumer(s) | Status |
| --- | --- | --- | --- |
| `config/pipeline_config.yaml` | Layer presets and CLI defaults | `pipeline.py` | Active |
| `config/run_defaults.yaml` | Lookback, depth, run defaults | Layer 0, `pipeline.py` CLI overrides | Active |
| `config/channel_thesis.yaml` | Channel identity and thesis | Layer 0 | Active |
| `config/audience_profiles.yaml` | Audience profile definitions | Layer 0 | Active |
| `config/format_config.yaml` | Enabled formats and format requirements | Layer 0, Layer 5, Layer 7 | Active |
| `config/quality_rules.yaml` | Quality policy | Layer 0 | Active |
| `config/sources.yaml` | Per-source definitions and enable flags | Layer 0, Layer 1 | Active |
| `config/source_strategy.yaml` | Source grouping and source-policy structure | Layer 0, Layer 1 | Active |
| `config/channels.yaml` | YouTube channel definitions | Standalone YouTube collector path | Active but not wired into main Layer 1 flow |
| `config/chatgpt_prompts.yaml` | Shared prompt blocks for handoff exporter | `chatgpt_export.py` | Active |
| `config/entity_topic_taxonomy.yaml` | Entity/topic normalization taxonomy | Layer 3 | Active |
| `config/llm_config.py` | LLM profiles and overrides | Active LLM modules | Active |
| `config/scoring_config.yaml` | Intended scoring config | No active consumer found in current pipeline | Likely dead / removable |

### Are configs only used by Layer 0?

No.

- Layer 0 owns the run-manifest assembly from channel, audience, format, quality, source, and run-default configs.
- Later layers still read config directly in a few places:
  - `format_config.yaml` is read again in Layer 5.
  - `chatgpt_prompts.yaml` is read by `chatgpt_export.py`.
  - `entity_topic_taxonomy.yaml` is read by Layer 3.
  - `llm_config.py` is read by active LLM modules.
  - `channels.yaml` is used by the standalone YouTube collector path.

### Should these files be merged?

A full merge would probably make the system harder to reason about. The better cleanup is a smaller, clearer grouping:

Keep separate:

- `pipeline_config.yaml` for execution presets
- `run_defaults.yaml` for run-time defaults
- `channel_thesis.yaml` and `audience_profiles.yaml` for editorial identity
- `format_config.yaml` for format enablement and format rules
- `sources.yaml`, `source_strategy.yaml`, and `channels.yaml` for source definitions
- `chatgpt_prompts.yaml` for handoff behavior
- `entity_topic_taxonomy.yaml` for Layer 3 mapping
- `llm_config.py` for LLM profiles

Remove or merge:

- `scoring_config.yaml` if it truly remains unused

### Important code-level note

[config/paths.py](../../config/paths.py) had stale layer path constants for Layer 9 and Layer 10. Those were corrected on 2026-05-12, and prompt/taxonomy config constants were added there as well.

---

## 3. Time Windows and Source Collection

### What the design docs intend

The design docs put time-window control in Layer 0. The run manifest should define:

- collection horizon
- source-specific windowing
- recency expectations for the run

### What the current system does

Layer 0 does compute those windows and writes them into `run_manifest.json`.

What is still missing:

- Layer 1 does not fully apply those window definitions when it dispatches collectors.
- Collector calls still mostly rely on fixed parameters like `max_per_source`, `max_per_category`, or default query behavior.

### Current state of YouTube collection

YouTube is not fully wired into the main orchestration path.

- `config/channels.yaml` exists.
- `config/sources.yaml` and `config/source_strategy.yaml` include YouTube-related source groups.
- The main Layer 1 orchestrator still prints a skip message for YouTube and does not collect it in normal runs.

See [pipelines/layer_1_extraction/run_layer_1.py](../../pipelines/layer_1_extraction/run_layer_1.py).

### Recommendation

High priority:

1. Carry channel IDs and source-specific collection windows into the run manifest in a form Layer 1 can consume directly.
2. Update each collector call to accept `start_at` or `lookback_days` from manifest-derived policy.
3. Wire YouTube collection into `run_layer_1.py` instead of keeping it as a separate manual path.

---

## 4. Layer-Wise Master Outputs

These are the main downstream files to inspect for each layer.

| Layer | Main files to inspect | Why they matter |
| --- | --- | --- |
| Layer 0 | `data/runs/{run_id}/run_manifest.json` | Run contract and config snapshot |
| Layer 1 | `data/runs/{run_id}/layer_1/raw_documents.jsonl`, `extraction_manifest.json` | Raw collected corpus and collection summary |
| Layer 2 | `data/runs/{run_id}/layer_2/canonical_documents.jsonl`, `source_spans.jsonl`, `provenance_map.jsonl` | Canonical text, evidence spans, provenance |
| Layer 3 | `data/runs/{run_id}/layer_3/story_clusters.json`, `ranked_stories.json` | Story objects and ranking |
| Layer 4 | `data/runs/{run_id}/layer_4/verified_claims.jsonl`, `story_fact_sheets.json`, `evidence_gaps.json` | Evidence-ready claims and story fact packets |
| Layer 5 | `data/runs/{run_id}/layer_5/selected_video_brief.json`, `editorial_candidates.json`, `format_routing_decisions.json` | Editorial selection and routing |
| Layer 6 | `data/runs/{run_id}/layer_6/research_packet.json`, `source_pack.json`, `claim_section_map.json` | Format-specific research packet |
| Layer 7 | `data/runs/{run_id}/layer_7/script_writer_brief.json`, `video_plan.json` | Consolidated plan for the script writer |
| Layer 8 | `data/runs/{run_id}/layer_8/generated_script.json`, `script.md`, `youtube_metadata.json` | Generated script and publishing metadata |
| Layer 9 | `data/runs/{run_id}/layer_9/verified_script.md`, `final_publish_package.json`, `verification_report.json` | Verified script and publish package |
| Layer 10 | `data/runs/{run_id}/layer_10/layer10_manifest.json`, `memory/memory_snapshot.json`, `memory/memory_index.json` | Memory write audit and future-run guidance |

For a shorter cheat sheet, see [docs/reference/layer_output_map.md](../reference/layer_output_map.md).

---

## 5. ChatGPT Handoff Audit

### The bug that was happening

For `auto` runs, `01_instructions.md` could still describe the video as a roundup even when the actual selected format downstream was `deep_dive`.

### Root cause

The exporter was using the first eligible format from the run manifest instead of the format actually selected by later layers.

### Fix applied on 2026-05-12

[chatgpt_export.py](../../chatgpt_export.py) now resolves the active format from downstream artifacts in this order:

1. Layer 8 `generated_script.json`
2. Layer 7 `script_writer_brief.json`
3. Layer 6 `research_packet.json`
4. Layer 5 `selected_video_brief.json`
5. Manifest fallback only if nothing downstream exists

### Current handoff behavior

- Shared prompt blocks still come from `config/chatgpt_prompts.yaml`.
- Format-specific instruction blocks are now resolved dynamically.
- Deep-dive runs now get deep-dive-specific instruction wording.
- The memory block now only uses published-video history.

### Remaining limitation

The exporter is more dynamic than before, but it is not fully config-driven yet.

Still code-defined today:

- format-specific instruction assembly
- some fallback logic
- how memory is rendered into instructions

### Recommendation

Medium priority:

Create a dedicated handoff config family if you want prompt behavior to be fully strategy-specific:

- `roundup`
- `deep_dive`
- `evergreen`
- `comparison`
- `follow_up`

That config should define:

- instruction blocks
- required output format
- strategy-specific review checklist
- which memory sections are relevant

---

## 6. Memory Behavior

### What exists today

Layer 10 writes raw memory files such as:

- `memory/video_memory.jsonl`
- `memory/story_coverage_memory.jsonl`
- `memory/editorial_pattern_memory.jsonl`
- `memory/followups.jsonl`
- `memory/memory_index.json`
- `memory/memory_snapshot.json`

### Why unpublished runs were showing up

`video_memory_writer.py` stores records with:

- `status = prepared_for_human_review`
- `timestamps.published_at = null`

That is fine for run history. The problem was downstream consumers treating those records like published-video memory.

### Fixes applied on 2026-05-12

1. `chatgpt_export.py` now only uses published memory for the handoff repetition block.
2. `memory_snapshot_builder.py` now builds repetition guidance and covered-story guidance from published videos only.
3. `novelty_checker.py` now only considers published videos inside the recency window.

### What still does not exist

There is still no built publication-state workflow.

Not present yet:

- automatic YouTube channel sync into memory
- performance ingest from real video analytics
- a first-class utility to mark a prepared run as published

### Recommended model going forward

Keep both concepts:

1. Raw run memory
   - every prepared script/run can remain in raw memory files for audit
2. Published memory
   - only published videos should affect novelty, repetition avoidance, and handoff guidance

### Practical correction path

Best next step:

Add a small utility that updates a matching `video_memory.jsonl` record with:

- `status = published`
- `timestamps.published_at = <real publish timestamp>`
- optional `youtube_video_id`

Then rebuild:

- `memory/memory_index.json`
- `memory/memory_snapshot.json`

This is safer than manually inventing whole new JSON objects from scratch.

---

## 7. Legacy Folders Audit

These legacy folders still exist:

- `pipelines/layer_2_processing`
- `pipelines/layer_3_intelligence`
- `pipelines/layer_4_content`

### Are they used by the current pipeline?

No.

The current `pipeline.py` path uses:

- `layer_2_canonicalization`
- `layer_3_story_processing`
- `layer_4_evidence_intelligence`

### What they are still affecting

- README and old docs still reference them
- legacy `llm_logger.py` usage lives there
- some path constants and comments still acknowledge legacy outputs

### Recommendation

Medium priority:

1. Remove them only after the README and any direct scripts are updated.
2. If you want to preserve historical context, move them to an `archive/` area first.
3. Do not keep them half-documented as if they are still the active pipeline.

---

## 8. Functional Gaps vs Design Docs

This section focuses on functionality, not folder structure.

### Layer 1

- Time windows are computed but not fully enforced in collector dispatch.
- YouTube orchestration is still skipped in the main run path.

### Layer 2

- The design called for more explicit source-type parser modules.
- The current Layer 2 works, but transcript-specific parsing remains effectively skipped until YouTube is wired in.

### Layer 3

- Entity-overlap clustering is lighter than the design intended.
- Community/news attachment behavior is simpler than the design version.
- Cluster confidence does not use embedding-based confidence scoring.

### Layer 5

- Portfolio balancing is soft, not a true diversity constraint.
- Several threshold families are still inline constants rather than explicit config.

### Layer 6

- Only `roundup` and `deep_dive` packet builders exist.
- `evergreen`, `comparison`, and `follow_up` paths are still intentionally absent.

### Layer 7

- Planning exists only for `roundup` and `deep_dive`.
- Strategy-internal rules still live mostly as inline constants.

### Layer 8

- No script writers yet for `evergreen`, `comparison`, or `follow_up`.
- `sentence_claim_map.jsonl` is not built at sentence granularity.
- Multiple metadata files from the design were consolidated into `youtube_metadata.json`.

### Layer 9

- Repetition checker is still missing.
- Contradiction/evidence-gap handling is mostly informational right now.

### Layer 10

- Performance ingest is not built.
- There is no publish-state updater or real channel-ingest workflow.

### Priority view

Build next:

1. Layer 1 time-window enforcement
2. Layer 1 YouTube orchestration
3. Published-state memory workflow
4. Shared async LLM wrapper with logging
5. Repetition checker in Layer 9

Build later:

- disabled format branches
- extra config-file extraction for purely internal constants
- structural parity items that do not unlock new behavior

---

## 9. Why LLM Logs Are Missing

### What exists

[llm/llm_logger.py](../../llm/llm_logger.py) exists and writes structured JSON logs.

### Why the current runs do not show logs

The active pipeline path mostly uses modern async OpenAI modules that do not call `llm_logger.py`.

Legacy folders still use it:

- `layer_3_intelligence`
- `layer_4_content`

The active layers mostly bypass it:

- Layer 4 evidence extractor
- Layer 5 viewer/editorial modules
- Layer 7 planners
- Layer 8 script writers
- Layer 9 sentence support verifier

### Recommendation

High priority:

Create one shared async LLM call wrapper that handles:

- provider routing
- temperature/model kwargs
- request/response logging
- per-run log destination

Until that exists, `output/llm_logs/` will remain incomplete for the modern pipeline.

---

## 10. Suggested Cleanup Order

### First

1. Finish config centralization around LLM calls and logging.
2. Wire time-window policy from Layer 0 into Layer 1 collectors.
3. Wire YouTube collection into the main Layer 1 orchestration path.
4. Add a publish-state updater for Layer 10 memory.

### Second

1. Update README so it reflects the real 0→10 pipeline.
2. Retire or archive legacy Layer 2/3/4 folders.
3. Remove or merge `config/scoring_config.yaml` if it remains unused.

### Third

1. Revisit disabled format branches when the editorial strategy actually needs them.
2. Move inline per-layer constants into config only where that improves operator control.

