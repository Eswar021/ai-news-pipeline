# Visuals Roadmap

This document tracks where the v2 visual system should go next. It is a
directional product/engineering map, not a full technical spec. Before editing
code, still read the actual modules under `src/pipeline_v2/visuals/`.

## Current Goal

The visual system should feel like a YouTube motion video, not a slide deck.

That means:

- show real source material when the narration references a report, article, or
  launch page
- show logos/entities when the narration introduces who is involved
- reveal points one by one when the narration lists implications
- use kinetic text for retention beats, transitions, and punchy phrases
- avoid generic title cards, timeline cards, entity cards, and fallback cards
- keep visuals synchronized to the spoken script and voiceover timing

## Current System

Current pipeline:

```text
planner -> media_discovery -> asset_resolver -> render -> assembly
```

For visual development and renderer QA, use:

```text
notebooks/v2_visual_assets_lab.ipynb
```

The lab renders scene modules with sample JSON payloads and writes generated
clips under `output_v2/visual_lab/{LAB_RUN_ID}/`. Use it before wiring a new
visual kind into the full pipeline.

Current render kinds:

- `source_article_scene`
- `quote_or_claim_highlight_scene`
- `logo_reveal_scene`
- `kinetic_type_scene`
- `bullet_build_scene`
- `entity_compare_scene`
- `recap_sequence_scene`
- `data_counter_scene`
- `trend_line_scene`
- `bar_chart_scene`
- `bar_race_scene`
- `ranked_list_scene`
- `benchmark_delta_scene`
- `ecosystem_map_scene`
- `architecture_flow_scene`
- `process_zoom_scene`
- `browser_walkthrough_scene`
- `decision_tree_scene`
- `capability_matrix_scene`
- `timeline_zoom_scene`
- `document_stack_scene`
- `signal_radar_scene`
- `interface_transform_scene`
- `transition_stinger_scene`

Current strengths:

- scene clips render through Remotion
- source screenshots work for many selected-story URLs
- final video assembly can attach voiceover audio
- planner is per-story and config-driven
- planner and parser now preserve voiceover chunks as `payload.beats` while
  allowing scenes to cover larger semantic visual ideas
- long final-scene stretch bug is guarded against
- story-level planner schema/fallback failures are reported before asset
  resolution by default
- planner can request real contextual images and representative b-roll without
  inventing URLs
- media discovery preserves provider, creator, license, source, query, score,
  and local-path metadata, and prepares only short scene-length video clips

Current weaknesses:

- visual sync is still approximate, especially near dense closing sections
- repeated graphic styles can still appear inside long story runs, though the
  planner now has non-text graphics for counters, trends, maps, flows, browser
  walkthroughs, matrices, evidence stacks, radar scans, and interface transforms
- manual prose scripts still need better story/closing boundary detection
- bullet scenes reveal points by scene timing, not precise narration beats
- source screenshots do not yet reliably crop to exact quoted text
- logo resolution is useful but still thin for product/model names
- contextual media ranking is metadata/search based; it does not yet use a
  vision model to verify that the exact selected shot visually matches the beat
- Wikimedia works without a key, but broader polished stock coverage requires
  enabling Pexels/Pixabay with operator-owned free API keys
- final assembly is clip-concat based, so transitions and captions are limited
- render quality is now config-driven through resolution presets and encoder
  settings, but higher presets increase render time

## Product Principles

Use visuals for attention and comprehension.

Good visuals should:

- match what the viewer is hearing at that moment
- help the viewer understand the story faster
- create variation every few seconds without becoming noisy
- use motion to direct attention, not distract from the narration
- make source-backed moments feel credible by showing the source
- make abstract AI/product ideas tangible through logos, diagrams, or examples
- avoid text-heavy slides that compete with the voiceover

## Priority 1: Visual Beat Map

Problem:

- scenes currently align to script/voiceover chunks, but the renderer does not
  know the smaller beat-by-beat reveal moments inside each scene

Build:

