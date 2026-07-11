# Pipeline v2 Handoffs

Standalone utility modules for export/review handoffs.

These modules follow the v2 app pattern:

```python
def run(input_json: dict) -> dict:
    ...
```

The app core accepts JSON/dict input and returns JSON/dict output. CLI adapters
may load run artifacts from disk and write Markdown files, but the core modules
do not depend on `src.pipeline.*`, `src.config.paths`, or global path constants.

## ChatGPT Exporter

```bash
python3 -m src.pipeline_v2.handoffs.chatgpt_exporter.cli --run-id current
python3 -m src.pipeline_v2.handoffs.chatgpt_exporter.cli --run-id current --profile script_review
```

The exporter also supports `--profile visual_scene_plan` when the caller
provides a v2 visual-planning packet in `input.artifacts.visual_scene_plan`.
That packet should include the final script, selected video packet, optional
voiceover timing, scene policy, and visual capability registry.

## ChatGPT Visual Plan Parser

```bash
python3 -m src.pipeline_v2.handoffs.chatgpt_visual_plan_parser.cli --input-json output_v2/.../chatgpt_visual_plan_parse_input.json
```

Use this after ChatGPT returns a `CHATGPT_VISUAL_PLAN_RESPONSE_V1` response.
The parser extracts `[VISUAL_SCENE_PLAN_JSON]`, validates scene timing,
supported render kinds, selected-story source URLs/record keys, and emits the
same `visual_scene_planning` envelope that `visuals.asset_resolver` expects.

## Publish Handoff

```bash
python3 -m src.pipeline_v2.handoffs.publish_handoff.cli --run-id current
```
