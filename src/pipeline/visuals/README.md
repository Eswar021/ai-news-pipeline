# Pipeline Visuals

`src.pipeline.visuals` is the motion-visual subsystem. It is parallel to
`apps/` and `voiceover/` because it produces media files, not just JSON.

The subsystem is intentionally split into small stages:

```text
planner -> media_discovery -> asset_resolver -> render -> assembly
```

The stages are intentionally separate:

- `planner` is the LLM-heavy stage. It converts the script, selected stories,
  source records, and optional voiceover timing into a renderable scene plan.
- `media_discovery` searches approved providers for planner-requested contextual
  images and b-roll, downloads only selected assets, prepares short video clips,
  and preserves attribution/license metadata.
- `asset_resolver` is the asset-building stage. It takes that plan and
  materializes screenshots, logo assets, discovered media, and render-ready
  scene records.
- `render` turns each resolved scene into an MP4 clip.
- `assembly` concatenates clips and attaches the voiceover.

Every production stage carries artifact provenance. The visual plan is bound
to one script and voiceover fingerprint; media discovery, asset resolution,
and rendering propagate that lineage. A mismatched or historical artifact is
rejected before expensive work instead of being selected by modification time.

If story-level LLM planning fails, do not let that silently become a generic
video. `visuals.planner.allow_deterministic_story_fallbacks` defaults to
`false`, so structural LLM/schema failures stop at planning. Set it to `true`
only when you intentionally want fallback visuals for debugging.

The notebook owns file orchestration. The modules receive JSON/dict inputs,
return JSON/dict outputs, and write only the media/package files that belong to
their stage.

## Current Flow

### 1. Planner

Entrypoint:

```python
from src.pipeline.visuals.planner import run
```

Purpose:

- read the video packet, script, optional voiceover package, and visual config
- create an episode-level direction
- plan renderable scenes per selected story
- consume canonical beat IDs, visual briefs, source keys, and aligned voice timing
- insert one moving story-title interstitial over each story's first transition beat
- stitch scenes deterministically without allowing the LLM to author raw seconds
- return `data.visual_scene_plan`

The planner uses LangChain structured output with Pydantic models. Durable
prompt text lives under:

```text
src/pipeline/visuals/planner/prompts/
```

The planner should not generate generic presentation-card outputs. The banned
old card language is enforced in code and prompts.

The planner output may include an `asset_manifest.requests` section, but those
are only asset requests. For `context_image_scene` and `broll_video_scene`, the
planner supplies search intent and visual constraints, never invented asset
URLs. The planner does not search, download, capture, resolve, or render media.

Script input can come from either:

- `input.script_generation`, the App 5 script-generation envelope.
- `input.script_text`, an explicit unstructured text fallback for isolated tests.

Production native and ChatGPT scripts both arrive through
`input.script_generation` and already share canonical sections and audiovisual
beats. The planner joins those beats to
`voiceover.audio_units[].aligned_beats` by ID, then sends only one story's
beats, records, source keys, visual briefs, and available asset hints to that
story's LLM call. Paragraph/entity inference is used only for an intentionally
unstructured `script_text` test input.

The planner should not treat beats as one-scene-per-beat instructions. Beats
are semantic timing anchors; one scene may cover adjacent beats when they form
one understandable visual idea. Scene payloads retain every covered `beat_id`
and exact timing for internal reveals. A beat longer than the render cap is
split into balanced visual slices without losing its identity. Title
interstitials are protected from compaction and cannot merge into neighboring
sections.

### 2. Media Discovery

Entrypoint:

```python
from src.pipeline.visuals.media_discovery import run
```

Purpose:

- search only for scenes that request contextual images or b-roll
- rank candidates using query/title/tag fit, aspect ratio, resolution, clip
  duration, provider rank, and license metadata
- download the selected image or prepare only the short muted video clip needed
  by the scene
- preserve candidate metadata and attribution in `data.visual_media_package`
- explicitly convert an unresolved media request to the configured fallback
  scene instead of hiding a missing file

