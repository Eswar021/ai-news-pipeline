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
