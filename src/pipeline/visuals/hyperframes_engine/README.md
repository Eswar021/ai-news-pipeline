# HyperFrames Rendering Engine

This is the recipe compiler used by the daily production profile for the
canonical visual scene contract. It does
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

Every production scene requires a named recipe. The current set includes
`editorial_hook`, `chapter_opener`, `source_proof_scan`,
`layered_evidence_reveal`, `annotated_image_focus`, `annotated_video_focus`,
`identity_reveal`, `mechanism_steps`, `metric_countup`, `metric_contrast`,
`process_trace`, `process_detail_zoom`, `interface_walkthrough`,
`evidence_stack`, `source_proof_montage`, and `interface_before_after`.
`render_kind` remains the broad media family; `recipe_id` chooses the tested
composition and motion behavior.

There is no cross-engine fallback. Selecting HyperFrames with an unsupported
scene kind fails before rendering that scene. Install dependencies once with:

```bash
npm install
```

The daily profile selects it automatically. Override the renderer explicitly
only for an A/B or historical plan:

```bash
python3 -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode preview \
  --render-backend remotion \
  --from-module visual_render
```
