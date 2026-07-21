# Pipeline Visuals

`src.pipeline.visuals` is the motion-visual subsystem. It is parallel to
`content/` and `voiceover/` because it produces media files, not just JSON.

The subsystem is intentionally split into small stages:

```text
asset_catalog -> planner -> media_discovery -> asset_resolver -> render -> assembly -> review
```

The stages are intentionally separate:

- `asset_catalog` creates trusted, story-owned asset IDs from selected source
  pages, source-owned hero images, and resolvable identities before planning.
- `planner` is the LLM-heavy stage. It converts the script, selected stories,
  trusted assets, and voiceover timing into a renderable scene plan.
- `media_discovery` resolves exact catalog media IDs first. Optional external
  image/B-roll research and semantic verification are separate, explicitly
  enabled policies rather than the default path.
- `asset_resolver` is the asset-building stage. It takes that plan and
  materializes screenshots, logo assets, discovered media, and render-ready
  scene records.
- `render` turns each resolved scene into an MP4 clip.
- `assembly` concatenates clips and attaches the voiceover.
- `review` samples the assembled video into a contact sheet and a
  scene-by-scene, story-grouped report for human visual inspection and publish
  review.

Every production stage carries artifact provenance. The visual plan is bound
to one script, voiceover, and asset-catalog fingerprint; media discovery, asset
resolution, rendering, assembly, and review propagate that lineage. A
mismatched or historical artifact is rejected before expensive work instead of
being selected by modification time.

If story-level LLM planning fails, do not let that silently become a generic
video. `visuals.planner.allow_deterministic_story_fallbacks` defaults to
`false`, so structural LLM/schema failures leave that story unresolved and stop
at planning without creating substitute scenes. Set it to `true` only when you
intentionally want fallback visuals for debugging.

`scene_policy.allowed_render_kinds` is the operational capability authority.
The authoring catalog may define additional future or disabled capabilities,
but neither the native LLM planner nor the ChatGPT handoff may advertise them.

The default production profile uses the `editorial_minimal` style and a
recipe-backed planner vocabulary:

```text
source_article_scene
context_image_scene
broll_video_scene
logo_reveal_scene
editorial_text_scene
simple_explainer_scene
story_transition_scene  # inserted by the system, not the story LLM
quote_or_claim_highlight_scene
data_counter_scene
benchmark_delta_scene
architecture_flow_scene
process_zoom_scene
browser_walkthrough_scene
document_stack_scene
interface_transform_scene
```

Every advertised kind must expose at least one named recipe that supports the
configured production backend. The LLM selects that exact `payload.recipe_id`;
it does not ask the renderer to improvise a design from a broad scene type. The
legacy charts, matrices, maps, and other specialist components remain available
to explicit profiles and historical plans, but they are not shown to the daily
planner by default.

The visuals stage router or interactive notebook owns file orchestration. The
modules receive JSON/dict inputs, return JSON/dict outputs, and write only the
media/package files that belong to their stage.

## Current Flow

### 1. Trusted Asset Catalog

Entrypoint:

```python
from src.pipeline.visuals.asset_catalog import run
```

Purpose:

- read the canonical script and selected video packet
- convert beat-level `visual_brief` values into story-owned asset requests
- register every selected source record as a stable `source_page` asset
- bind source-page screenshot targets to exact canonical beat support truths
- preflight source pages with the same browser capture path used by the asset
  resolver, so anti-bot, access-denied, or otherwise uncapturable pages are
  marked unavailable before the planner can select them
- fetch page metadata and inspect OpenGraph/hero plus bounded in-article image
  and direct source-video candidates, including lazy-loaded and `srcset` image
  sources
- retain only the configured number of structurally valid source-owned images
  under byte, dimension, and aspect-ratio limits; remove exact and near-visual
  duplicates while preserving alt text, image role, order, provenance,
  dimensions, and content hash
- retain bounded direct source-owned video files when the selected publisher
  exposes a supported MP4/WebM/MOV asset, then verify its stream with ffprobe
