# Media And Handoff Modules

Handoffs, voiceover, and visuals live parallel to pure `apps/` because they
either adapt an external/manual workflow or produce media files. They retain an
app-like JSON/dict control boundary.

## Handoffs

Location:

```text
src/pipeline/handoffs/
```

Responsibilities:

- export self-contained ChatGPT packets
- parse manually pasted script responses
- parse manually pasted visual plans
- prepare publish-review packages

The exporter returns files in memory. The handoff notebook decides where those
files are written.

Manual script responses are normalized by `chatgpt_script_parser` into the same
contract as `apps/script_generation`. Preferred script responses include exact
`[[SECTION:<section_id>]]` markers. The parser removes markers from narration
while retaining intro/story/closing boundaries for metadata and visuals.

Manual visual responses are normalized by `chatgpt_visual_plan_parser` into the
same envelope as `visuals.planner`. The parser validates scene kinds, selected
source references, timing coverage, and render caps before assets are resolved.

Operator notebook:

```text
notebooks/handoffs/chatgpt_handoffs.ipynb
```

## Voiceover

Location:

```text
src/pipeline/voiceover/
```

Boundary:

```python
def run(input_json: dict) -> dict:
    ...
```

Voiceover is allowed to write media because WAV files are its core product. The
caller provides `config.output_dir`. The module writes full audio, optional
chunks, package JSON, and summary JSON.

The default provider is free local Kokoro. Chatterbox, F5-TTS, and Dia adapters
remain available for experiments. Provider, voice, style, speed, pauses, chunk
size, and sample rate are config-driven. Model caches live under
`.cache/ai_content_creation/models/`.

Python 3.12 voice dependencies are isolated in `.venv-voiceover`; the notebook
invokes the CLI adapter with that interpreter.

Operator notebook:

```text
notebooks/production/voiceover_generation.ipynb
```

## Visuals

Location:

```text
src/pipeline/visuals/
├── planner/
├── media_discovery/
├── asset_resolver/
├── generators/
├── remotion_engine/
├── render/
└── assembly/
```

### Planner

The planner is semantic and LLM-assisted. It receives the selected video
packet, canonical script, optional voiceover timing, visual capability registry,
and scene policy. It returns a validated continuous scene timeline.

Planning and rendering are separate. A planner does not download images,
capture pages, or invoke Remotion.

### Media Discovery

Media discovery handles requested contextual images and B-roll. It records the
provider, source URL, license/attribution metadata, local file, ranking, and
fallback reason. It must not silently treat unrelated stock footage as a match.

### Asset Resolver

Asset resolution obtains concrete assets for a validated scene plan:

- article screenshots through Playwright
- brand marks through local overrides, Simple Icons, favicon, then text fallback
- media files selected by media discovery
- no external asset for code-generated motion scenes

### Remotion Rendering

Remotion components receive validated scene JSON. Scenes render independently,
may run in parallel, and are bounded by a render-side duration cap. A failed
scene can be retried without rendering the entire episode.

### Assembly

Assembly orders rendered clips, creates a continuous video track, attaches the
original voiceover, and validates final duration. It does not regenerate
planning or media.

Operator and lab notebooks:

```text
notebooks/production/visual_production.ipynb
notebooks/labs/visual_assets_lab.ipynb
```

## Output Layout

```text
output/runs/{run_id}/
├── voiceover/{variant}/
└── visuals/
    ├── planning/{source}/
    ├── media_discovery/
    ├── asset_resolution/
    ├── render/
    └── assembly/
```

Reference smoke outputs use:

```text
output/tests/media_roundup_reference/
```

## Change Checklist

Before changing media code:

- read the module contract and actual implementation
- check the frozen config fields used by its notebook
- preserve JSON compatibility between generated and manual paths
- compile Python and type-check Remotion
- run focused fixture tests
- inspect actual rendered frames or clips for visual changes
- keep generated media out of Git
