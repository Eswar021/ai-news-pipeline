# HyperFrames Rendering Engine

This directory is the production recipe compiler for the canonical visual scene
contract. It does not plan scenes, select media, or change source ownership.
`visuals.render` creates an isolated HyperFrames project for each resolved scene
and invokes the pinned local CLI.

Supported scene kinds:

- `source_article_scene`
- `quote_or_claim_highlight_scene`
- `context_image_scene`
- `broll_video_scene`
- `browser_walkthrough_scene`
- `document_stack_scene`
- `logo_reveal_scene`
- `story_transition_scene`
- `editorial_text_scene`
- `simple_explainer_scene`
- `interface_transform_scene`

Every scene requires a recipe from
`src.pipeline.visuals.recipes.RECIPE_REGISTRY`. The HTML composition uses one
shared palette and four layers: background, content, annotation, and
typography. Real media stays opaque; generated overlays inherit the episode
palette rather than painting a separate dark card or dashboard.

There is no cross-engine fallback. An unsupported kind, missing recipe, invalid
payload, or overlong scene fails before rendering.

Install the pinned compiler dependencies:

```bash
npm install
```

This directory contains `index.template.html`, not a standalone `index.html`.
Run `hyperframes check` against a generated gallery/render project; the normal
renderer does this when `hyperframes_strict=true`.

Before changing render behavior, check the pinned CLI:

```bash
npx hyperframes@latest upgrade --project . --check
```

The active visual-family gallery and focused sequence benchmark are documented
in `../README.md`.
