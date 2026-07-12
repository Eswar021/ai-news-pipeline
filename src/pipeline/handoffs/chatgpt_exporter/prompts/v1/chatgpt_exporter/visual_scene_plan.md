Profile: visual_scene_plan

Use this handoff to create a renderable visual scene plan for the selected
roundup video.

Your job:
- Plan YouTube-style visuals for the provided final script.
- Use the provided section-aware aligned beat timing when available, but do **not** make
  one visual scene per beat.
- Group adjacent beats into semantic visual scenes: one scene should usually
  cover one complete visual idea, normally about 6-10 seconds and never longer
  than the configured max scene duration.
- Put exact beat-level timing inside `payload.beats` so the renderer can reveal
  sub-points in sync while the scene stays visually coherent.
- Use only the selected stories, records, URLs, source_record_key values, and
  visual capabilities in the payload.
- Return a JSON scene plan that our asset resolver and Remotion renderer can
  consume.
- Prefer source-backed scenes, logo moments, data counters, trend lines,
  real contextual images, representative b-roll, ecosystem maps, architecture
  flows, transition stingers, and short kinetic type over generic text-heavy
  visuals.

Do not:
- write or revise the narration
- invent URLs, screenshots, source titles, quotes, facts, companies, products,
  or footage
- create old presentation-card scene types such as title_card, timeline_card,
  entity_card, recap_card, quote_card, data_card, or fallback_card
- create a separate scene for sentence fragments such as "This week, the U.S."
  or "Which raises an obvious question" unless it is a deliberate transition
  beat
- use generic placeholder labels such as "Manual process", "Old systems",
  "Input", "System", "Outcome", "watch next", or "Best fit" unless those exact
  words are the intended on-screen message
- output Markdown inside the JSON block
- create scenes longer than the configured max_scene_seconds
- create story-title scenes; the parser inserts exactly one moving title over
  each story's first aligned transition beat

Planning guidance:
- Use `source_article_scene` or `quote_or_claim_highlight_scene` when the
  narration cites a source, reported number, caveat, launch claim, or
  source-specific detail.
- Use `logo_reveal_scene` when introducing a company, product, model, platform,
  or lab.
- Use `context_image_scene` when a real photograph can directly show the
  concrete person, place, device, lab, office, infrastructure, or physical
  subject being discussed. Provide two or three `search_queries`, plus
  `must_show`, `must_avoid`, `shot_style`, and optional short overlay fields.
- Use `broll_video_scene` for a short representative clip of a concrete action,
  environment, device, workflow, or infrastructure moment. Never imply generic
  b-roll depicts the exact reported event. Provide search intent and constraints,
  not an asset URL.
- Use `data_counter_scene` for concrete numbers such as funding, valuation,
  price, dates, percentages, model sizes, speedups, user counts, employee
  counts, or duration.
- Use `trend_line_scene` only for conceptual momentum or pressure, not fake
  precise market data.
- Use `ecosystem_map_scene` when relationships between companies/products/users
  matter.
- Use `architecture_flow_scene` when the narration explains how a system,
  pipeline, agent workflow, training process, API, SDK, cloud, or deployment
  works.
- Use `transition_stinger_scene` for fast story-to-story pivots or section
  changes.
- Use `kinetic_type_scene`, `bullet_build_scene`, or `recap_sequence_scene`
  only when the visual should emphasize short spoken words, a compact list, or
  the final roundup recap.
- Prefer fewer, stronger scenes over many tiny scenes. A source, diagram,
  counter, matrix, or flow scene can cover several neighboring narration chunks
  if the payload includes timed beats.
- Every non-source visual must be specific to the spoken idea. For example,
  if the narration says an overlay converts A2A messages into legacy API calls,
  the flow labels should say that exact mechanism, not generic "Input/System/Outcome".

Return exactly this top-level section format:

```text
CHATGPT_VISUAL_PLAN_RESPONSE_V1

[NOTES]
Short notes for the human operator. These are not rendered.
Mention any uncertainty, timing approximation, or source-scene limitation.

[VISUAL_SCENE_PLAN_JSON]
{
  "episode_style": {
    "visual_language": "...",
    "pacing_notes": "...",
    "recurring_motifs": [],
    "color_notes": "...",
    "typography_notes": "...",
    "transition_notes": "..."
  },
  "story_sections": [],
  "scene_timeline": []
}
```

Each `scene_timeline` item must include:
- `scene_id`: stable id such as `scene_001`
- `scene_order`: integer starting at 1
- `story_id`: selected story id, or empty string for intro/closing/transition
- `section_type`: `intro`, `story`, `closing`, or `transition`
- `start_seconds`: number copied from the first covered aligned beat
- `end_seconds`: number copied from the last covered aligned beat
- `render_kind`: one allowed render kind from `visual_capabilities`
- `script_excerpt`: the spoken script covered by this scene
- `visual_intent`: short explanation of why this visual helps
- `payload`: render-kind-specific object
- `covered_unit_orders`: authoritative aligned beat order numbers covered by this scene

`covered_unit_orders` is the timing authority. The parser recalculates scene
start/end seconds from those units and rejects unknown values, so do not guess,
stretch, or interpolate timing.

For source-backed scene payloads, use only the exact `source_record_key` and
`url` values from the payload. For contextual image and b-roll payloads, do not
provide URLs; the media discovery module will search approved providers. For
no-asset graphics, keep payload text short and readable.

For every scene payload, include `beats` when voiceover chunks are available:

```json
{
  "beats": [
    {
      "unit_order": 12,
      "beat_id": "section_03_story_example_beat_02",
      "beat_type": "explanation",
      "start_seconds": 51.93,
      "end_seconds": 54.97,
      "text": "Picture a translator sitting on top of a service you already have.",
      "visual_action": "advance_diagram_step",
      "emphasis_words": ["translator", "service"]
    }
  ]
}
```

The scene itself can cover multiple beats. The beats tell the renderer what to
reveal inside that scene.
