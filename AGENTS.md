# AI Content Creation — Engineering Instructions

The standing contract for work in this repository. Keep it short and current;
delete guidance that stops being true.

## Architecture

`src/pipeline/` is the only active pipeline. Its shape:

```text
src/pipeline/
├── ingestion/news_collection/          # pluggable collectors (config-selected)
├── content/                            # evidence_prep, editorial_triage,
│                                       # story_mapping, editorial_selection,
│                                       # video_packaging, script_generation,
│                                       # metadata_creator
├── voiceover/                          # TTS (Gemini/OpenAI); .venv-voiceover subprocess
├── publishing/metadata_finalizer/      # audio-timed metadata
├── orchestration/                      # runner + per-stage routers + persistence
├── contracts/                          # provenance / fingerprints
└── config/                             # workbench.yaml, environments/, profiles/
```

The visual layer is **`video_engine/`** (Node/HyperFrames motion-graphics), a
self-contained tool triggered only by `orchestration/stages/visuals.py`. It has
no dependency on pipeline internals — its input is the selected voiceover package
+ audio, so it stays portable to other projects.

The run desk UI is **`ui/`** (React frontend + FastAPI inspector backend +
controller). The controller launches the runner; modules never import it.

Production automation is one thin CLI router with four stages:

```text
orchestration/runner.py + stages/{ingestion,content,voiceover,visuals}.py
```

The runner owns sequencing, paths, resumability, run state, and logging, and
calls existing `run(input_json)` boundaries — never an app's private internals.
Run the runner with the main project Python; `.venv-voiceover` is a synthesis
runtime the voiceover stage invokes internally.

## Application Contract

Every functional app exposes one boundary:

```python
def run(input_json: dict) -> dict:
    ...
```

- dict-in / dict-out only at the core boundary; validate with Pydantic v2
- return one envelope with `status`, `data`, `summary`, `handoff`; add `llm_calls` when an LLM is used
- keep app-specific config, prompts, contracts, helpers inside the app
- do not import orchestration logging/telemetry, or another app's private implementation
- keep file I/O, CLI parsing, and output paths in the stage routers, not the app
- carry forward the source context the next app needs; do not read older sibling outputs
- fail clearly when required input, config, prompts, or provider settings are missing

Media modules (voiceover WAV, video MP4) may write files as their product; their
control boundary is still dict-in / dict-out.

## Config Policy

Behavior must be config-driven — never hardcode company names, titles,
thresholds, model names, prompt versions, source caps, output paths, or editorial
rules. If a value changes behavior, it belongs in config or the input contract.

- `config/workbench.yaml` is the profile manifest; module config lives under `config/profiles/{profile}/{stage}/`
- `config/environments/{dev|staging|prod}.yaml` are **sparse overlays** — never duplicate full profile trees per environment
- the runner loads each module's current YAML immediately before execution and writes the effective config to `config_snapshot.json`; `--config-mode frozen` reproduces the run's initial profile
- content apps receive effective config in the input envelope; they do not read YAML directly
- no silent fallbacks: a deliberate fallback must be named in config and visible in the summary

## Output Layout

```text
output/runs/{run_id}/
├── run_context.json
├── {each module}/            # input envelope, result, primary package, summary, config_snapshot, llm_calls.jsonl
├── orchestration/            # run_state.json, {stage}_stage_result.json, voiceover_selection.json, logs/
├── voiceover/ visuals/
```

Do not commit generated media or machine-specific absolute paths.

## Data Flow

```text
raw records → prepared records (+ reversible decision ledgers)
  → editorial triage (advance/reserve/quarantine)
  → semantically mapped stories (carrying full records)
  → LLM-selected roundup slate → structural video packet
  → section-aware script package → metadata draft + beat-aware voiceover
  → audio-timed metadata + rendered episode (video_engine)
```

Script generation receives the full selected story records (no fact-packet layer).

## LLM Policy

Use LLMs for semantic judgment and code for stable guardrails.

- **LLM:** candidate relevance/triage, story identity + editorial value, slate
  selection/ordering, episode direction + beat writing + bounded repair + bookends,
  viewer-facing metadata, visual direction (the art-director).
- **Deterministic:** collection/normalization, provenance + fingerprints, format
  routing + caps after semantic choices, section order + observed timing +
  audiovisual alignment, Pydantic validation, asset resolution + render + assembly.

Do not turn categorical script judgments into code gates. Engagement, tone, hook
quality, humor, and prose quality belong to the LLM reviewer and human review;
code may validate structure, identity, source ownership, projections, provenance,
and bounded loops — never approve/reject prose with keyword lists or regexes.

Use LangChain structured output with Pydantic where an LLM must return structure.
Keep `llm_client.py` to provider/model construction; prompt text lives in versioned
files. Review/revision loops need a config-driven hard maximum — never unbounded.

## Script Contract

Explicit sections: intro, one per selected story, then closing. Each section
carries stable audiovisual beats; `section.narration_text` and `full_script` are
deterministic projections. Preserve section/story/beat IDs outside spoken prose so
voiceover and visuals never reconstruct boundaries from text. Word/beat counts and
nominal duration are telemetry, not approval quotas — synthesized voiceover timing
is authoritative. Every canonical script carries a content fingerprint that
downstream stages propagate and verify; never select artifacts by modification time.

## Verification

```bash
python3 -B -m compileall src/pipeline
python3 -m pytest -q
cd ui/frontend && npm run typecheck && npm run build && npm run test:browser
```

For quality-affecting changes (reasoning effort, prompt/grouping edits), do a
**before/after A/B on 1-2 real runs** and confirm quality is preserved before
committing — never trade quality for speed/cost unverified.

## Clarify Before

Ask before changing invocation, output ownership, deletion behavior, provider
cost, or a public contract when the choice can't be determined from code +
instructions. Don't build compatibility layers for an assumption not requested.
