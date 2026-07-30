Profile: content_packet

Use this handoff as a production-ready content packet.

Your job:
- Write the final spoken narration for the selected video packet.
- Return a paste-friendly response that the pipeline can parse.
- Preserve required facts, cautious facts, source attribution, and blocked angles.
- Keep the target format, selected story order, and roles from the packet.
- Make the narration feel like a strong YouTube video, not a technical report.
- Give every story a mini-arc built around tension, surprise, a practical
  consequence, a mechanism, or another specific story engine.
- Use selected source facts as storytelling material rather than following the
  records in source order or trying to mention every available detail.
- Write with the voice of a curious technical friend with a skeptical eyebrow:
  concrete, energetic but not frantic, and willing to offer a useful opinion.
- Add fitting analogy, contrast, reaction, or restrained humor when it improves
  clarity. Never fabricate personal experience or let a joke create a factual
  accusation.
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

Avoid press-release language such as "pivotal," "groundbreaking,"
"indispensable," "game-changing," and generic claims about reshaping the
technology landscape. Stop each story when its viewer payoff is complete.

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
- `beats`, a list of objects with `beat_type`, `beat_function`,
  `narration_text`, `source_record_keys`, `creative_device`, and
  `delivery_direction`

Use `beat_function` values from `story_hook`, `setup`, `reveal`, `explanation`,
`example`, `reaction`, `comic_release`, `consequence`, `caveat`, `payoff`, and
`bridge`. Use `creative_device` values from `none`, `analogy`, `contrast`,
`rhetorical_question`, `hypothetical`, `observational_humor`,
`self_aware_humor`, and `callback`. Intro and closing beats may omit
`beat_function`; the parser assigns their canonical bookend functions.

Each `delivery_direction` is silent performance metadata and must contain:
- `performance_intent`: a concise director note for how the beat should land
- `emotional_color`: a natural description such as curious, lightly amused,
  skeptical, urgent, or reflective
- `pace`: `deliberate`, `measured`, `conversational`, `brisk`, or `rapid`
- `energy`: `restrained`, `warm`, `engaged`, `animated`, or `punchy`
- `emphasis_phrases`: exact phrases from this beat's narration, or an empty list
- `pause_after`: `none`, `micro`, `short`, or `full_beat`

Do not put bracketed acting tags in `narration_text`. Vary performance across
beats rather than making the whole episode fast or enthusiastic.

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
