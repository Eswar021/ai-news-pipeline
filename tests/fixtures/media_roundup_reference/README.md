# Media Roundup Reference Fixture

This fixture is the deterministic smoke input for voiceover, visual asset
resolution, scene rendering, and final video assembly.

It deliberately uses no live LLM calls, screenshots, stock-media searches, or
remote image downloads. The episode explains the pipeline itself and exercises
several code-generated motion families.

Files:

- `video_packaging_result.json`: canonical selected-story packet.
- `chatgpt_response.txt`: manual handoff response with explicit section markers.
- `script_generation_result.json`: canonical parsed script envelope.
- `full_script.txt`: narration-only convenience copy.
- `visual_scene_planning_result.json`: curated planner-compatible scene plan.

Generated WAV, MP4, manifests, and summaries belong under
`output/tests/media_roundup_reference/` and are not committed.