Wikimedia Commons images are enabled by default and require no API key. Pexels
and Pixabay adapters are available but disabled until their free API keys are
put in `PEXELS_API_KEY` or `PIXABAY_API_KEY` and enabled in workbench config.
Enable `broll_video_scene` in `scene_policy.allowed_render_kinds` at the same
time. Do not put API keys in YAML. Wikimedia video support exists for targeted
experiments, but is off by default because search relevance and large remote
WebM delivery are not consistent enough for routine full runs.

### 3. Asset Resolver

Entrypoint:

```python
from src.pipeline.visuals.asset_resolver import run
```

Purpose:

- resolve screenshot assets for source-backed scenes
- resolve logo assets for logo reveal scenes
- validate and attach downloaded contextual image/b-roll assets
- pass through graphic-only scenes that do not require assets
- return `data.visual_asset_manifest`

Current asset mapping:

```text
source_article_scene             -> source_screenshot
quote_or_claim_highlight_scene   -> source_screenshot
context_image_scene              -> context_image
broll_video_scene                -> broll_video
logo_reveal_scene                -> logo_asset
kinetic_type_scene               -> none
bullet_build_scene               -> none
entity_compare_scene             -> none
recap_sequence_scene             -> none
data_counter_scene               -> none
trend_line_scene                 -> none
bar_chart_scene                  -> none
bar_race_scene                   -> none
ranked_list_scene                -> none
benchmark_delta_scene            -> none
ecosystem_map_scene              -> none
architecture_flow_scene          -> none
process_zoom_scene               -> none
browser_walkthrough_scene        -> none
decision_tree_scene              -> none
capability_matrix_scene          -> none
timeline_zoom_scene              -> none
document_stack_scene             -> none
signal_radar_scene               -> none
interface_transform_scene        -> none
transition_stinger_scene         -> none
```

If a new scene type is added, update the planner contracts, asset resolver
classification, Remotion render types, and workbench config together.

### 4. Render

Entrypoint:

```python
from src.pipeline.visuals.render import run
```

Purpose:

- validate scene durations before rendering
- build the Remotion project once per render run
- render independent MP4 scene clips with bounded parallel workers
- cap Remotion frame concurrency inside each scene to avoid CPU/RAM overload
- retry failed or missing scene outputs serially and preserve attempt logs
- return `data.visual_render_package`

The Remotion source lives under:

```text
src/pipeline/visuals/remotion_engine/
```

Run `npm install` there on a fresh machine before rendering.

Render concurrency is config-driven:

```text
worker_count          scene clips rendered at the same time
frame_concurrency     Remotion browser tabs used inside each scene render
max_render_attempts   bounded attempts per scene; retries run serially
```

Do not start two full render cells at the same time. One render run already
uses multiple scene workers and browser tabs; overlapping runs compete for the
same CPU, memory, and encoders and can be slower than one bounded run.

The production profile keeps 2K resolution and CRF-based quality while using
the `veryfast` x264 preset. This favors shorter local render time and somewhat
larger clips instead of reducing resolution.

### 5. Assembly

Entrypoint:

```python
from src.pipeline.visuals.assembly import run
```

Purpose:

- verify script, voiceover, visual-plan, and render fingerprints
- probe each rendered clip and the WAV before invoking ffmpeg
- require planned scene IDs/order and real visual duration to match the audio
- concatenate rendered scene clips
- attach the selected voiceover WAV
- verify that the final MP4 contains both video and audio streams
- write the final review MP4
- return `data.final_video_package`

Assembly currently uses rendered scene clips plus ffmpeg. A later milestone may
move final assembly into one full Remotion composition for better transitions,
captions, and sync control.

## Scene Types

Current renderable scene types:

- `source_article_scene`: show a real article/source screenshot with a focused
  overlay.
- `quote_or_claim_highlight_scene`: show a source screenshot plus a claim or
  caution callout.
- `context_image_scene`: show a real contextual photograph full-bleed with
  restrained cinematic motion and optional short overlay text.
- `broll_video_scene`: show a muted representative real-world clip while the
  narration remains the authoritative audio.