- preserve source-link text, nearby page context, provider metadata, and
  bounded provider chapter moments for selected-source YouTube/Vimeo/X videos
- register resolvable local/Simple Icons identities without pretending a
  favicon or text treatment is an official logo
- treat exact logo identities requested by canonical script visual briefs as
  additional resolution candidates, while still accepting them only when the
  configured resolver can verify the identity
- return `data.visual_asset_catalog` with stable asset IDs, story ownership,
  source provenance, availability, content hashes, and unresolved requests

The default catalog mode is `trusted_only`. It does not search the open web and
does not call an LLM or vision model. A selected source page is a real visual
anchor even when the publisher exposes no usable hero image or direct video.
Unresolved photo or B-roll briefs remain visible; this stage never substitutes
an unrelated asset to make the run appear complete.

Beat briefs expose structurally eligible `candidate_asset_ids`, not semantic
matches. Story ownership, source-record ownership, and renderer compatibility
are safe code checks; whether a candidate actually depicts the active sentence
is a planner/editor decision. The planner receives joined `beat_asset_options`
with each candidate's image-specific description, surrounding page context,
and available source-video moments.

HTTP metadata fetch status and browser capture readiness are recorded
separately. Browser preflight is authoritative for screenshot availability: a
page that rejects the metadata client but renders correctly in Chromium remains
available, while a challenge or access page is not advertised to the planner.

### 2. Planner

Entrypoint:

```python
from src.pipeline.visuals.planner import run
```

Purpose:

- read the video packet, script, voiceover package, trusted asset catalog, and
  visual config
- create an episode-level direction
- plan intro and closing visuals in one bounded bookend call using the authored
  beat-level visual briefs
- plan renderable scenes per selected story
- consume canonical beat IDs, beat functions, creative devices, visual goals,
  support truth IDs, source keys, visual briefs, and aligned voice timing
- insert one moving story-title interstitial over each story's first transition beat
- require at least one available catalog-backed real anchor for every story
- optionally run one bounded story-local visual editor pass whose default is
  keep and whose replacement must pass the same complete scene contract
- stitch scenes deterministically without allowing the LLM to author raw seconds
- return `data.visual_scene_plan`

The planner uses LangChain structured output with Pydantic models. The strict
provider schema exposes only the render kinds enabled for that story. A
catalog-backed render kind is omitted when the active story has no compatible
available asset, so an image-only story cannot request invented source video.
The available asset IDs form a closed enum in the story prompt; they are not
examples. Each
capability includes its exact payload shape, list cardinality, and enum values;
the dynamic scene payload is then carried as JSON text. Pydantic decodes and
validates its render-family structure before the story plan is accepted, and
app code applies the same shared payload validator plus source grounding. The
same payload validator is used by native planning, manual-plan
parsing, and render preflight so no path can bypass the nested scene contract.
Missing values, item structure, or source references trigger bounded targeted
replanning. Code does not delete invented asset IDs, substitute a different
asset, change the scene family, or synthesize semantic payload fields to make a
scene renderable. The only post-plan expansion is structural timing
continuation when one authored treatment covers an audio unit longer than the
render cap. Durable prompt text lives under:

```text
src/pipeline/visuals/planner/prompts/
```

The episode director, bookend planner, story planner, and visual editor each
have an independent `llm_roles` provider/model route in
`visuals/planner.yaml`. The daily profile uses GPT-4o-mini for episode
direction and bookends, then Kimi K3 for the main per-story plan and any
story-plan editor pass. An exact frozen one-story comparison completed in
303.79 seconds with six valid Kimi scenes, versus 17.95 seconds for
GPT-4o-mini. K3 produced a more varied and better-grounded plan on that sample,
so visual-plan quality now takes priority over its higher latency for the
story-local creative roles. K3 role config omits temperature, uses a
600-second timeout, and permits one provider attempt per bounded role call.
Both K3 story roles declare a GPT-4o route that is invoked only when Moonshot
returns an explicit HTTP 400/403 content-filter or high-risk rejection. The
planner records the rejected primary request and successful secondary request
in `llm_calls`, and reports the switch under `summary.provider_failover`.
Timeouts, rate limits, malformed schemas, and semantic scene validation errors
never trigger this provider switch.

