# 2026-05-12 System Audit

## Scope

This audit covers:

- LLM model selection and hardcoded model usage
- Config ownership and whether config is actually being consumed
- Time-window behavior and source collection behavior
- Layer-by-layer output files that matter downstream
- Run completeness and output-contract enforcement status
- Downstream data flow and artifact ownership across layers
- ChatGPT handoff generation behavior
- Memory behavior, especially published vs prepared runs
- Memory workflow parity versus the design docs
- Legacy pipeline folders still present in the repo
- Functional gaps between the current pipeline and the design docs
- Why LLM logs are missing for current runs

The live pipeline audited here is the `pipeline.py` flow that runs:

`layer_0_control` → `layer_1_extraction` → `layer_2_canonicalization` → `layer_3_story_processing` → `layer_4_evidence_intelligence` → `layer_5_editorial_intelligence` → `layer_6_research_packets` → `layer_7_content_planning` → `layer_8_script_generation` → `layer_9_verification_firewall` → `layer_10_memory_learning`

For the feature-oriented build backlog derived from this audit and the design docs, see [system_completion_feature_map.md](../roadmaps/system_completion_feature_map.md).

---

## Executive Summary

- `config/llm_config.py` is the intended model source, and the last known hardcoded `gpt-4o-mini` usages were removed from Layer 8 and Layer 9 on 2026-05-12.
- Layer 0 correctly computes run-time collection windows, and Layer 1 now enforces them in the active path with a mix of fetch-side narrowing and post-fetch filtering.
- YouTube collection is now wired into the main Layer 1 orchestrator through the `resolved_config.youtube_channels` manifest snapshot authored from `channels.yaml`.
- The design rule that downstream layers should read the Layer 0 run manifest is now implemented in the active runtime path through `resolved_config` snapshots in `run_manifest.json`; downstream runtime consumers no longer fall back to original repo config files.
- ChatGPT handoff generation had a format-selection bug for `auto` runs; this was fixed on 2026-05-12 so the exporter now infers the actual selected format from downstream outputs.
- ChatGPT handoff export now also refuses partial runs that never produced Layer 3 outputs, instead of generating empty story handoffs.
- Core run-completeness enforcement was added on 2026-05-12: the pipeline now checks for each layer's minimum required artifacts and honors the layer's existing validation report instead of assuming success from "no exception raised".
- The handoff memory block was also corrected on 2026-05-12 so unpublished runs no longer show up as past-video repetition guidance.
- A Layer 4 write-path bug was fixed on 2026-05-13: `layer4_writer.py` was incorrectly reading `confidence_label` from an already-flattened verified-claim record shape, which caused the run to fail after successful claim extraction and verification.
- Active generated pipeline timestamps were standardized to the configured project timezone on 2026-05-13. The source of truth remains `config/run_defaults.yaml` with `Asia/Kolkata`, and the active pipeline now uses shared helpers for run manifests, layer manifests, memory records, and LLM logs. Canonical source `published_at` normalization and some internal elapsed-time math intentionally remain UTC-based.
- Raw Layer 10 memory still records prepared runs, which is useful for audit, but only published runs should drive novelty and repetition decisions.
- The active pipeline is not a strict Layer N → Layer N+1 chain. It behaves as a DAG of authoritative artifacts, and later layers intentionally reach back to Layer 2, Layer 3, and Layer 4.
- A single mutable master file is not recommended as the primary source of truth. A compiled `run_state.json` or `run_graph.json` artifact is the better future direction.
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
| `config/format_config.yaml` | Enabled formats and format requirements | Layer 0 authoring input | Active |
| `config/quality_rules.yaml` | Quality policy | Layer 0 | Active |
| `config/sources.yaml` | Per-source definitions and enable flags | Layer 0 authoring input | Active |
| `config/source_strategy.yaml` | Source grouping and source-policy structure | Layer 0 authoring input | Active |
| `config/channels.yaml` | YouTube channel definitions | Layer 0 authoring input | Active |
| `config/chatgpt_prompts.yaml` | Shared prompt blocks for handoff exporter | Layer 0 authoring input | Active |
| `config/entity_topic_taxonomy.yaml` | Entity/topic normalization taxonomy | Layer 0 authoring input | Active |
| `config/llm_config.py` | LLM profiles and overrides | Layer 0 authoring input | Active |
| `config/scoring_config.yaml` | Intended scoring config | No active consumer found in current pipeline | Likely dead / removable |

### Are configs only used by Layer 0?

