# Creator Voice Benchmark

This compact deterministic fixture freezes the Phase 0 writing benchmark. It
is intentionally small enough to read during code review and does not require
an API call.

- `story.json` contains one selected story whose useful details live in the
  full record content, not only the title and summary.
- `baseline_scripts.json` records a deliberately weak article-readout version
  and a creator-led reference version with human rubric scores.
- `regression_cases.json` preserves examples of a harmful review rewrite and
  semantically unrelated visual choices found during the reference-run audit.

The reference scores are calibration labels, not automated claims that one
script is universally good. Prompt or model variants should be compared
blindly by a human using `docs/build/creator_voice_storytelling_rubric.md`.