- `logo_reveal_scene`: show one or more company/product/model logos.
- `kinetic_type_scene`: show short high-impact phrases or transitions.
- `bullet_build_scene`: reveal multiple narration points one by one.
- `entity_compare_scene`: compare two or more entities, products, or models.
- `recap_sequence_scene`: close or summarize with a sequence of short items.
- `data_counter_scene`: animate concrete metrics, dates, speedups, costs,
  valuations, or adoption numbers.
- `trend_line_scene`: show momentum, pressure, growth, decline, or competition
  as a stylized directional chart.
- `bar_chart_scene`: compare concrete values or grounded relative signals with
  bold horizontal bars.
- `bar_race_scene`: show competitive movement, adoption momentum, or before/after
  rank shifts with animated bars.
- `ranked_list_scene`: show top-three/top-five priorities, implications, or
  takeaways with large rank numbers and compact labels.
- `benchmark_delta_scene`: visualize before/after gains, cost shifts, speedups,
  latency changes, or benchmark deltas.
- `ecosystem_map_scene`: map relationships among companies, products,
  platforms, developers, users, and model providers.
- `architecture_flow_scene`: explain SDK/API/model/app/user flows, agent
  workflows, integrations, training, or deployment pipelines.
- `process_zoom_scene`: zoom into one critical step of a workflow while keeping
  surrounding steps visible as context.
- `browser_walkthrough_scene`: simulate a guided browse through a source,
  product page, or workflow surface without relying on a static screenshot.
- `decision_tree_scene`: show branching choices for agent routing, model
  selection, safety gates, product strategy, or workflow decisions.
- `capability_matrix_scene`: compare model, product, or platform tradeoffs
  across a few meaningful dimensions such as speed, cost, context, and tooling.
- `timeline_zoom_scene`: show a short event sequence and zoom attention into
  the turning point without returning to generic timeline cards.
- `document_stack_scene`: show papers, release notes, docs, GitHub issues,
  reports, or articles stacking as evidence.
- `signal_radar_scene`: show trend/company/model signals as radar blips for
  "watch this" or emerging-signal narration.
- `interface_transform_scene`: show before/after UI or workflow transformation,
  especially when the story moves from chat to tools or manual to agentic work.
- `transition_stinger_scene`: create a short motion bumper between stories or
  dense visual sections without turning it into a title card.

Text-like scene types should support the video, not dominate it. Use
`kinetic_type_scene`, `bullet_build_scene`, and `recap_sequence_scene` for
punchlines, transitions, and short summaries. Prefer source, logo, data,
trend, chart, ranking, delta, map, flow, process-zoom, browser walkthrough,
decision-tree, matrix, document-stack, radar, interface-transform, contextual
image, or b-roll visuals when the narration gives enough structure.

Scene payloads may include:

```json
{
  "beats": [
    {
      "unit_order": 12,
      "beat_id": "section_02_story_example_beat_03",
      "beat_type": "explanation",
      "start_seconds": 51.93,
      "end_seconds": 54.97,
      "relative_start_seconds": 0,
      "relative_end_seconds": 3.04,
      "text": "Picture a translator sitting on top of a service you already have.",
      "visual_action": "advance_diagram_step",
      "emphasis_words": ["translator", "service"]
    }
  ]
}
```

Renderers can use these beats to reveal points, diagram steps, captions, or
highlights inside one coherent scene instead of cutting to a new visual for
every small voiceover chunk.

Several graphic scenes accept optional kicker text through `kicker_text` or an
existing label field such as `emphasis_label`, `leader_label`, or
`winner_label`. Kicker text is hidden by default so the lower-third area stays
clear for captions. To render it, pass `show_kicker: true` and optionally
`kicker_position: "top_right"` or `kicker_position: "bottom"`.

Do not add back `title_card`, `timeline_card`, `entity_card`, `recap_card`, or
`fallback_card` as primary visual types. If a new type feels card-like, rename
and redesign it around a real motion purpose.

## Config

Workbench defaults live in:

```text
src/pipeline/config/workbench.yaml
```

Relevant config sections:

- `visuals.planner`: LLM provider/model, scene policy, visual capabilities.
- `visuals.media_discovery`: provider enablement, environment-key names,
  candidate/download limits, minimum quality, video clipping, and explicit
  fallback behavior.