- create `visual_beat_map` inside `visual_scene_plan`
- map each script unit or voiceover chunk to one or more visual beats
- include beat start/end seconds, spoken phrase, visual action, and emphasis
- pass beat timing into scene payloads
- keep scenes semantic: a visual scene may cover multiple voiceover chunks when
  they form one complete visual idea

Example payload idea:

```json
{
  "beats": [
    {
      "start_seconds": 0.0,
      "end_seconds": 1.8,
      "text": "Gemini is moving into products",
      "visual_action": "reveal_point"
    }
  ]
}
```

Expected improvement:

- bullet points can appear when the narrator reaches them
- closing sections stop drifting visually
- fewer scenes need to carry too much narration at once

## Priority 2: Timed Point Reveal Renderers

Problem:

- `bullet_build_scene` and `recap_sequence_scene` are visually better than old
  cards, but their timing is still mostly scene-relative

Build:

- update Remotion scenes to read `payload.beats`
- reveal each point based on the beat timing
- support optional emphasis words per beat
- keep text density capped per frame

Expected improvement:

- the video feels edited to the voice instead of simply placed under it

## Priority 3: Source Focus Scenes

Problem:

- source screenshots are useful, but they often show the page broadly instead
  of focusing the exact line or claim being discussed

Build:

- improve target-text search in screenshot capture
- scroll to the nearest matching heading or paragraph
- crop or zoom toward the relevant area
- draw a highlight sweep over matching phrases
- use `quote_or_claim_highlight_scene` for source-backed claims, numbers, and
  caveats

Expected improvement:

- source scenes become evidence moments, not just webpage background

## Priority 4: Better Entity And Logo Handling

Problem:

- some important companies, models, and products fall back to text-only visuals

Build:

- add local logo overrides
- add product/model alias mapping in config
- add domain extraction from selected records
- use favicon fallback only after local/simple-icons lookup fails
- support multi-logo stacks for ecosystems, partnerships, and comparisons

Expected improvement:

- stories feel more concrete and easier to follow

## Priority 5: New YouTube-Oriented Scene Types

Add scene types only when they support a real storytelling job.

Implemented first-pass code-generated graphic types:

- `data_counter_scene`: animate a number, cost, valuation, model size, or date.
- `ecosystem_map_scene`: show companies/products connected in a simple graph.
- `trend_line_scene`: show growth, decline, pressure, or momentum as a stylized
  directional chart.
- `bar_chart_scene`: show two to five bars for grounded values or clearly
  labeled relative signals.
- `bar_race_scene`: show race/momentum/rank movement across entities or stages.
- `ranked_list_scene`: show fast top-three/top-five priorities, risks, tools, or
  takeaways.
- `benchmark_delta_scene`: show before/after speed, cost, latency, quality, or
  benchmark shifts.
- `architecture_flow_scene`: show app, SDK, API, model, agent, training, or
  deployment steps as a motion flow.
- `process_zoom_scene`: zoom into one critical stage of a process or workflow.
- `browser_walkthrough_scene`: simulate a guided browse through a source,
  product page, or workflow surface when a static screenshot would feel flat.
- `decision_tree_scene`: show routing, safety, policy, product strategy, or
  agent choices as a branching path.
- `capability_matrix_scene`: compare model/product/platform tradeoffs across
  speed, cost, context, modality, tooling, or other compact dimensions.
- `timeline_zoom_scene`: show a short sequence of events and zoom attention
  into the critical moment without using old timeline cards.
- `document_stack_scene`: stack papers, releases, docs, GitHub issues, reports,
  or articles as visible evidence.
- `signal_radar_scene`: scan for emerging trend, company, model, or market
  signals.
- `interface_transform_scene`: show before/after workflow or UI transformation,
  especially when AI moves from chat to tools.
- `transition_stinger_scene`: short branded motion bumper between stories or
  dense visual sections.

Candidate types still worth adding later:

- `generated_illustration_scene`: generated or code-built imagery for abstract
  concepts when real contextual media and source pages are not useful.
- `caption_emphasis_scene`: transcript-aware word emphasis for key narration
  phrases.