The planner should not generate generic presentation-card outputs. The banned
old card language is enforced in code and prompts.

The production `visual_editor` receives one story's exact script units,
normalized scenes, story-owned asset catalog, episode direction, and structural
quality telemetry. It runs only when named plan problems recommend review; an
unused asset is not a defect or usage quota. It may keep the plan or return one complete
replacement through the same strict nested Pydantic story-plan contract used by
the initial planner. It does not patch individual scenes, does not rewrite
narration, and does not invent missing media or payload semantics.
The pass is limited to one and to the configured story-call budget. If the
editor fails, the explicit production policy keeps an already valid original;
an invalid original still fails planning rather than becoming generic text.
When a text scene covers a beat with catalog candidates, the production profile
asks this semantic editor to inspect those candidates. It may keep the text
when none fits; code never swaps the scene merely because an asset exists.

Selected-source YouTube, X, and Vimeo links/embeds may be resolved through the
bounded app-local `yt-dlp` adapter when enabled. Provider allowlists, link
counts, duration, resolution, byte size, and timeouts are config-driven. These
assets are provenance-trusted, but that trust is recorded separately from
narration-beat suitability.
When provider chapter metadata exists, the story planner can select one exact
`video_moment_id`. Media discovery then clips from that start rather than
blindly using 0:00. A missing or invented moment ID fails as an identity error;
the relevance of a valid listed moment remains the planner's judgment.

Story-title transitions reuse the story planner's semantically selected opening
image, video, or logo when one exists. The renderer overlays the canonical
story identity on that moving media; a short clean reset is used only when the
planner supplied no opening media anchor.

Catalog-backed scenes carry exact `asset_id` values. The planner may use a
`source_page` ID for a screenshot/proof scene, a `source_image` ID for a
context image, and a `logo` ID for an identity reveal. The app verifies that
the ID is available, belongs to the active story, and is compatible with the
requested scene kind. When the catalog contains a usable real anchor, at least
one actual scene payload must use an exact story-owned catalog asset ID with its
compatible render kind. The planner validates the scenes themselves rather than
a duplicate top-level anchor declaration. Production requests this anchor but
defaults `real_anchor_failure_mode` to `warn`, because a missing anchor is a
creative-quality concern rather than a reason to discard an otherwise valid
story plan. Profiles may explicitly choose `fail` for stricter review runs.
The planner may still request external media when a
profile enables that path, but it never invents asset URLs. It does not search,
download, capture, resolve, or render media.

For `source_article_scene`, the active script unit receives eligible screenshot
targets containing exact truth IDs and source text. A cited content/title truth
from the selected record wins over a merely similar page headline, so the
captured and highlighted article region supports what the narration is saying.

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

`scene_policy.hard_cap_tolerance_seconds` absorbs only subsecond duration
rounding at a configured hard cap. It is shared by planning and render
preflight and does not permit genuinely overlong scenes.

The production `one_scene_per_script_unit` assignment mode gives the LLM one
exact visual slot for each canonical spoken beat. It prevents the model from
authoring interval arithmetic, combining unrelated beats, or shifting a later
visual onto earlier narration. When one aligned audio unit exceeds the render
cap, the contract exposes multiple slots for that same unit and the story
planner must return distinct semantic treatments. The stitcher divides the
authoritative audio time across those planned treatments; it never copies one
screenshot, logo, chart, or text payload into several timing slices or treats
a changed animation label as a new idea. Intro/closing continuity slices use
different narration excerpts rather than duplicated full-beat text. Title
interstitials are protected from compaction and cannot merge into neighboring
sections.

Adjacent scenes with an identical render kind and effective payload fail plan
validation. This is an objective duplicate-spec check, not a code-based
creative-quality score. Text-like mix targets remain visible warnings and LLM
planning guidance rather than deterministic editorial approval gates.

