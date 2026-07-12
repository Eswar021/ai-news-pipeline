# Roundup Script Generation

This app is the canonical script writer for the active `roundup` format.

```python
from src.pipeline.apps.script_generation.formats.roundup import run

result = run(input_json)
```

## Generation Flow

```text
video_packet
  -> deterministic story order and soft role guidance
  -> roundup director
  -> parallel story-local writers
  -> bounded story-local quality reviews
  -> bookend/continuity writer
  -> bounded bookend quality review
  -> deterministic section, beat, full-script, and audio-plan assembly
```

No LLM call writes or rewrites the complete episode. Once a story body passes
its gate, later calls cannot replace it. The bookend writer receives compact
final story summaries and may write only the intro, short spoken connectors,
moving-title copy, and conclusion.

## Canonical Units

`sections[].beats` are authoritative. Every beat carries:

- stable `beat_id`, `beat_order`, `beat_type`, and `story_id`
- spoken `narration_text`
- source record keys used by that beat
- a typed visual brief describing the viewer-facing visual purpose

`section.narration_text` and `full_script` are deterministic projections of
those beats. `audio_plan.units` defines one synthesis unit for the intro, each
story, and the closing. Story sections also contain a title-card contract whose
`voice_behavior` is `continue`.

## Guardrails

- selected-story order is preserved from the video packet
- a story writer receives only its own full records
- source keys outside that story fail validation
- role-specific word suggestions are prompt guidance only, never approval gates
- writers use as many coherent audiovisual beats as the story naturally needs
- short complete stories are accepted; writers must not pad them with filler
- measured word counts and estimated duration remain visible as diagnostics
- review loops have a strict maximum of two, with one as the default
- transient provider rate limits and service errors retry only the failed LLM
  call under the bounded `llm_retry` policy; validation errors are not retried
- a review candidate is applied only when the model recommends a material
  editorial improvement and it passes structural/source guardrails
- title connectors are short enough to remain moving transitions
- visual directions and internal IDs are forbidden in spoken narration
- actual voiceover timing, not nominal script duration, drives visual planning

All prompt text is versioned below `prompts/`. `llm_client.py` only constructs
providers, and `llm_logging.py` records calls in the returned envelope. OpenAI
calls use strict Pydantic structured output; every schema field is required,
with empty lists used explicitly when a category has no values.
