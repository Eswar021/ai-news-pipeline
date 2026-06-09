Profile: content_packet

Use this handoff as a production-ready content packet.

Your job:
- Write the final spoken narration for the selected video packet.
- Return a paste-friendly response that the pipeline can parse.
- Preserve required facts, cautious facts, source attribution, and blocked angles.
- Keep the target format, target duration, roles, and timing from the packet unless asked otherwise.
- Do not add unsupported facts.

Focus on:
- segment flow
- transitions
- required facts
- optional context
- caution language
- source usage
- what L7 should say clearly and what it must avoid

Return exactly this top-level section format:

```text
CHATGPT_PIPELINE_RESPONSE_V1

[NOTES]
Short notes for the human operator. These are not spoken.

[SCRIPT]
Only final spoken narration text.
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
```

The `[SCRIPT]` block is the only text that will be sent to voiceover. Keep it
natural, clean, and ready to read aloud.
