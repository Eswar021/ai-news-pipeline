# Pipeline Handoffs

Standalone JSON/dict adapters for manual or external workflows.

- `chatgpt_exporter`: produces paste-ready instruction and payload files.
- `chatgpt_script_parser`: validates explicit story beats, or normalizes marked
  prose into the canonical section/beat/title/audio-plan contract with
  content-driven length.
- `chatgpt_visual_plan_parser`: retimes manual scenes from authoritative aligned
  beat orders, inserts deterministic moving story titles, splits overlong
  scenes, and validates the canonical planner contract.
- `publish_handoff`: validates finalized metadata and matching script,
  voiceover, visual, and final-video lineage before creating a human review document.

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