By design, authoring configs are Layer 0 inputs.

- Layer 0 owns the run-manifest assembly from channel, audience, format, quality, source, LLM, taxonomy, and handoff-prompt configs.
- In the active downstream runtime path, those values are now read from the run manifest instead of the original config files.
- Direct config reads still remain in Layer 0 by design and in some standalone/inactive authoring utilities.

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

### Manifest authority versus direct config reads

The design docs are explicit on this point:

- Layer 0 should read the authoring config files
- Layer 0 should resolve them into one immutable `run_manifest.json`
- downstream layers should read the manifest rather than re-reading config files

See [layer_0.md](../system_design_docs/layer_0.md) and the dedicated reference note [manifest_authority_and_config_ownership.md](../reference/manifest_authority_and_config_ownership.md).

As of 2026-05-12, the active runtime path now follows that rule.

Manifest-driven in the active path:

- Layer 1 collection windows, enabled source groups, and query themes
- Layer 1 resolved source registry subset
- Layer 1 resolved YouTube channel subset
- Layer 3 entity/topic taxonomy
- Layer 5 format requirements
- active LLM module profile selection in Layers 4, 5, 7, 8, and 9
- ChatGPT handoff prompt config
- Layer 0 memory policy, memory paths, depth limits, and output contracts

Still not fully strict:

- Layer 0 still reads authoring config files by design
- some standalone or inactive utilities still read config files directly

Recommended architectural rule:

1. `config/` files remain authoring inputs.
2. Layer 0 snapshots the effective run-scoped values into the manifest.
3. Downstream layers consume the manifest plus upstream artifacts, not the original config files.

The important nuance is that the manifest should carry the resolved subset used by the run, not an uncontrolled dump of every raw config file.

### What was implemented on 2026-05-12

Layer 0 now writes a `resolved_config` section into `run_manifest.json` with run-scoped snapshots for:

- active source registry subset
- enabled YouTube channel registry subset
- effective LLM runtime profiles
- entity/topic taxonomy
- ChatGPT handoff prompt config

The following active consumers were switched to use those manifest snapshots:

- Layer 1 source registry loading
- Layer 1 YouTube channel loading
- Layer 3 entity/topic mapping
- Layer 5 format config usage
- active LLM modules in Layers 4, 5, 7, 8, and 9
- `chatgpt_export.py`

### Why this drift happened

The implementation decisions show the original intent was already manifest-driven, but the system drifted for practical reasons while the workflow was being completed:

- existing collectors/helpers were wrapped rather than fully rewritten
- some later modules were implemented faster by reading local config directly
- the main focus at the time was end-to-end functionality, not full control-plane cleanup

So this was not forgotten. The main active-path migration is now done, and what remains is cleanup of standalone/inactive utilities and any remaining tooling ambiguity.

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

As of 2026-05-12, Layer 1 now also consumes those manifest fields in the active path:

- `collection_strategy.enabled_source_groups`
- `collection_strategy.query_themes`
- `collection_strategy.collection_window`
- `collection_strategy.source_specific_windows`

The main Layer 1 orchestration no longer relies on the older wrong manifest keys for enabled groups and query themes.

### What was implemented on 2026-05-12

Manifest-driven window enforcement is now partially operational in Layer 1:

- source-group windows are resolved from the run manifest during orchestration
- collectors receive `start` / `end` bounds for post-fetch filtering
- collectors that already support fetch-side recency narrowing also receive a `days_back` value where useful
  - currently this is applied to NewsAPI and GitHub search
- `extraction_manifest.json` now records the collection policy that was applied for the run

This means Layer 1 now enforces the configured collection windows on the produced `raw_documents.jsonl` corpus instead of only computing them in Layer 0.

What is still missing:

- some collectors still fetch first and then filter locally because the upstream source/API wrapper does not support reliable server-side date constraints
- documents with missing or unparseable `published_at` are currently kept and surfaced via audit warnings instead of being dropped
- collector sizing still largely relies on fixed caps like `max_per_source` and `max_per_category`

### Current state of YouTube collection

As of 2026-05-12, YouTube is now wired into the main Layer 1 orchestration path.

What is now active:

- `run_layer_1.py` invokes the YouTube wrapper when `youtube_podcast_transcripts` is enabled and `--skip-youtube` is not used
- the wrapper loads enabled channels from `run_manifest.json` `resolved_config.youtube_channels`
- manifest-driven `days_back`, `start`, and `end` window policy is passed into the YouTube path
- channel-specific `search_query` values snapshotted from `channels.yaml` are preserved, with the Layer 1 query-plan value used when a channel entry has no query

