# Pipeline Visuals

`src.pipeline.visuals` turns the canonical script and authoritative voiceover
timeline into a reviewed video. Planning and media production are separate so
an LLM decides meaning while deterministic modules own identity, timing,
rendering, and provenance.

## Runtime Flow

```text
visual_research
  -> asset_catalog
  -> visual_planner
  -> media_discovery
  -> asset_resolver
  -> visual_render
  -> video_assembly
  -> visual_review
  -> publish_handoff (final mode only)
```

- `research` makes one story-local structured LLM call per selected story. It
  reads the complete story records and canonical script section, then names
  concrete asset needs such as an official interface, source figure, person,
  product image, demo moment, logo, or code-generated explanation.
- `asset_catalog` inspects selected source pages and verified identities. It
  converts research needs into story-owned asset briefs and binds structurally
  compatible candidates without deciding whether an image is semantically
  good merely from keywords.
- `planner` receives voiceover-aligned beats, complete story context, visual
  research, and exact catalog assets. It directs the episode, plans bookends,
  and plans each story using only renderable recipes.
- `media_discovery` materializes exact catalog choices first. Open-web image
  and B-roll search remains an explicit optional policy.
- `asset_resolver` captures article regions, resolves logos, and prepares
  selected images and video moments.
- `render` creates short independent clips. HyperFrames is the production
  recipe compiler; Remotion remains an explicit comparison backend.
- `assembly` joins clips and attaches the authoritative voiceover.
- `review` creates contact sheets and a story-grouped report for human QA.

Every stage keeps the script, voiceover, research, plan, asset, render, and
assembly fingerprints needed to reject mismatched artifacts before expensive
work.

## Active Visual Families

Only these scene contracts are active:

| Family | Active scene types |
|---|---|
| Source proof | `source_article_scene`, `quote_or_claim_highlight_scene` |
| Real media | `context_image_scene`, `broll_video_scene` |
| Interface/source motion | `browser_walkthrough_scene`, `document_stack_scene` |
| Identity | `logo_reveal_scene`, `story_transition_scene` |
| Editorial motion | `editorial_text_scene` |
| Explanatory motion | `simple_explainer_scene`, `interface_transform_scene` |

The source-controlled design catalog is under:

```text
src/pipeline/visuals/families/
```

Each scene type has three validated recipe examples. The gallery app renders
all examples through the same production contract and writes a review contact
sheet under `output/labs/visual_family_gallery/`.

Legacy dashboard, chart-card, matrix, radar, generic flow-card, and slide-deck
families were removed. They are not hidden planner fallbacks. A new visual type
must first receive a reviewed recipe, payload contract, renderer implementation,
gallery examples, and actual frame QA before it can enter the planner menu.

## Palette And Layer Contract

Every active recipe uses four conceptual layers:

1. `background`: one episode-owned palette and atmosphere.
2. `content`: open graphics or intentionally opaque real media.
3. `annotation`: highlights, callouts, focus marks, and source credit.
4. `typography`: short hooks, chapter titles, and labels.

H.264 MP4 does not preserve useful alpha for this pipeline. Here,
"transparent" means a recipe does not paint a competing theme. Generated
graphics inherit the episode palette; photographs, video, browser pages,
documents, and interfaces remain opaque because their pixels are the subject.

The default `editorial_signal` palette uses warm paper, near-black ink, a
restrained burnt-orange accent, large editorial serif headlines, and condensed
sans labels. Decorative pills, dark dashboards, floating metric cards, and
tiny captions are prohibited.

## Visual Sequences

The planner still emits one exact scene slot per voiceover-aligned script unit,
but it now directs adjacent shots as 25-45 second sequences. A sequence is not
one long visual. It is a coherent mini-story containing two to four short shots
that establish, develop, and pay off one idea.

Example for the AI-advice story:

```text
Sequence: confidence rises while accuracy falls (about 34 seconds)

shot 1, 5 seconds
  clean story opener: "Confidence Up, Accuracy Down"

shot 2, 9 seconds
  real source page establishing the study and publisher

shot 3, 10 seconds
  concise before/after contrast: accuracy 27 -> 9, confidence 30 -> 76

shot 4, 10 seconds
  source-backed quote or short creator punchline
```