Numeric scene families are literal. `data_counter_scene` values must contain a
number or measured quantity and must name exact `evidence_truth_ids` from the
active story. Native and manual ChatGPT plan paths validate nested renderer
shape and evidence-ID ownership. They do not compare displayed labels, values,
quotes, or punctuation against source strings; semantic accuracy remains the
planner/editor and human review responsibility. Code does not decide whether
the graphic is the best editorial treatment and never invents missing metrics
or relationships to make a payload renderable.

Manual ChatGPT plans may author per-beat `visual_action` and `emphasis_words`.
The parser preserves those fields while replacing only beat text and timing with
the authoritative voiceover alignment. Missing creative beat guidance receives
the neutral action `hold_scene`; it is never guessed from narration keywords.

### 3. Media Discovery

Entrypoint:

```python
from src.pipeline.visuals.media_discovery import run
```

Purpose:

- copy exact catalog-backed source images requested by the planner
- prepare an exact planner-selected catalog video moment when one is present
- optionally search only for unresolved scenes that explicitly request
  contextual images or b-roll
- use lexical/provider signals only to build a bounded candidate pool
- use structured vision output to verify narration fit, visible evidence, and
  exact named-identity requirements before selecting an asset
- sample long B-roll videos into bounded windows and use a second structured
  vision decision to select one supplied window rather than a random offset
- download the selected image or prepare only the short muted video clip needed
  by the scene
- preserve candidate metadata and attribution in `data.visual_media_package`
- explicitly convert an unresolved media request to the configured fallback
  scene instead of hiding a missing file

The active production profile uses `trusted_catalog_only: true`, disables the
paid semantic verifier, and permits no generic fallback. A scene without a
usable catalog ID remains unresolved and returns a clear replan requirement;
keyword overlap never becomes the final semantic selector. This is the current
cost-conscious path.

When external research is deliberately enabled, semantic verifier failure
rejects the candidate by default. Any query fallback
or start-at-zero clip fallback must be explicitly enabled in config and remains
visible in the returned package. Episode fallback use is capped. A fallback
may reuse an exact narration-derived phrase, but it must remain unresolved when
no such phrase exists; production code never inserts generic copy merely to
make the renderer succeed.

Timeline splitting can produce multiple short image scenes from one script
beat. When `reuse_equivalent_image_requests` is enabled, media discovery hashes
the normalized story, beat, query, and visible constraints, searches and
verifies that logical request once, and exposes the selected asset separately
for every scene that uses it. The fallback budget is likewise charged once per
unique media request rather than once per split clip. Configure that budget with
`max_fallback_requests`; historical frozen profiles using
`max_fallback_scenes` remain supported. B-roll clips remain
scene-specific because their extracted duration and start window can differ.

The vision decision field `contains_forbidden_visual` is literal: it is true
only when the candidate visibly contains an item from `must_avoid`. Exact named
people, products, interfaces, and events cannot be satisfied by a different
representative identity.

Wikimedia Commons images are enabled by default and require no API key. Pexels
and Pixabay adapters are available but disabled until their free API keys are
put in `PEXELS_API_KEY` or `PIXABAY_API_KEY` and enabled in workbench config.
Enable `broll_video_scene` in `scene_policy.allowed_render_kinds` at the same
time. Do not put API keys in YAML. Wikimedia video support exists for targeted
experiments, but is off by default because search relevance and large remote
WebM delivery are not consistent enough for routine full runs.

### 4. Asset Resolver

Entrypoint:

```python
from src.pipeline.visuals.asset_resolver import run
```

Purpose:

- resolve screenshot assets for source-backed scenes
- reuse a successful screenshot capture when several scenes request the exact
  same URL, target text, capture mode, zoom, and highlight treatment, avoiding
  repeated publisher requests and anti-bot throttling while retaining one
  scene-owned output file per scene
- optionally reuse a persistent page capture across runs, with a config-driven
  cache directory and TTL, so repeated article treatments do not repeatedly hit
  the publisher