What still remains limited:

- YouTube collection still depends on `YOUTUBE_API_KEY`
- transcript availability remains source-dependent, so some discovered videos may still be partial or unavailable
- this step did not yet make YouTube channel selection manifest-driven beyond the existing channel registry

### Recommendation

Still high priority:

1. Extend fetch-side recency filtering to any remaining sources where the upstream API supports it safely.
2. Decide whether undated documents should remain soft-kept or become format-dependent hard exclusions later.
3. If needed later, make the YouTube channel subset itself manifest-selectable rather than always registry-driven.

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

## 4A. Run Completeness and Output-Contract Enforcement

### What is implemented now

The active pipeline now enforces a small but meaningful completion contract:

- `output_contract_builder.py` was aligned to the real run-scoped output layout under `data/runs/{run_id}/layer_X/`
- `pipeline.py` now checks for a minimum set of required artifacts after each completed layer
- `pipeline.py` now reads the layer's existing validation report and fails the run if that report did not pass
- `pipeline.py` now requires the manifest's `output_contract` to be current and fails clearly if the run needs to be rebuilt from Layer 0

This intentionally reuses the validation logic that already existed inside the layers instead of creating a second, more complex validation framework.

### What is intentionally still out of scope

This implementation does not try to enforce everything the design docs mention.

Still deferred:

- enforcing `minimum_expected_documents` from Layer 0 as a centralized runner threshold
- deep schema validation beyond what each layer's validation gate already checks
- full final-package validation beyond the active Layer 9 and Layer 10 artifacts

### Why this was the right first implementation

This closes the confusing failure mode where a layer could:

- finish without raising an exception
- write only partial artifacts
- write a failed validation report
- still be shown by the pipeline as complete

That problem is now addressed without adding a large new validation surface.

---

## 5. Downstream Data Flow and Artifact Ownership

### The current pattern

The active pipeline is not designed as a pure immediate-downstream chain where each layer only reads the previous one.

Instead, it behaves as a DAG of layer-scoped authoritative artifacts:

- Layer 1 produces raw extraction artifacts.
- Layer 2 turns those into canonical documents and source spans.
- Layer 3 turns canonical documents into stories and rankings.
- Layer 4 turns stories into verified claims and evidence mappings.
- Later layers often read the latest layer output plus selected earlier authoritative artifacts.

### Real examples from the active code

- Layer 6 reads Layer 5, Layer 4, Layer 3, and Layer 2.
- Layer 8 reads Layer 7 plus Layer 4 verified claims.
- Layer 9 reads Layer 8, Layer 7, Layer 4, and Layer 2.
- Layer 10 reads Layer 9, 8, 7, 5, 4, and 3.

See:

- [run_layer_6.py](../../pipelines/layer_6_research_packets/run_layer_6.py)
- [brief_loader.py](../../pipelines/layer_8_script_generation/brief_loader.py)
- [context_loader.py](../../pipelines/layer_9_verification_firewall/context_loader.py)
- [context_loader.py](../../pipelines/layer_10_memory_learning/context_loader.py)

### Why this happened

This is not just accidental drift. Several later layers need provenance-rich, lower-level truth:

- Layer 6 needs evidence spans and canonical documents to build source packs.
- Layer 8 needs verified claim text and source URLs, not only a planning brief.
- Layer 9 should verify against source spans and verified claims, not only the generated script.
- Layer 10 needs cross-layer context to build durable memory safely.

### What is authoritative today

Best mental model:

- Layer 2 is the authoritative evidence base for documents and source spans.
- Layer 3 is the authoritative story base.
- Layer 4 is the authoritative claim/evidence base.
- Layer 5 is the authoritative editorial decision point.
- Layer 7 is the authoritative script-writing brief.
- Layer 9 is the authoritative verification outcome.

### What this means for future work

The dataflow is valid in principle, but it creates repeated backward joins and makes the run harder to inspect in one place.

For a fuller map and recommendation, see [docs/reference/run_dataflow_and_run_state.md](../reference/run_dataflow_and_run_state.md).

---

## 6. ChatGPT Handoff Audit

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
5. Manifest-declared target or eligibility default only if no downstream selection exists yet

### Current handoff behavior

- Shared prompt blocks now come from `run_manifest.json` `resolved_config.chatgpt_handoff`.
- Format-specific instruction blocks are now resolved dynamically.
- Deep-dive runs now get deep-dive-specific instruction wording.
- The memory block now only uses published-video history.
- The exporter now requires completed Layer 3 inputs and will refuse partial runs that do not have `layer_3/ranked_stories.json`.

