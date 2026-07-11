Profile: content_packet

Use this handoff as a production-ready content packet.

Your job:
- Write the final spoken narration for the selected video packet.
- Return a paste-friendly response that the pipeline can parse.
- Preserve required facts, cautious facts, source attribution, and blocked angles.
- Keep the target format, target duration, roles, and timing from the packet unless asked otherwise.
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
Use one explicit marker before every script section:
`[[SECTION:<section_id>]]`

Use the exact section IDs and order implied by the video packet: intro first,
one section per selected story in `video_segment.segment_order`, then closing.
The parser removes these markers before voice generation.

After each marker, include only final spoken narration text for that section.
No markdown headings.
No timing labels.
No bold markers.
No visual directions.
No citations list.
No source appendix.

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