- resolve `source_proof_montage` scenes into two or three independently captured
  story-owned source pages
- resolve logo assets for logo reveal scenes and report their actual quality
  class (`verified_logo`, `simple_icon`, `domain_favicon`, or
  `text_identity_fallback`)
- report source target-text misses instead of presenting an unrelated page
  viewport as successful proof
- validate and attach downloaded contextual image/b-roll assets
- pass through graphic-only scenes that do not require assets
- return `data.visual_asset_manifest`

Current asset mapping:

```text
source_article_scene             -> source_screenshot
quote_or_claim_highlight_scene   -> source_screenshot
browser_walkthrough_scene        -> source_screenshot
context_image_scene              -> context_image
broll_video_scene                -> broll_video
logo_reveal_scene                -> logo_asset
editorial_text_scene             -> none
simple_explainer_scene           -> none
story_transition_scene           -> none
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
decision_tree_scene              -> none
capability_matrix_scene          -> none
timeline_zoom_scene              -> none
document_stack_scene             -> source_montage for source_proof_montage; otherwise none
signal_radar_scene               -> none
interface_transform_scene        -> none
transition_stinger_scene         -> none
```

If a new scene type is added, implement and visually verify its named recipe,
then update the planner contracts, asset resolver classification, selected
render backends, and workbench config together. Do not advertise an unrendered
capability to the LLM.

Text-identity fallbacks are explicitly not verified logos. They preserve and
fit the complete entity name instead of clipping it or substituting an invented
brand label. The entity name appears as the identity badge while the companion
idea remains the visual headline, avoiding repeated fake branding. Production
profiles may disable them or cap their use.

Source screenshot capture can apply a profile-driven focus zoom and target
highlight after locating a semantic headline/body candidate. Large page
containers are not accepted merely because they contain the requested words;
the capture prefers readable headings, paragraphs, and list items.
Challenge pages, access-denied responses, and HTTP 401/403/429 responses are
reported as capture failures rather than being rendered as source proof.

### 5. Render

Entrypoint:

```python
from src.pipeline.visuals.render import run
```

Purpose:

- validate scene durations before rendering
- treat `scene_policy.max_scene_seconds` as the pacing target and
  `scene_policy.hard_max_scene_seconds` as the renderer safety limit, so small
  voiceover timing variation does not trigger unnecessary replanning
- validate every nested scene payload again before spending render time
- select one explicit rendering backend; never silently cross-fallback
- build the Remotion project once per Remotion run, or generate one isolated
  HyperFrames composition per scene
- render independent MP4 scene clips with bounded persistent-browser workers
- render scene clips without audio; the authoritative voiceover is attached once
  during assembly so AAC padding cannot accumulate at scene boundaries
- cap browser/frame concurrency inside each scene to avoid CPU/RAM overload
- restore unchanged clips from a persistent content-addressed cache
- support scene/story-targeted preview renders without making them assembly-ready
- retry failed or missing scene outputs serially and preserve attempt logs
- emit start, cache, batch-progress, retry, and completion events through the
  lightweight runtime logger when called by orchestration
- return `data.visual_render_package`

The renderer backends live under:

```text
src/pipeline/visuals/remotion_engine/
src/pipeline/visuals/hyperframes_engine/
```

All scene components author against a stable 1920x1080 reference canvas. The
scene root scales and centers that canvas to the configured 16:9 render preset,
so 720p tests, 1080p production, 2K, and 4K preserve identical composition and
safe areas. Individual scenes must not position content against the requested
pixel dimensions directly.

Run `npm install` in the selected engine directory on a fresh machine before
rendering.

Render behavior is config-driven:

```text
render_mode           preview or final
backend               remotion or hyperframes
selected_scene_ids    optional focused rerender selection
selected_story_ids    optional focused rerender selection
worker_count          scene clips rendered at the same time
frame_concurrency     bounded browser/frame workers inside a scene render
max_render_attempts   bounded attempts per scene; retries run serially
reuse_cached_scenes   restore unchanged clips from the persistent cache
```