The shots share a continuity motif, palette, and subject. Exact timestamps
still come from voiceover alignment; the LLM never authors raw seconds.

## Asset-First Research

Final planning no longer starts from a blind list of generic scene kinds. For
each story, the research pass answers:

- What must the viewer see to understand this narration?
- Which selected record might contain it?
- Is the best material a source page, figure, official image, interface, demo,
  identity, contextual photo/video, or code-generated explanation?
- What exact action or detail must be visible?
- What should be avoided so the visual does not misrepresent the beat?

Research does not select URLs or invent asset IDs. Cataloging and resolution
perform those deterministic ownership steps. The final planner sees the
research brief and the concrete assets actually available, then chooses the
shots.

The default profile remains `trusted_only`: selected source pages,
source-owned media, and verified identities are available without an extra
vision charge. Wikimedia, Pexels, Pixabay, and paid visual verification remain
disabled until the trusted foundation passes repeated human review.

## Planning Contract

Native planning uses:

- one episode-director call for global pacing and visual language
- one bookend call for intro and closing
- one story-planner call per selected story
- at most one bounded story-editor pass when a named issue requires it

Production keeps the fast episode director and bookend planner on GPT-4o-mini.
Story-local planning and the bounded visual editor use DeepSeek V4 Pro with
thinking enabled and `reasoning_effort: max`. Those DeepSeek routes use JSON
mode with the active dynamic Pydantic schema included in each story prompt;
development overrides them with GPT-4o-mini. The configured OpenAI fallback is
used only for an explicit provider content-filter rejection.

Each story call receives only that story's complete records, canonical script
beats, voiceover alignment, visual research, and story-owned catalog assets.
The provider schema exposes only active render kinds and exact recipe payloads.
Code validates Pydantic shape, stable IDs, source/asset ownership, timeline
coverage, renderability, and bounded-loop behavior. It does not use keyword or
numeric heuristics to decide whether a visual is creatively good.

Intro and closing scenes have no story owner, so their bounded bookend planner
may choose from the selected episode's catalog. Exact catalog ownership remains
recorded, and logo scenes keep the declared entity rather than inheriting an
unrelated asset title. When one exact identity match exists, normalization may
rebind to that logo deterministically. Story transitions may carry an optional
story-owned logo, image, or video background; validation follows that
background render kind.

One `story_transition_scene` is inserted at the beginning of every story while
narration continues. Bookends and transitions use authored display copy; code
does not slice arbitrary narration words into on-screen text.

## Render Contract

Every scene must name a `recipe_id` registered in
`src.pipeline.visuals.recipes.RECIPE_REGISTRY`. `render_kind` selects the broad
contract and `recipe_id` selects the tested composition.

HyperFrames compositions are generated in isolated temporary projects from:

```text
src/pipeline/visuals/hyperframes_engine/
```

The renderer uses a shared episode palette, frozen local assets, deterministic
seek-safe animation, bounded scene concurrency, persistent preview caching, and
video-only scene validation. There is no cross-engine semantic fallback.

Preview and final rendering are deliberately separate:

```bash
python3 -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode preview

python3 -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode final \
  --from-module visual_render
```

Focused renderer iteration can select one scene or story without rerunning
research and planning:

```bash
python3 -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode preview \
  --from-module visual_render \
  --stop-after visual_render \
  --scene-id scene_003
```

## QA

Visual QA must inspect actual frames or clips, not only summaries. The current
foundation is exercised by:

- all 33 active recipe variants under
  `output/labs/visual_family_gallery/active_33/`
- the July 20 intro plus AI-advice and probabilistic-computer benchmark under
  `output/labs/visual_sequence_benchmark_july20/`
- the committed deterministic fixture under
  `tests/fixtures/media_roundup_reference/`

Relevant checks:

```bash
python3 -B -m compileall src/pipeline/visuals
python3 -m pytest -q
cd src/pipeline/visuals/remotion_engine && npm run typecheck
```

`hyperframes_engine` is a render template rather than a standalone composition,
so HyperFrames validation occurs on the isolated projects produced by the
gallery and renderer smoke runs.