- `small_multiple_scene`: compare several tiny charts without implying precise
  data when the script is about patterns rather than one metric.
- `market_map_scene`: place companies/products into a two-axis landscape when
  the story is about positioning.

Do not add all of these at once. Add one, prove it improves the final video,
then add the next.

## Visual Families

Keep scene modules grouped by storytelling job, not by one-off visual names.

Recommended Remotion/code organization:

- `text_motion`: kinetic type, bullet build, caption emphasis, recap sequence,
  transition stingers. These should be used for retention beats and short
  narration phrases, not as the default visual for every scene.
- `data_viz`: counters, trend lines, bars, rankings, benchmark deltas, funding,
  cost, latency, adoption, and dates. These should make numbers feel concrete.
- `diagram_motion`: architecture flows, ecosystem maps, decision trees,
  process zooms, market maps, and entity comparisons. These should explain
  relationships better than text can.
- `source_media`: source article scenes, quote/claim highlights, browser
  walkthroughs, and screenshot focus tools. These should provide visible
  provenance when narration references a real source.
- `brand_media`: logo reveals, multi-logo stacks, product/model identity
  moments, and partner/comparison layouts.

The planner should choose from these families based on narration need:

- use `source_media` when credibility/source evidence matters
- use `brand_media` when the viewer needs entity recognition
- use `data_viz` when numbers, change, scale, or comparisons are spoken
- use `diagram_motion` when the story explains systems or relationships
- use `text_motion` only for punchlines, transitions, and short emphasis

## Priority 6: Visual Quality Report

Problem:

- currently we inspect outputs manually after something feels wrong

Build:

- write `visual_quality_report.json`
- include scene-kind mix, repeated-kind runs, average duration, max duration,
  unresolved asset count, text-density warnings, source coverage, and fallback
  counts
- optionally write contact sheets for scene midpoints and final-video samples

Expected improvement:

- bad visual plans become visible before wasting render time

## Priority 6A: Semantic Media Verification

Problem:

- provider search results can be topically relevant while still showing the
  wrong composition, subject prominence, or visual action for the exact beat

Build:

- create thumbnails for the top few media candidates
- use a local or API vision model only on that small shortlist
- score must-show subject presence, must-avoid violations, composition, text or
  watermark clutter, and match to the spoken beat
- keep deterministic provider/license/resolution checks as hard guardrails

Expected improvement:

- real images and b-roll match narration more reliably without sending huge
  provider catalogs to an LLM

## Priority 7: Full Remotion Assembly

Problem:

- clip concatenation works, but limits transitions, global captions, and
  frame-accurate audio sync

Build:

- render the full timeline as one Remotion composition
- attach voiceover inside the Remotion render
- add transitions between scenes
- add optional lower-thirds or captions
- keep scene clips as debug artifacts only

Expected improvement:

- final video feels edited as one piece instead of stitched from clips

## Priority 8: Captions And Retention Layer

Problem:

- current visuals do not yet use captions or word-level emphasis

Build:

- generate transcript timing from voiceover chunks or later forced alignment
- add selective captions for key phrases, not full constant subtitles
- use captions only when they improve retention or clarity
- avoid covering source screenshots with too much text

Expected improvement:

- important ideas land more clearly, especially on mobile or low-volume viewing

## Guardrails

Every visual change should preserve these rules:

- no old card scene types as primary output
- no one-run company/title hacks in code
- no scene longer than the configured max duration
- no unsupported scene type should reach the renderer
- source-backed scenes need selected-story URLs and record keys
- LLM prompts should receive visual capabilities from config
- notebook outputs are generated artifacts, not source-of-truth config

## Suggested Next Implementation Order

Recommended near-term order:

1. Add semantic thumbnail verification for top media candidates.
2. Add `visual_quality_report.json` and contact sheets before full rendering.
3. Improve source screenshot text focus and highlighting.
4. Expand timed-beat behavior across diagrams, charts, and media overlays.
5. Move final assembly into one Remotion composition.
