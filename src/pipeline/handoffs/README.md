# Pipeline Handoffs

Standalone JSON/dict adapters for manual or external workflows.

- `chatgpt_exporter`: produces paste-ready instruction and payload files.
- `chatgpt_script_parser`: converts a manual ChatGPT response into the canonical script contract.
- `chatgpt_visual_plan_parser`: validates a manual visual plan into the canonical planner contract.
- `publish_handoff`: creates a human publishing-review document from current content and media envelopes.

Core modules return files in memory. Notebooks or CLIs own file writing.

```bash
python3 -m src.pipeline.handoffs.chatgpt_exporter.cli \
  --input-json output/runs/.../handoffs/chatgpt/script/handoff_input.json \
  --output-dir output/runs/.../handoffs/chatgpt/script/packet

python3 -m src.pipeline.handoffs.chatgpt_script_parser.cli \
  --input-json output/runs/.../inputs/chatgpt_script_parse.json \
  --output-json output/runs/.../script_generation/chatgpt/script_generation_result.json

python3 -m src.pipeline.handoffs.chatgpt_visual_plan_parser.cli \
  --input-json output/runs/.../inputs/chatgpt_visual_plan_parse.json
```

The preferred operator surface is `notebooks/handoffs/chatgpt_handoffs.ipynb`.
