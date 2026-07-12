Profile: content_packet

Use this handoff as a production-ready content packet.

Your job:
- Write the final spoken narration for the selected video packet.
- Return a paste-friendly response that the pipeline can parse.
- Preserve required facts, cautious facts, source attribution, and blocked angles.
- Keep the target format, selected story order, and roles from the packet.
- Make the narration feel like a strong YouTube video, not a technical report.
- You may use broader context, web/search knowledge, analogies, and creative
  framing to make the story clearer and more engaging.
- Do not silently add new factual claims to the selected stories. If you use
  outside context or a searched fact, disclose it under `[NOTES]` and keep it
  non-essential unless the payload already supports the claim.

Focus on:
- a strong hook
- plain-language stakes
- segment flow
- transitions
- viewer curiosity
- useful context without overexplaining
- caution language only where it helps the viewer understand uncertainty
- source usage
- what the final script should say clearly and what it must avoid

Return exactly this top-level section format:

```text
CHATGPT_PIPELINE_RESPONSE_V1

[NOTES]
Short notes for the human operator. These are not spoken.
If you used outside context or web/search knowledge, list it here under
external_context_used.

[SCRIPT]
Start with the exact line `[SCRIPT_SECTIONS_JSON]`, then return one fenced JSON
object with a `sections` list. Use the exact marker names from **Required Script
Markers** as each `section_id`; the parser normalizes packet segment IDs into
canonical section IDs.

Each section object must contain:
- `section_id`
- `narration_text`, equal to the spoken beat texts joined in order
- `beats`, a list of objects with `beat_type`, `narration_text`,
  `source_record_keys`, and `visual_brief`

Each `visual_brief` must contain:
- `purpose`
- `visual_intent`: one of `story_title`, `source_proof`, `entity_intro`,
  `product_demo`, `metric_explainer`, `process_explainer`, `comparison`,
  `context_media`, `transition`, or `takeaway`
- `preferred_asset_types`: values chosen from `source_page`, `product_ui`,
  `logo`, `photo`, `video`, `chart`, `diagram`, or `kinetic_text`
- `must_show`
- `on_screen_text`
- `avoid`

Use only source record keys contained in the assigned story. Intro and closing
beats use an empty source-record list. The role-based suggested words in
`02_payload.md` are soft guidance only. Use as many words and coherent beats as
the story naturally needs, then stop. Never repeat, pad, or add generic commentary
to approach a duration or word count.

The title-card visual is anchored to the first beat of each story and narration
continues underneath it. Make that first beat a short natural transition,
then put the story explanation in the remaining beats. Do not write a silent
title slide or a spoken section heading. No markdown inside narration, timing labels, citations appendix,
internal IDs, or visual directions in narration_text.

[METADATA]
title_options:
- ...
thumbnail_text_options:
- ...
description_intro:
...
tags:
- ...
external_context_used:
- ...
```

The `[SCRIPT]` block is the only text that will be sent to voiceover. Keep it
natural, clean, and ready to read aloud.
