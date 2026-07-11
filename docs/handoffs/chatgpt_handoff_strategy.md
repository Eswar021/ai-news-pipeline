# ChatGPT Handoff Strategy

The ChatGPT handoff is an optional manual production route, not a separate
pipeline. It uses the same downstream contracts as native LLM applications.

Operator notebook:

```text
notebooks/handoffs/chatgpt_handoffs.ipynb
```

## Script Handoff

1. Load a completed `video_packaging_result.json`.
2. Export the content packet through `handoffs.chatgpt_exporter`.
3. Paste the generated instruction and payload files into ChatGPT.
4. Paste the complete response into the notebook-provided response file.
5. Parse it with `handoffs.chatgpt_script_parser`.

The response wrapper is:

```text
CHATGPT_PIPELINE_RESPONSE_V1

[NOTES]
...

[SCRIPT]
[[SECTION:section_00_intro]]
spoken narration

[[SECTION:section_01_story_id]]
spoken narration

[[SECTION:section_99_closing]]
spoken narration

[METADATA]
...
```

The parser returns a canonical `script_generation_result` containing full
narration, explicit sections, timing estimates, source/story keys, summary, and
`ready_for_metadata_creation` handoff. Voiceover and visuals consume this result
without a manual-only schema.

Legacy plain `[SCRIPT]` responses remain accepted. The parser partitions them
by paragraph and timing weight, but emits a warning because story boundaries
are inferred.

## Visual Planning Handoff

Run voiceover before exporting the visual packet. The exporter includes:

- canonical script sections and full text
- exact voiceover chunk timing
- selected stories and compact records
- visual scene policy
- configured visual capabilities
- response schema and prohibited card types

ChatGPT returns `CHATGPT_VISUAL_PLAN_RESPONSE_V1` with a
`[VISUAL_SCENE_PLAN_JSON]` object. The parser validates and repairs only safe
source references, rejects unsupported scene kinds, closes timeline gaps, and
returns the canonical visual planner envelope.

The visual production notebook can then use:

```python
VISUAL_PLAN_SOURCE = "chatgpt"
```

## Rules

- Treat selected records and script as the production context.
- External context must be disclosed in notes and must not silently replace the selected story.
- Keep internal section/story IDs out of spoken narration.
- Do not bypass parser validation by writing directly into renderer inputs.
- Keep handoff file writing in the notebook, not the exporter core.
- Preserve manual responses and parse inputs under the run directory for reproducibility.
