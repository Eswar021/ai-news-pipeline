# Roundup Script Generation

This app is the canonical script writer for the active `roundup` format.

```python
from src.pipeline.apps.script_generation.formats.roundup import run

result = run(input_json)
```

## Generation Flow

```text
video_packet
  -> editor-selected story order and role guidance
  -> one semantic source-research pass per story over complete records
  -> shared versioned story-context packets with full records and semantic reading notes
  -> creator-led roundup director and per-story engines
  -> parallel story-local storytellers
  -> bounded story-local quality reviews
  -> bookend/continuity writer
  -> bounded bookend quality review
  -> deterministic section, beat, full-script, and audio-plan assembly
```

No LLM call writes or rewrites the complete episode. Once a story body is
accepted, later calls cannot replace it. The bookend writer receives the final
story narration and may write only the intro, short spoken connectors,
moving-title copy, and conclusion.

The root `provider` and `model` remain the default for every script role.
`llm_roles` can override individual roles without moving high-volume research
or structural calls to a slower creative model. The current production profile
uses Kimi K3 only for `story_writer` and `story_reviewer`; source research,
episode direction, bookends, and bookend review remain on GPT-4o. The reviewer
shares the writer's model because an accepted review revision becomes the
canonical story body.

## Canonical Units

`sections[].beats` are authoritative. Every beat carries:

- stable `beat_id`, `beat_order`, `beat_type`, and `story_id`
- an editorial `beat_function`, optional `creative_device`, and `visual_goal`
- spoken `narration_text`
- invisible support truth IDs and source record keys used by that beat
- a typed visual brief describing the viewer-facing visual purpose

`section.narration_text` and `full_script` are deterministic projections of
those beats. `audio_plan.units` defines one synthesis unit for the intro, each
story, and the closing. Story sections also contain a title-card contract whose
`voice_behavior` is `continue`.

## Guardrails

- selected-story order is preserved from the video packet
- the director receives every complete story packet, and each story-local
  writer and reviewer receives the same complete packet
- semantic source briefs add reading notes without replacing
  or truncating the records
- semantic source briefs carry explicit meaning boundaries for current versus
  planned state, source attribution, claim strength, and terminology such as
  open-weight versus open-source
- source keys outside that story fail validation
- truth IDs outside that story fail validation; attaching every available truth
  ID is not a coverage quota
- truth details, quotes, metrics, and interpretations are selected semantically
  by the source researcher; code validates only record ownership and stable IDs
- code never compares an LLM source note, quote, or metric against article text
- regex metric extraction, lexical sentence classification, and stage-specific
  truth truncation are not used in the creative prompt boundary
- configured context limits are resource guards: an oversized complete packet
  fails clearly rather than being silently shortened
- truth items preserve source name and relationship; self-published and
  community-launch context remains visible to the LLM
- engagement, tone, hook quality, claim interpretation, attribution style,
  humor, and prose quality are LLM and human editorial judgments, not regex or
  semantic-overlap approval gates
- role-specific word suggestions are prompt guidance only, never approval gates
- writers use as many coherent audiovisual beats as the story naturally needs
- prompts guide one visual thought per beat and usually one or two spoken
  sentences, but beat duration and count are not deterministic quotas
- short complete stories are accepted; writers must not pad them with filler
- measured word counts and estimated duration remain visible as diagnostics
- review loops have a strict maximum of one
- transient provider rate limits, service errors, and structured-output parsing
  retry only the failed LLM call under the bounded `llm_retry` policy
- reviewers may explicitly keep a good draft with no replacement revision
- a proposed rewrite is eligible only when it validates and names supplied
  review beat IDs; code does not compare its prose or require an exact textual
  difference in a named beat
- a structurally valid reviewer revision is applied directly after the reviewer
  has made its bounded semantic `rewrite_required` decision; there is no second
  candidate selector or hidden code-based prose comparison
- code does not reject generated prose based on corporate-language lists,
  metric matching, qualifiers, claim-strength words, source-order similarity,
  or inferred claim states
- Pydantic shape, story/source ownership, known IDs, canonical order,
  non-empty narration, and artifact provenance remain hard checks
- title connectors are short enough to remain moving transitions
- internal pipeline IDs are forbidden in spoken narration; visual-direction separation is owned by the structured beat contract and writing prompts rather than phrase matching
- actual voiceover timing, not nominal script duration, drives visual planning

All prompt text is versioned below `prompts/`. `llm_client.py` only constructs
providers, and `llm_logging.py` records calls in the returned envelope. Prompt
bundles are sent as real system and user chat messages rather than flattened
into one user message. OpenAI and Moonshot calls use strict Pydantic structured
output. The structured-output transport is config-driven: production OpenAI
and Kimi K3 use JSON Schema, while Kimi K2.6 comparisons may use forced function
calling because that model follows complex nested schemas more reliably through
its tool interface. Every schema field is required, with empty lists used
explicitly when a category has no values.

Moonshot experiments are fully config-driven through `provider`, `model`,
`provider_options`, and `structured_output`. Kimi K2.6 requires temperature
`0.6`; use `thinking: disabled` for its non-thinking mode. Kimi K3's mandatory
thinking mode is incompatible with forced tool choice, so its comparison uses
JSON Schema instead. `provider_options.request_timeout_seconds` places a hard
bound on any individual OpenAI-compatible request.

Production routing is role-specific. GPT-4o remains responsible for source
research and episode direction; Kimi K3 owns story writing/review and bookend
writing/review. `worker_count: 2` runs two independent story pipelines in
parallel while preserving deterministic output order. Metadata uses its own
single Kimi K3 call in `apps/metadata_creator`; code still owns timestamps,
source URLs, and section identity.

## Model Comparison

Model experiments are declared under `experiments.script_model_comparison` in
`src/pipeline/config/workbench.yaml`. Run them against an existing frozen input
without changing production artifacts:

```bash
python3 -B -m src.pipeline.orchestration.script_model_comparison \
  --input output/runs/{RUN_ID}/script_generation/script_generation_input.json \
  --output-dir output/labs/script_model_comparison/{EXPERIMENT_ID} \
  --variant moonshot_kimi_k26_non_thinking
```

The runner records status, latency, token usage, cache reads, reasoning tokens,
route-specific estimated cost, call logs, and the generated script under the
isolated lab directory. Mixed-provider variants declare `pricing_by_route` so
OpenAI and Moonshot usage is not priced as one model. A model should move into a
production profile only after the same frozen packet passes its full structured
workflow and human script review.
