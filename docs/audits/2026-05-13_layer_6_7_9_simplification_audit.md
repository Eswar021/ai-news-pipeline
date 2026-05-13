# 2026-05-13 Layer 6 / Layer 7 / Layer 9 Simplification Audit

## Scope

This audit was done after the Layer 8 narration-contract cleanup, prompt externalization rollout, and Layer 9 revision-package refactor.

It answers one narrower question:

- what should stay
- what should be merged
- what should be removed later
- what should be deferred until we observe more live runs

## Executive Summary

### Keep

- Layer 6 `research_packet.json` as the main research handoff
- Layer 6 `source_pack.json` because it is still the cleanest reviewer-facing source bundle
- Layer 7 `script_writer_brief.json` as the single authoritative Layer 8 input
- Layer 9 `verification_report.json`, `sentence_verification_results.jsonl`, and `revision_package.json`

### Merge or shrink next

- Layer 7 planning artifacts are still broader than the cleaned Layer 8 contract needs
- Layer 9 still has too many internal micro-check modules for the amount of durable output it now keeps

### Remove later if live runs confirm they add no value

- extra Layer 7 planning outputs that are derivable from `script_writer_brief.json`
- residual Layer 9 intermediate patch/check decomposition that now only feeds the lean report set

### Defer

- any deeper Layer 6 packet shrink until we have a few more successful roundup and deep-dive runs on the new Layer 4/5/8/9 contracts

---

## Layer 6

### Keep

- `research_packet.json`
  This is still the clearest compact evidence packet for the selected video.
- `source_pack.json`
  This remains useful for review and for downstream verification because it gives one human-readable source bundle instead of forcing every consumer to rehydrate claims one by one.
- `packet_context_for_layer7.json`
  This is still the effective normalized handoff into Layer 7.

### Merge later

- `claim_section_map.json`
  This may eventually be derivable from `research_packet.json` plus `packet_context_for_layer7.json`.

### Remove later

- No immediate removal is recommended from Layer 6 yet.

### Decision

Keep Layer 6 mostly stable for now. The recent embedded-provenance refactor already simplified the most important part: Layer 6 no longer needs a separate claim-evidence-map artifact from Layer 4.

---

## Layer 7

### Keep

- `script_writer_brief.json`
  This is the strongest Layer 7 artifact and should remain the sole authoritative Layer 8 input.
- `title_thumbnail_plan.json`
  This is still needed by Layer 8 metadata generation and Layer 9 metadata checks.

### Merge later

- `hook_plan.json`, `visual_plan.json`, `transition_plan.json`, and some pacing guidance are increasingly implementation details once `script_writer_brief.json` is complete.
- Much of the section-level planning logic is already folded into `script_writer_brief.json`; some separate durable files likely remain only for inspection/debugging.

### Remove later

- Any Layer 7 durable artifact that is not directly consumed by Layer 8, Layer 9, or human review after a few observed runs should be a candidate for removal.

### Decision

Layer 7 is not the immediate correctness problem anymore, but it is still broader than necessary. The next simplification pass should make `script_writer_brief.json` even more clearly authoritative and demote more of the other planning files to optional diagnostics.

---

## Layer 9 Residuals

### Keep

- `verification_report.json`
- `sentence_verification_results.jsonl`
- `revision_package.json`
- `verified_script.md` when approved
- `verified_youtube_metadata.json`
- `final_publish_package.json`

These are now the right durable outputs for the verification gate.

### Merge later

- `correction_patch_generator.py` and `revision_package_builder.py`
  They are still conceptually separate, but they now feed the same durable revision outcome and may eventually become one builder.
- some narrow report/check helpers
  The internal step split is still helpful today, but a few can likely merge once we observe stable behavior on more runs.

### Remove later

- old Layer 9 output families such as `unsupported_sentences.jsonl`, `overclaim_report.json`, `metadata_safety_report.json`, `source_attribution_report.json`, and `correction_patch.json`
  These are already removed from the active durable output tree and should stay removed.

### Decision

The important simplification is already done: `requires_revision` is no longer a fake file-missing failure mode. The next Layer 9 cleanup should focus on reducing internal helper sprawl only after we confirm the new `revisable` workflow across more real runs.

---

## Keep / Merge / Remove / Defer Matrix

| Area | Keep | Merge | Remove later | Defer |
| --- | --- | --- | --- | --- |
| Layer 6 | `research_packet.json`, `source_pack.json`, `packet_context_for_layer7.json` | `claim_section_map.json` into stronger packet context later | none immediately | packet shrink until more live runs |
| Layer 7 | `script_writer_brief.json`, `title_thumbnail_plan.json` | hook/visual/transition/pacing artifacts into brief-led model | extra planning artifacts not consumed downstream | exact removals until more runs |
| Layer 9 | lean durable output set | patch + revision builders, some internal check modules | old report sprawl stays removed | deeper helper merges until behavior stabilizes |

---

## Recommendation

The next simplification order should be:

1. observe a few real runs on the new Layer 8 and Layer 9 contract
2. shrink Layer 7 durable artifacts around `script_writer_brief.json`
3. then revisit whether Layer 6 still needs every current file
4. only after that, merge residual Layer 9 internals
