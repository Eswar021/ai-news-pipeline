# Media Roundup Reference Fixture

This fixture is the deterministic smoke input for voiceover, visual asset
resolution, scene rendering, and final video assembly.

It deliberately uses no live LLM calls, screenshots, stock-media searches, or
remote image downloads. The episode explains the pipeline itself and exercises
several code-generated motion families.

Files:

- `video_packaging_result.json`: canonical selected-story packet.
- `chatgpt_response.txt`: manual handoff response with explicit section markers.
- `script_generation_result.json`: canonical parsed script envelope with five
  sections, twelve audiovisual beats, moving-title anchors, and five audio
  units. Its length is content-driven; reported words and duration are
  observational telemetry rather than approval targets. It also carries the
  deterministic script fingerprint required by production media stages.
- `full_script.txt`: narration-only convenience copy.
- `visual_scene_planning_result.json`: curated planner-compatible scene plan.

Generated WAV, MP4, manifests, and summaries belong under
`output/tests/media_roundup_reference/` and are not committed.

The fixture is test-adapter data, not a production-code mode. Production apps
never branch on fixture IDs. Contract and media regressions can therefore run
without collection, LLM, hosted TTS, or external-media calls:

```bash
python3 -m pytest -q \
  tests/test_media_reference_contracts.py \
  tests/test_roundup_story_beat_pipeline.py
```

For visual styling against a real completed episode, prefer runner artifact
replay (`--from-module visual_render --stop-after visual_render`) so the exact
saved plan and resolved assets are exercised without repeating upstream work.
