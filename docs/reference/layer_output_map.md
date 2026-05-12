# Layer Output Map

Use this file when you want to inspect the main downstream artifacts for a run quickly.

| Layer | Main output files | What to read first |
| --- | --- | --- |
| Layer 0 | `data/runs/{run_id}/run_manifest.json` | The full run contract |
| Layer 1 | `data/runs/{run_id}/layer_1/raw_documents.jsonl`, `extraction_manifest.json` | `extraction_manifest.json` |
| Layer 2 | `data/runs/{run_id}/layer_2/canonical_documents.jsonl`, `source_spans.jsonl`, `provenance_map.jsonl` | `canonical_documents.jsonl` |
| Layer 3 | `data/runs/{run_id}/layer_3/story_clusters.json`, `ranked_stories.json`, `story_timeline.json` | `ranked_stories.json` |
| Layer 4 | `data/runs/{run_id}/layer_4/verified_claims.jsonl`, `story_fact_sheets.json`, `evidence_gaps.json` | `story_fact_sheets.json` |
| Layer 5 | `data/runs/{run_id}/layer_5/selected_video_brief.json`, `editorial_candidates.json`, `format_routing_decisions.json` | `selected_video_brief.json` |
| Layer 6 | `data/runs/{run_id}/layer_6/research_packet.json`, `source_pack.json`, `claim_section_map.json`, `packet_context_for_layer7.json` | `research_packet.json` |
| Layer 7 | `data/runs/{run_id}/layer_7/script_writer_brief.json`, `video_plan.json`, `title_thumbnail_plan.json` | `script_writer_brief.json` |
| Layer 8 | `data/runs/{run_id}/layer_8/generated_script.json`, `script.md`, `youtube_metadata.json`, `section_scripts.json` | `generated_script.json` |
| Layer 9 | `data/runs/{run_id}/layer_9/verified_script.md`, `final_publish_package.json`, `verification_report.json` | `verification_report.json` |
| Layer 10 | `data/runs/{run_id}/layer_10/layer10_manifest.json`, `memory/memory_snapshot.json`, `memory/memory_index.json` | `layer10_manifest.json` |

## Short reading path by goal

If you want:

- Source collection summary: read Layer 1 `extraction_manifest.json`
- Final story ranking: read Layer 3 `ranked_stories.json`
- Evidence-backed facts: read Layer 4 `story_fact_sheets.json`
- Which video the system chose: read Layer 5 `selected_video_brief.json`
- What the script writer saw: read Layer 7 `script_writer_brief.json`
- Final generated script: read Layer 8 `script.md`
- What Layer 9 approved or flagged: read Layer 9 `verification_report.json`
- What got written to memory: read Layer 10 `layer10_manifest.json`