### Remaining limitation

The exporter is more dynamic than before, but some behavior is still code-defined.

Still code-defined today:

- format-specific instruction assembly
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

## 7. Memory Behavior

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

### Publish-memory workflow status

As of 2026-05-13, the core publication-state workflow is now implemented.

Now present:

- `publishing_memory.py mark-published` to update a prepared run into published memory
- `publishing_memory.py sync-channel` to sync the authenticated owner channel into local memory files
- `performance_memory.jsonl` ingestion from authenticated YouTube Analytics queries
- automatic rebuild of `learning_signals.jsonl`, `memory_index.json`, and `memory_snapshot.json` after publish-state changes

Completed in practice:

- first live OAuth authorization on the machine
- first authenticated owner-channel sync
- canonical publishing channel resolution to `UCp4tfcoFDQIFu7Cnodrqq_w`

Still pending in practice:

- first real published video to exercise the full path end-to-end

### Recommended model going forward

Keep both concepts:

1. Raw run memory
   - every prepared script/run can remain in raw memory files for audit
2. Published memory
   - only published videos should affect novelty, repetition avoidance, and handoff guidance

### Practical workflow now

Current workflow:

1. Run Layer 10 so prepared-run memory exists.
2. Publish the YouTube video.
3. Run `publishing_memory.py mark-published --run-id <run_id> --youtube-video-id <youtube_video_id>`.
4. Optionally run `publishing_memory.py sync-channel` before later runs to refresh channel state and analytics.

### Fresh-start cleanup applied

Because the authenticated publishing channel currently has zero published videos, the
exploratory editorial memory was reset to a clean baseline before the first real run.

Preserved:

- `memory/publishing_channel_state.json`
- `memory/published_video_inventory.jsonl`

Reset and rebuilt:

- run-derived JSONL memory files
- `memory/learning_signals.jsonl`
- `memory/memory_index.json`
- `memory/memory_snapshot.json`

This keeps the publishing/auth state real while preventing novelty and repetition
guidance from being polluted by exploratory draft history.

For a file-by-file ownership map of the `memory/` folder, see:

- `docs/reference/memory_file_map.md`

### Memory workflow parity versus design

The full design does not limit memory influence to Layer 5 only.

The design expectation is broader:

- Layer 0 uses memory policy and future-run guidance.
- Layer 1 can later use source priority and follow-up targets.
- Layer 3 can later use prior story recurrence and story families.
- Layer 5 uses novelty and prior coverage memory.
- Layer 6 can later use follow-up and evergreen memory.
- Layer 7 can later use prior hooks, title angles, and style memory.
- Layer 8 can later use blocked phrases and prior-risk memory.
- Layer 9 can later use rejected claim and risky-title memory.

Current implementation status:

- Implemented direct memory consumption in the active pipeline:
  - Layer 5 reads `video_memory.jsonl` and `followups.jsonl`
- Implemented planning/policy metadata only:
  - Layer 0 writes memory policy, windows, and paths into the manifest
- Implemented outside the main pipeline:
  - `chatgpt_export.py` reads `memory_snapshot.json`
- Not yet implemented as active direct memory consumers:
  - Layer 1
  - Layer 3
  - Layer 6
  - Layer 7
  - Layer 8
  - Layer 9

Conclusion:

The current system only partially follows the design's memory feedback loop. The first real consumer is Layer 5. The broader memory-driven workflow is still incomplete.

---

## 8. Legacy Folders Audit

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

## 9. Functional Gaps vs Design Docs

This section focuses on functionality, not folder structure.

### Layer 1

- Time windows are now enforced in the active Layer 1 path, but some sources still depend on post-fetch filtering instead of native server-side date constraints.
- YouTube orchestration now runs in the main path, but channel selection remains registry-driven and transcript availability is still source-dependent.

### Layer 2

- The design called for more explicit source-type parser modules.
- The current Layer 2 works, and transcript content can now enter through the active Layer 1 path, but transcript-specific normalization/parsing is still lighter than the design envisioned.

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

- Repetition checker now exists in Layer 9 against published-memory state.
- Contradiction/evidence-gap handling is mostly informational right now.

### Layer 10

- Performance ingest is built through the post-run publishing workflow.
- Publish-state updating and authenticated channel sync now exist.
- The practical remaining gap is the first real published video flowing through the full cycle.

