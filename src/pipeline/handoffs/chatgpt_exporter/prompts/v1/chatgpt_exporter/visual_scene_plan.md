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
- Cover every aligned beat order exactly once in the episode timeline, except
  that the parser owns each story's first title-anchor beat. Never skip one beat
  and assign a later beat's visual idea to the skipped order.
- Put exact beat-level timing inside `payload.beats` so the renderer can reveal
  sub-points in sync while the scene stays visually coherent.
- Use only the selected stories, records, URLs, source_record_key values, and
  visual capabilities in the payload.
- Return a JSON scene plan that our asset resolver and Remotion renderer can
  consume.
- Treat `visual_context.visual_capabilities` as the complete and authoritative
  menu for this run. Prefer its richer source, media, explanatory-graphic, and
  motion capabilities over generic text-heavy visuals.
- Treat `asset_catalog.assets` as the authoritative real-world media available
  for this run. Use at least one relevant available catalog asset in every
  selected story and copy its exact `asset_id` into the scene payload.

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
- Never use a render kind absent from `visual_context.visual_capabilities`, even
  if you remember it from another run or see it in an example elsewhere.
- For every available capability, read its `best_for`, `avoid_when`,
  `required_payload_fields`, and `render_notes`; choose the richest capability
  that directly explains the active narration.
- Prefer available source or discovery-media capabilities for concrete people,
  places, devices, environments, and source-specific details.
- Prefer available explanatory graphics for supported numbers, relationships,
  comparisons, workflows, ordered choices, evidence stacks, and before/after
  behavior.
- A catalog `source_page` may drive a source article, quote highlight, or
  browser walkthrough. A catalog `source_image` may drive a context image. A
  catalog `logo` may drive a logo reveal. Never use an asset from another story
  and never treat an unresolved asset brief as available.
- Use available text-oriented capabilities only for short spoken emphasis,
  compact lists, transitions, or cases where no richer available capability is
  appropriate.
- Prefer fewer, stronger scenes over many tiny scenes. A source, diagram,
  counter, matrix, or flow scene can cover several neighboring narration chunks
  if the payload includes timed beats.
- Every non-source visual must be specific to the spoken idea. For example,
  if the narration says an overlay converts A2A messages into legacy API calls,
  the flow labels should say that exact mechanism, not generic "Input/System/Outcome".
- For every data, trend, comparison, map, flow, process, decision, matrix,
  timeline, document, radar, or interface scene, include selected-story
  `evidence_record_keys` and concise `evidence_text` explaining exactly what
  supports that graphic. Never invent values or relationships to complete a
  visual. If the evidence is incomplete, use a source, contextual-media, logo,
  or exact-narration kinetic scene instead.
- Numeric graphics must also include `evidence_truth_ids` copied from the
  assigned story's `story_truth_indexes`. Display only exact values carried by
  those metric truth items. A vague phrase such as "a few years" is not
  permission to invent a specific number.

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
- `evidence_record_keys`: selected-story record keys supporting semantic graphics; otherwise an empty list
- `evidence_truth_ids`: exact selected-story truth IDs supporting displayed numbers; otherwise an empty list
- `evidence_text`: concise support for semantic graphics; otherwise an empty string
- `grounding_basis`: `selected_record`, `script_beat`, `editorial_transition`, or `context_media`
- `payload`: render-kind-specific object
- `covered_unit_orders`: authoritative aligned beat order numbers covered by this scene

`covered_unit_orders` is the timing authority. The parser recalculates scene
start/end seconds from those units and rejects unknown values, so do not guess,
stretch, or interpolate timing.

For source-backed scene payloads, use only the exact `source_record_key` and
`url` values from the payload and include the matching catalog `asset_id`.
In trusted-catalog production mode, use context images only with a supplied
`source_image` asset_id; do not request generic stock imagery. For no-asset
graphics, keep payload text short and readable.

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
