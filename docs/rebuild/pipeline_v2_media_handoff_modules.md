# Pipeline v2 Media And Handoff Modules

This document is a directional map for v2 modules that are not pure `apps/`.
It does not replace reading the actual code before making changes.

Read this when working on:

- `src/pipeline_v2/handoffs/`
- `src/pipeline_v2/voiceover/`
- `src/pipeline_v2/visuals/`
- `notebooks/v2_chatgpt_voiceover_workbench.ipynb`

## Shared Principle

These modules still follow the v2 app-like contract:

```python
def run(input_json: dict) -> dict:
    ...
```

They differ from pure apps because their job may require writing files:

- handoffs write operator-facing Markdown or review files
- voiceover writes WAV files and audio manifests
- visuals write screenshots, logos, scene clips, and final review MP4 files

The caller must provide output paths through config. Do not make these modules
read global path constants or current-manifest files.

## Handoffs

Location:

```text
src/pipeline_v2/handoffs/
```

Purpose:

- export structured pipeline context for a human or external tool
- create manual ChatGPT review/script packets
- create publish handoff packages when needed

Important boundaries:

- core modules accept JSON/dict input and return JSON/dict output
- CLI adapters may read/write files
- handoffs should not silently mutate upstream run outputs
- handoffs should not import `src.pipeline.*`

Current important module:

```text
handoffs/chatgpt_exporter/
```

This is used by the ChatGPT-assisted notebook path to create a content packet
after App 4 video packaging. The manual script parser then extracts the saved
ChatGPT response for voiceover and visuals.

Visual planning can also use a ChatGPT handoff:

```text
handoffs/chatgpt_exporter/              # profile: visual_scene_plan
handoffs/chatgpt_visual_plan_parser/    # parse response back to visual_scene_plan
```

The visual handoff packet must include the final script, selected video packet,
optional voiceover timing, scene policy, and visual capability registry. The
parser validates that returned scenes use supported render kinds, do not revive
old card types, and use only selected-story source URLs/record keys for
source-backed scenes. Its output is intentionally shaped like
`visuals.planner.run(...)` so `visuals.asset_resolver` does not care whether the
plan came from the local planner or a manual ChatGPT pass.

## Voiceover

Location:

```text
src/pipeline_v2/voiceover/
```

Purpose:

- turn script text into audio
- write WAV files, chunks, package JSON, and summary JSON
- support local TTS providers through one v2-style entrypoint

Current providers:

- `kokoro_local`: active fast/free long-form workbench default
- `chatterbox_local`: slower expressive comparison option
- `f5_tts_local`: reference-voice style transfer
- `dia_transformers`: expressive dialogue experiments, slow locally

Important boundaries:

- old `src/voiceover/` was removed during cleanup; v2 voiceover is canonical
- provider choice and tuning live in config and input JSON
- the module is allowed to write audio because audio is its output
- provider-specific dependencies stay in `.venv-voiceover`
- main notebook Python may differ from voiceover Python

Primary docs:

```text
src/pipeline_v2/voiceover/README.md
```

## Visuals

Location:

```text
src/pipeline_v2/visuals/
```

Purpose:

- plan motion-first visual scenes from script, selected stories, and voiceover
- resolve external assets such as screenshots and logos
- render Remotion scene clips
- assemble the clips with voiceover into a final review video

Current flow:

```text
planner -> media_discovery -> asset_resolver -> render -> assembly
```

Optional manual planning flow:

```text
chatgpt_exporter(profile=visual_scene_plan) -> ChatGPT -> chatgpt_visual_plan_parser -> media_discovery -> asset_resolver -> render -> assembly
```

Important boundaries:

- the planner is the LLM-heavy stage and returns JSON scene plans only
- planner `asset_manifest.requests` are asset requests, not built assets
- media discovery owns contextual image/b-roll search, candidate ranking,
  downloading, short-clip preparation, and attribution metadata
- remote media providers never run inside the planner or Remotion renderer
- story-level planner failures should be visible before asset resolution; by
  default `allow_deterministic_story_fallbacks=false` blocks fallback plans
- asset resolver is the asset-building stage and writes assets under
  caller-provided `output_v2/visuals/...`
- render writes scene clips
- assembly writes the review MP4
- no central v2 runner exists yet
- notebook cells own orchestration and output folder naming

Primary docs:

```text
src/pipeline_v2/visuals/README.md
docs/rebuild/visuals_roadmap.md
```

## Notebook Relationship

Use:

```text
notebooks/v2_chatgpt_voiceover_workbench.ipynb
```

This notebook resumes from App 4 video packaging and runs:

- ChatGPT handoff export
- manual script parsing
- voiceover generation
- visual planning
- contextual media discovery
- visual asset resolution
- visual scene rendering
- final video assembly

If the notebook fails, debug the stage module first. Avoid adding notebook-only
fixes unless the bug is truly orchestration-specific.

## Change Checklist

Before changing these modules:

- read `docs/rebuild/pipeline_v2_application_architecture.md`
- read the relevant local README
- inspect the actual module code and notebook cell that calls it
- identify whether the change is core behavior, adapter behavior, or notebook orchestration
- keep behavior config-driven through `workbench.yaml` and input envelopes
- update docs when a new provider, scene type, handoff format, or output folder shape is added