- `visuals.asset_resolver`: browser, screenshot, logo, and output settings.
- `visuals.render`: Remotion render settings, quality preset, encoder options,
  worker count, and per-scene caps.
- `visuals.assembly`: final-video mux/assembly settings.

When `visuals.render.quality_preset` is `1080p`, `2k`, or `4k`, the preset is
authoritative for render dimensions and baseline encoder quality. Use
`quality_preset: custom` when you want manual `width` and `height` values.

The modules should receive resolved config through their JSON input envelopes.
They should not read `workbench.yaml` directly.

`visuals.render.worker_count` controls how many scene clips are rendered in
parallel. Increase it to speed up section 8 when the machine has enough CPU/RAM;
decrease it if Remotion, ffmpeg, or the browser becomes unstable. The default
workbench setting is intentionally bounded rather than unlimited.

Logo scenes resolve assets in this order:

- local logo override from `visuals.asset_resolver.logos.local_logo_dir`
- Simple Icons aliases for common brands/products
- generated text-logo fallback

The fallback is not an official brand logo. Add local overrides for brands that
must look exact or when Simple Icons does not contain the right mark.

## Notebook Usage

Use:

```text
notebooks/production/visual_production.ipynb
```

Visual sections:

- `6. Plan Motion Visual Scenes`
- `7. Discover Media + Resolve Visual Assets`
- `8. Render Visual Scene Clips`
- `9. Assemble Final Video With Voiceover`

Optional manual ChatGPT visual planning can replace section 6:

- export a `visual_scene_plan` handoff with `handoffs.chatgpt_exporter`
- paste the response into a text file
- parse it with `handoffs.chatgpt_visual_plan_parser`
- continue from asset resolution using the parsed result

If section 7 fails with unsupported render kinds, the planner and resolver are
out of sync. Add the scene type to the resolver classification and render
contracts instead of removing the scene from the plan.

For renderer and scene-module development, use:

```text
notebooks/labs/visual_assets_lab.ipynb
```

This lab renders visual scene modules from small JSON payloads without running
the whole pipeline. It writes clips, specs, and review indexes under
`output/labs/visual_assets/{LAB_RUN_ID}/`. Use it to test a scene kind with several
payload variants before allowing the planner to produce that kind in real runs.

The lab has three useful groups:

- no-asset motion graphics, such as kinetic type, data counters, diagrams, and
  transition stingers
- targeted variants for data/trend/stinger behavior
- asset-backed examples for source screenshots, quote highlights, and logo
  reveals

Prefer reliable local fixtures in the lab for source screenshot QA. Production
still uses real selected-story URLs, but local fixtures make renderer layout
issues easier to distinguish from website-capture issues.

## Visual Families

As the subsystem grows, keep implementation grouped by visual family:

- `text_motion`: kinetic type, bullet build, recap, captions, and stingers.
- `data_viz`: counters, trends, bars, rankings, costs, speedups, benchmarks,
  dates, and adoption metrics.
- `diagram_motion`: architecture flows, ecosystem maps, decision trees,
  process zooms, and market maps.
- `source_media`: source screenshots, quote/claim highlights, and browser
  walkthroughs.
- `context_media`: discovered photographs, representative b-roll, and later
  generated illustrations when no real asset can communicate the idea.
- `brand_media`: logo reveals, multi-logo stacks, and entity identity moments.

The planner should not default to text scenes. Use text scenes for punchlines
and transitions; use source, logo, data, and diagram scenes whenever they make
the narration easier to understand.

## Development Checklist

When changing visuals:

- read this README and `docs/current_system_architecture.md`
- inspect the actual planner, resolver, render, and Remotion code before edits
- keep visual behavior config-driven
- keep prompt instructions in versioned prompt files
- update contracts whenever a payload shape changes
- update `workbench.yaml` when a new visual capability is added
- run Python compile checks for `src/pipeline/visuals`
- run Remotion typecheck after React/TypeScript changes
- smoke render at least one scene for any new render kind
- retain source, creator, license, and attribution metadata for remote media