### Priority view

Build next:

1. Feature-complete manifest authority for the remaining runtime consumers
2. Higher-parity story clustering / recurrence behavior from the design docs
3. Additional format branches (`evergreen`, `comparison`, `follow_up`)
4. Broader multi-provider support in the async runtime
5. Deeper memory consumers in Layers 7, 8, and 9 beyond the currently active checks

Build later:

- disabled format branches
- extra config-file extraction for purely internal constants
- structural parity items that do not unlock new behavior

---

## 10. Why LLM Logs Are Missing

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

That recommendation is now implemented for the active async path.

Now present:

- `llm/async_llm_runtime.py` as the shared async runtime wrapper
- manifest-backed model/profile resolution inside the runtime
- structured per-call logs written under `output/llm_logs/{run_id}/`
- active async Layers 4, 5, 7, 8, and 9 routed through that shared path

Remaining gap:

- legacy or standalone LLM utilities are not all migrated yet
- the active async runtime still assumes `provider='openai'`

---

## 11. Suggested Architecture Direction for Run State

### The question

Should the system move to one cumulative master file where each layer appends more data, instead of later layers tracing back to multiple earlier layer outputs?

### Recommendation

Do not replace the current per-layer outputs with one mutable master file as the primary source of truth.

Instead:

1. Keep per-layer artifacts as the authoritative outputs.
2. Add one compiled run-state artifact for convenience and inspection.

Suggested names:

- `data/runs/{run_id}/run_state.json`
- `data/runs/{run_id}/run_graph.json`

### Why a single mutable master file is a bad primary contract

This pipeline does not enrich one object linearly. It creates several different object families:

- documents
- spans
- stories
- claims
- editorial decisions
- sections
- sentences
- verification results

Forcing all of that into one ever-mutating primary blob would make:

- ownership unclear
- partial reruns risky
- provenance harder to audit
- bugs harder to isolate
- writes more expensive and conflict-prone

### Why a compiled run-state artifact is a good secondary contract

A compiled run-state artifact would still give the usability benefits the repo currently lacks:

- one place to inspect the full run
- less repeated joining for tooling and export
- easier debugging and handoff generation
- clearer lineage across documents, stories, claims, sections, and sentences

### Best implementation approach later

Start from Layer 2 onward, not Layer 1.

Reason:

- Layer 1 is raw and noisy extraction.
- Layer 2 is the first canonical, stable evidence layer.

The compiled artifact should be a registry of IDs and links, not one giant duplicated nested blob.

Good direction:

```json
{
  "run_id": "run_...",
  "documents": { "doc_id": {} },
  "spans": { "span_id": {} },
  "stories": { "story_id": {} },
  "claims": { "claim_id": {} },
  "video": {},
  "sections": { "section_id": {} },
  "sentences": { "sentence_id": {} },
  "verification": {},
  "artifacts": {
    "layer_2": {},
    "layer_3": {},
    "layer_4": {}
  }
}
```

### Important rule

The compiled run-state artifact should be derived and refreshed by orchestrators, not treated as the only writable truth for every submodule.

### What to keep authoritative even after adding run state

- Layer 2 `canonical_documents.jsonl` and `source_spans.jsonl`
- Layer 3 `story_clusters.json` and `ranked_stories.json`
- Layer 4 `verified_claims.jsonl` and `claim_evidence_map.jsonl`
- Layer 5 `selected_video_brief.json`
- Layer 7 `script_writer_brief.json`
- Layer 9 `final_publish_package.json` and `verification_report.json`

### Why this fits the current repo

The repo already has partial master-style checkpoints:

- `run_manifest.json`
- `research_packet.json`
- `script_writer_brief.json`
- `final_publish_package.json`

The missing piece is a unified run graph tying those checkpoints together.

---

## 12. Suggested Cleanup Order

### First

1. Finish config centralization around LLM calls and logging.
2. Wire time-window policy from Layer 0 into Layer 1 collectors.
3. Wire YouTube collection into the main Layer 1 orchestration path.
4. Add a publish-state updater for Layer 10 memory.
5. Document or prototype a compiled `run_state.json` / `run_graph.json` approach before changing downstream readers.

### Second

1. Update README so it reflects the real 0→10 pipeline.
2. Retire or archive legacy Layer 2/3/4 folders.
3. Remove or merge `config/scoring_config.yaml` if it remains unused.

### Third

1. Revisit disabled format branches when the editorial strategy actually needs them.
2. Move inline per-layer constants into config only where that improves operator control.
