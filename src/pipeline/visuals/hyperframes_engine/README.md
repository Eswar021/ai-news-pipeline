# HyperFrames Rendering Engine

This is an optional renderer for the canonical visual scene contract. It does
not plan scenes, select media, or replace source ownership checks. The Python
`visuals.render` app generates an isolated composition per resolved scene and
invokes the pinned local HyperFrames CLI.

Supported production scene kinds:

- `source_article_scene`
- `context_image_scene`
- `broll_video_scene`
- `logo_reveal_scene`
- `editorial_text_scene`
- `simple_explainer_scene`
- `story_transition_scene`
- `quote_or_claim_highlight_scene`
- `data_counter_scene`
- `benchmark_delta_scene`
- `ecosystem_map_scene`
- `architecture_flow_scene`
- `process_zoom_scene`
- `browser_walkthrough_scene`
- `capability_matrix_scene`
- `document_stack_scene`
- `interface_transform_scene`

Named cross-renderer recipes include `source_proof_montage`,
`annotated_image_focus`, `annotated_video_focus`, `metric_countup`,
`metric_contrast`, `process_trace`, `interface_walkthrough`, and
`evidence_stack`. Recipe IDs refine a stable scene payload; they do not create a
second planning contract.

There is no cross-engine fallback. Selecting HyperFrames with an unsupported
scene kind fails before rendering that scene. Install dependencies once with:

```bash
npm install
```

Select it for an orchestration run with:

```bash
python3 -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode preview \
  --render-backend hyperframes \
  --from-module visual_render
```