The daily production profile uses the inspected `editorial_minimal` Remotion
renderer as the stable delivery baseline for the active recipe-backed
vocabulary:
source proof, contextual image/video, logo identity, editorial typography,
simple explainers, story transitions, claim highlights, interface motion, and
evidence stacks.
Named recipes share the same payload and provenance contract across Remotion
and HyperFrames. HyperFrames is an explicit comparison backend, not an implicit
fallback or the current delivery default. It uses pinned local dependencies, a
copied `frame.md` design contract, strict composition checks, isolated per-scene
projects, and the same cache envelope. Selecting a scene without a valid named
recipe fails before rendering and never crosses to another engine.

Ten or fifteen workers are not automatically faster on either backend:
Chromium, ffmpeg, memory bandwidth, and encoders become the bottleneck, so the
profile keeps scene and frame concurrency bounded.
The pinned `hyperframes@0.7.64` dependency still carries an unresolved
high-severity transitive `adm-zip` denial-of-service advisory. Production must
therefore continue to render only pipeline-owned compositions and trusted local
assets until upstream ships a fix.

Cache identity includes the scene payload, render settings, resolved asset
content, and selected engine source. A prompt, asset, scene, or renderer change
therefore invalidates only affected clips. Preview mode uses 720p,
bitrate-based hardware-friendly encoding, and a fast path; final mode retains
CRF-based quality and renders the complete scene manifest at delivery quality.
Focused previews intentionally set `ready_for_video_assembly=false`. They are
written below `render_preview/focused/{backend-selection-hash}` and do not
replace the complete episode preview or another renderer's comparison.

The production notebook keeps preview and final artifacts separate:

```text
visuals/render_preview/    720p preview clips
visuals/assembly_preview/  optional full preview with voiceover
visuals/review_preview/    preview contact sheet
visuals/render/            complete delivery-quality clips
visuals/assembly/          canonical final video
visuals/review/            canonical publish-review artifacts
```

Preview mode never creates a publish handoff. This prevents a fast 720p pass or
focused scene test from replacing or masquerading as the delivery render.

Do not start two full render cells at the same time. One render run already
uses multiple browser workers and ffmpeg encoders; overlapping runs compete for
the same CPU and memory and can be slower than one bounded run.

The production profile keeps 2K resolution and CRF-based quality while using
the `veryfast` x264 preset. This favors shorter local render time and somewhat
larger clips instead of reducing resolution.

### 6. Assembly

Entrypoint:

```python
from src.pipeline.visuals.assembly import run
```

Purpose:

- verify script, voiceover, visual-plan, and render fingerprints
- probe each rendered clip and the WAV before invoking ffmpeg
- losslessly remove audio from legacy scene clips before concatenation
- require planned scene IDs/order and real visual duration to match the audio
- concatenate rendered scene clips
- attach the selected voiceover WAV
- verify that the final MP4 contains both video and audio streams
- write the final review MP4
- return `data.final_video_package`

Assembly currently uses rendered scene clips plus ffmpeg. A later milestone may
move final assembly into one full Remotion composition for better transitions,
captions, and sync control.

### 7. Review

Entrypoint:

```python
from src.pipeline.visuals.review import run
```

Purpose:

- verify the selected final-video artifact and its provenance
- sample configured frames across the complete episode
- write a contact sheet and review package
- extract one midpoint frame per planned scene and write
  `story_review_manifest.json` plus `story_review_report.html`, grouped by
  intro, story, and closing with narration, recipe, asset, source, and planner
  rationale beside each frame
- make human visual review an explicit publish prerequisite

The contact sheet is a navigation aid, not an automatic creative approval.
Inspect the final video with audio for semantic fit, legibility, repetition,
timing, and synchronization.

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
- `editorial_text_scene`: punctuate one concise hook, implication, or punchline
  with expressive serif typography, whitespace, and one restrained accent;
  never place it inside a decorative card.
- `simple_explainer_scene`: explain one small relationship or process using two
  to four large labels and restrained connectors.
