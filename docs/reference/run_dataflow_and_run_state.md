# Run Dataflow and Run-State Recommendation

This document captures the current downstream read pattern of the active pipeline and the recommended future direction for a compiled run-state artifact.

## Short answer

The current pipeline is not a strict `Layer N -> Layer N+1` chain.

It behaves as a DAG of authoritative artifacts:

- later layers often read the immediate upstream output
- and also reach back to earlier layers for more authoritative evidence or provenance

This is valid for an evidence-heavy system, but it increases join complexity.

## Current downstream read pattern

### Layer 1

- Produces raw extraction artifacts
- Primarily consumed by Layer 2 only

Main output:

- `layer_1/raw_documents.jsonl`

### Layer 2

- Consumes Layer 1
- Produces canonical documents, source spans, and provenance
- Becomes the long-lived evidence base for many later layers

Main authoritative files:

- `layer_2/canonical_documents.jsonl`
- `layer_2/source_spans.jsonl`
- `layer_2/provenance_map.jsonl`

Later readers:

- Layer 3
- Layer 4
- Layer 6
- Layer 9

### Layer 3

- Consumes Layer 2
- Produces stories, rankings, entity/topic maps, timelines
- Becomes the long-lived story base

Main authoritative files:

- `layer_3/story_clusters.json`
- `layer_3/ranked_stories.json`
- `layer_3/story_entity_topic_map.json`
- `layer_3/story_timeline.json`

Later readers:

- Layer 4
- Layer 5
- Layer 6
- Layer 10

### Layer 4

- Consumes Layer 3 and Layer 2
- Produces verified claims and evidence mappings
- Becomes the long-lived claim/evidence base

Main authoritative files:

- `layer_4/verified_claims.jsonl`
- `layer_4/claim_evidence_map.jsonl`
- `layer_4/story_fact_sheets.json`
- `layer_4/evidence_gaps.json`

Later readers:

- Layer 5
- Layer 6
- Layer 8
- Layer 9
- Layer 10

### Layer 5

- Consumes Layer 3, Layer 4, and memory
- Produces the selected editorial brief

Main authoritative file:

- `layer_5/selected_video_brief.json`

Later readers:

- Layer 6
- Layer 10

### Layer 6

- Consumes Layer 5 and also reaches back to Layers 4, 3, and 2
- Produces the research packet and source pack

Main authoritative files:

- `layer_6/research_packet.json`
- `layer_6/source_pack.json`
- `layer_6/claim_section_map.json`
- `layer_6/packet_context_for_layer7.json`

Later readers:

- Layer 7

### Layer 7

- Consumes Layer 6
- Produces the full planning package for script generation

Main authoritative files:

- `layer_7/script_writer_brief.json`
- `layer_7/section_plan.json`
- `layer_7/title_thumbnail_plan.json`

Later readers:

- Layer 8
- Layer 9
- Layer 10

### Layer 8

- Consumes Layer 7 and also Layer 4 verified claims
- Produces the generated script and sentence maps

Main authoritative files:

- `layer_8/generated_script.json`
- `layer_8/sentence_claim_map.jsonl`
- `layer_8/sentence_source_map.jsonl`
- `layer_8/youtube_metadata.json`

Later readers:

- Layer 9
- Layer 10

### Layer 9

- Consumes Layer 8, Layer 7, Layer 4, and Layer 2
- Produces the final verification outcome

Main authoritative files:

- `layer_9/verification_report.json`
- `layer_9/final_publish_package.json`
- `layer_9/verified_script.md`

Later readers:

- Layer 10

## What this means

The current system does not build one object linearly. It creates several different object families:

- documents
- spans
- stories
- claims
- editorial decisions
- sections
- sentences
- verification results

That is why a single mutable primary master file is not a good fit.

## Recommendation

Do not replace per-layer outputs with one giant mutable master file.

Instead, add a compiled run-state artifact as a secondary convenience layer.

Suggested names:

- `run_state.json`
- `run_graph.json`

## What the compiled run-state artifact should do

- make the whole run inspectable in one place
- reduce repeated joins for export/debugging
- preserve clear object identity across layers
- keep authoritative per-layer outputs intact

## What it should not do

- it should not replace per-layer authoritative files
- it should not become the only writable data store
- it should not force every submodule to edit one shared blob

## Good shape

The run-state artifact should mostly be an ID registry plus resolved links:

```json
{
  "run_id": "run_...",
  "documents": {},
  "spans": {},
  "stories": {},
  "claims": {},
  "video": {},
  "sections": {},
  "sentences": {},
  "verification": {},
  "artifacts": {}
}
```

## Best adoption path

Start from Layer 2 onward.

Reason:

- Layer 1 is raw extraction and changes often
- Layer 2 is the first stable canonical layer

Good future rollout:

1. Add a derived run-state builder after Layer 2.
2. Extend it at the end of each orchestrator.
3. Keep existing per-layer files unchanged.
4. Switch helper tooling and exports to prefer the run-state artifact where that simplifies code.
5. Only switch core pipeline readers later, and only where provenance remains explicit.

## Related docs

- [System Audit — 2026-05-12](../audits/2026-05-12_system_audit.md)
- [Layer Output Map](layer_output_map.md)
- [System Completion Feature Map](../roadmaps/system_completion_feature_map.md)
