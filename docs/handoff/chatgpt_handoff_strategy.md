# ChatGPT Handoff Strategy

This note describes the rebuilt pipeline handoff exporter.

The exporter is a helper tool, not a pipeline layer. It does not change `L0-L9`
contracts and it does not write into layer folders.

## Commands

```bash
python3 -m src.chatgpt_exporter --run-id current
python3 -m src.chatgpt_exporter --run-id current --profile script_review
python3 chatgpt_export.py --run-id current --profile publish_review
```

The root `chatgpt_export.py` command delegates to the rebuild exporter when the
run exists under `output/`. Legacy `data/runs/` exports remain reference-only.

## Output

Each export writes:

```text
output/chatgpt_handoffs/{run_id}/{profile}/01_instructions.md
output/chatgpt_handoffs/{run_id}/{profile}/02_payload.md
output/chatgpt_handoffs/{run_id}/{profile}/03_manifest_context.md
```

Use:
- `01_instructions.md` first
- `02_payload.md` second
- `03_manifest_context.md` only when ChatGPT needs full run/config context

## Profiles

`auto` picks the highest completed rebuild artifact in this order:

1. `publish_review` from `L8/verification_package.json`
2. `script_review` from `L7/script_package.json`
3. `content_packet` from `L6/content_packet.json`
4. `editorial_brief` from `L5/selected_video_brief.json`
5. `fact_packet` from `L4/fact_packets.json`
6. `story_map` from `L3/stories.json`

Explicit profiles:

- `story_map`: review story candidates after clustering/ranking
- `fact_packet`: review grounded facts and evidence strength
- `editorial_brief`: review selected story set and video angle
- `content_packet`: hand off production packet before script generation
- `script_review`: review generated script package
- `publish_review`: review verified final publish package

Legacy aliases are accepted where useful:
- `after_layer_3` -> `story_map`
- `after_layer_4` -> `fact_packet`
- `after_layer_6` -> `content_packet`

## Prompt Source

Exporter prompt text lives in:

```text
prompts/v1/chatgpt_exporter/
```

The exporter combines:
- `base.md`
- the selected profile prompt
- dynamic manifest/run context
- the selected layer artifact
- available layer summaries

## Design Rules

- Read `run_manifest.json` and the selected profile artifact.
- Include manifest context so ChatGPT sees run profile, source groups, channel,
  target format, model/prompt choices, timing, and caps.
- Do not make ChatGPT infer pipeline configuration from old files.
- Do not add unsupported facts in prompts.
- Preserve caution labels and evidence boundaries.
- Keep this as an export helper, not a new pipeline layer.
