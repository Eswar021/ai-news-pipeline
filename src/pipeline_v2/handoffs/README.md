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

## Publish Handoff

```bash
python3 -m src.pipeline_v2.handoffs.publish_handoff.cli --run-id current
```
