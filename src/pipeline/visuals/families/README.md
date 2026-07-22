# Visual Family Catalog

This directory is the inspectable design catalog for the active visual
subsystem. Each scene-type directory contains three tested recipe examples.
The runtime allowlist remains `src.pipeline.visuals.recipes.RECIPE_REGISTRY`;
the examples here are reference inputs for the visual lab and renderer smoke
tests.

The scene architecture has four layers:

1. `background`: one episode-owned palette and atmosphere.
2. `content`: transparent/open graphics, or an intentionally opaque real media
   surface such as a photograph, video, browser page, document, or interface.
3. `annotation`: highlights, callouts, focus marks, and source credit.
4. `typography`: short hooks, chapter titles, and labels.

An H.264 scene clip cannot preserve alpha, so "transparent" means that a
recipe does not paint its own competing full-frame theme. Every recipe inherits
the episode background and palette. Real media surfaces remain opaque because
their pixels are the subject.

## Families

| Family | Scene types |
|---|---|
| `source_proof` | `source_article_scene`, `quote_or_claim_highlight_scene` |
| `real_media` | `context_image_scene`, `broll_video_scene` |
| `interface_source_motion` | `browser_walkthrough_scene`, `document_stack_scene` |
| `identity` | `logo_reveal_scene`, `story_transition_scene` |
| `editorial_motion` | `editorial_text_scene` |
| `explanatory_motion` | `simple_explainer_scene`, `interface_transform_scene` |

Legacy dashboard/card families are intentionally absent. They are not hidden
fallbacks and must not be reintroduced without a new reviewed recipe.

## Sequence Example

A 25-45 second sequence is a direction window, not a single long shot. For a
story about AI advice reducing accuracy, one sequence can contain:

1. A 5-second chapter opener.
2. A 9-second source-page establishment.
3. A 10-second confidence-versus-accuracy explanation.
4. A 10-second source-backed quote or creator punchline.

Those adjacent shots share one idea and continuity motif while retaining their
own authoritative voiceover-aligned scene slots.

The full gallery currently contains 33 examples: three recipes for each of the
11 active scene types. Generated gallery output belongs under
`output/labs/visual_family_gallery/`, not in this source directory.