- `story_transition_scene`: introduce each selected story with its complete
  title in a deterministic, voiceover-aligned editorial transition.
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

Text-like scene types should support the video, not dominate it. In the default
profile, `editorial_text_scene` is a short punctuation device between source,
image, and identity scenes. Specialist profiles may additionally enable
kinetic type, charts, maps, flows, matrices, or other renderers when the active
narration and source material genuinely call for them.

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

The profile manifest and module authoring config live in:

```text
src/pipeline/config/workbench.yaml
src/pipeline/config/profiles/{profile}/visuals/*.yaml
```

Relevant config sections:

- `visuals.asset_catalog`: trusted source-page/image/video collection,
  structural duplicate filtering, logo hints, fetch limits, anchor policy, and
  contact-sheet settings.
- `visuals.planner`: default and role-specific LLM provider/model routes,
  structured-output policy, scene policy, named recipe policy, visual
  capabilities, and the text-supporting visual-mix target.
- `visuals.media_discovery`: provider enablement, environment-key names,
  candidate/download limits, semantic verifier and clip-selector models,
  identity confidence, video clipping, and explicit fallback behavior.
- `visuals.asset_resolver`: browser, screenshot, logo, and output settings.
- `visuals.render`: explicit backend, backend paths, quality preset, encoder
  options, worker count, cache, and per-scene caps.
- `visuals.assembly`: final-video mux/assembly settings.
- `visuals.review`: contact-sheet sampling and output settings.

`visuals.render.active_mode` selects a named entry from
`visuals.render.profiles` in the production notebook. Use `preview` while
iterating and `final` only after the scene plan and representative clips pass
review. The module itself still receives a fully resolved render config and
does not read the YAML.

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
- domain favicon fallback
- explicit text-identity fallback when enabled

Favicon and text fallbacks are not official verified brand logos. Their quality
class travels with the asset. The production profile disables favicon lookup so
a publication favicon cannot impersonate the narrated company; unresolved
entities use an explicitly typographic identity treatment. Add local overrides
when identity must be exact.

Source-proof scenes use `target_miss_policy: failed` in production. Capturing a
page is not enough when the requested headline, quote, or body target was not
located.

## Notebook Usage

Use:

```text
notebooks/production/visual_production.ipynb
```

Visual sections:

- `1. Build Trusted Asset Catalog And Load Or Generate Visual Plan`
- `2. Discover Media And Resolve Assets`
- `3. Render Scene Clips`
- `4. Assemble Final Video With Voiceover`
- `5. Build Visual Contact Sheet`
- `6. Build Manual Publish Review Handoff`

Optional manual ChatGPT visual planning can replace the generated plan in
section 1:

- build the same trusted asset catalog used by the native planner
- export a `visual_scene_plan` handoff with `handoffs.chatgpt_exporter`
- paste the response into a text file
- parse it with `handoffs.chatgpt_visual_plan_parser`, which verifies every
  referenced asset ID and story owner
- continue from asset resolution using the parsed result

If the parser returns `status="needs_repair"`, repair the semantic ownership or
timeline problem and parse again. Do not treat a substantially auto-repaired
manual plan as production-ready.

If section 7 fails with unsupported render kinds, the planner and resolver are
out of sync. Add the scene type to the resolver classification and render
contracts instead of removing the scene from the plan.

For fast CLI iteration against a completed run, replay only renderer code and
saved assets:

```bash
python3 -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode preview \
  --from-module visual_render \
  --stop-after visual_render \
  --scene-id scene_003
```

Repeat `--scene-id` or use `--story-id` for a bounded selection. This path makes
no LLM or TTS call and does not assemble or publish. Omit the selections only
when a complete cached preview is needed.

For fast notebook iteration, keep `VISUAL_RENDER_MODE = "preview"` and optionally set
`VISUAL_SCENE_IDS` or `VISUAL_STORY_IDS` near the top of the notebook. Clear
both selections and switch to `final` before assembly. A second unchanged
preview should report cache hits rather than re-rendering every clip.

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
