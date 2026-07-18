# Voiceover

`src.pipeline.voiceover` converts a canonical script result or explicit script
text into WAV audio and a timing package.

```python
from src.pipeline.voiceover import run

result = run(input_json)
```

Voiceover writes media because audio is its core product. The caller must
provide `config.output_dir`; the module never chooses a global run folder.

## Inputs

Provide exactly one:

- `input.script_generation`: canonical script-generation envelope
- `input.script_text`: explicit manual text with optional `script_source`

The production notebook requires the canonical envelope so section, story,
beat, visual-brief, and source identity remain available. Explicit
`script_text` is retained only for isolated voice tests and produces an
unaligned manual-text package.

## Providers

- `openai`: hosted `gpt-4o-mini-tts` synthesis with delivery instructions
- `gemini`: hosted Gemini TTS synthesis with delivery instructions
- `kokoro_local`: fast, free local fallback
- `chatterbox_local`: slower expressive local model
- `f5_tts_local`: reference-voice local synthesis
- `dia_transformers`: experimental dialogue-style local synthesis

Provider, model, voice, delivery direction, request concurrency, style, speed,
provider splitting, beat/section pauses, sample
rate, mastering, captions, and provider settings come from the input config.
`llm_client` is not involved.

The default profile in `src/pipeline/config/workbench.yaml` uses OpenAI
`gpt-4o-mini-tts` with `cedar`, `general_youtube`, and speed `1.0`. API keys
remain environment-only. The configured aliases are:

- OpenAI: `OPENAI_API_KEY`, then `OPENAI_API_KEY_A_C_C`
- Gemini: `GEMINI_TTS_API_KEY`, then `GEMINI_API_KEY`, then `GOOGLE_API_KEY`

Use `GEMINI_TTS_API_KEY` for a dedicated billed speech project. This keeps
voice experiments isolated from Gemini keys used elsewhere in the content
pipeline. The key remains in `.env`; it is never placed in YAML or output
manifests.

Select a provider by changing `voiceover.provider`. Change hosted model, voice,
performance direction, retry behavior, and concurrency in the matching
`voiceover.openai` or `voiceover.gemini` block. To return to free local speech,
set `provider: kokoro_local`; its voice lives in `voiceover.kokoro.voice`.
Top-level `voice` remains a backward-compatible override for local providers;
hosted providers use their provider-local voice field.

Gemini TTS Preview can have very low free-tier request quotas. The project
therefore keeps its default Gemini worker count at `1`; raise it only after the
API project has a paid quota that supports the episode's beat-level call count.
OpenAI currently labels `gpt-4o-mini-tts` deprecated, although it remains
available and passed the production smoke. Treat it as the immediate
cost/quality comparison baseline, not a permanent provider lock.

Authoring YAML affects new runs. Existing runs keep their frozen profile, so
use an explicit stage override when comparing providers against the same
script:

```bash
python3 -m src.pipeline.orchestration.runner voiceover \
  --run-id current \
  --script-source app \
  --config-overrides-json '{"provider":"gemini","gemini":{"model":"gemini-2.5-flash-preview-tts","voice":"Kore"}}'
```

Provider/model/voice/delivery settings are part of the generated variant name
and artifact fingerprint. A config change therefore creates a new voiceover
variant instead of reusing stale audio.

## Short Delivery Comparisons

Do not synthesize a complete episode while choosing a hosted voice or delivery
direction. The delivery-comparison command takes the first configured beat from
an explicit script section and renders the same short text for every selected
config-driven variant:

```bash
.venv-voiceover/bin/python -m src.pipeline.voiceover.delivery_comparison \
  --script-result output/runs/{run_id}/script_generation/script_generation_result.json \
  --output-dir output/labs/voiceover_delivery_comparison/{run_id}
```

Comparison variants live under `experiments.voiceover_delivery_comparison` in
`workbench.yaml`. Use repeated `--variant` arguments to render only particular
profiles; without them, only `default_variant_ids` are rendered. This keeps
optional free-tier Gemini comparisons from silently adding requests to the
default OpenAI comparison. Easy-to-play WAV files are written to `samples/`, while
`comparison_manifest.json` records the exact model, voice, speed, instructions,
duration, and source beat used for each sample. This command intentionally runs
inside `.venv-voiceover`; unlike the production orchestration runner, it is a
focused synthesis adapter rather than a stage router.

For a systematic voice-by-direction comparison, run a named matrix. The Gemini
matrix deliberately spaces request starts according to the configured free-tier
limit and stops if the provider reports exhausted quota:

```bash
.venv-voiceover/bin/python -m src.pipeline.voiceover.delivery_comparison \
  --script-result output/runs/{run_id}/script_generation/script_generation_result.json \
  --output-dir output/labs/voiceover_delivery_comparison/{run_id}_gemini_matrix \
  --matrix gemini31_creator_matrix \
  --resume
```

Matrix runs additionally write `comparison_summary.md` and
`comparison_summary.csv` for quick listening and settings review, plus
`comparison_playlist.m3u8` for continuous playback in table order. `--resume`
reuses successful WAV files from the same output directory and requests only
missing or failed combinations, which is essential for free-tier daily quotas.
The comparison manifest also records measured words per minute and a pricing
estimate. `max_projected_cost_usd` prevents an accidentally broad matrix from
starting, and a checkpoint is written after each successful request so a paid
run can be resumed safely.

The research suite includes all 30 official voices on one identical fast
creator direction, two additional fast deliveries for a focused eight-voice
shortlist, and small Gemini 2.5 Flash/Pro model comparisons:

```bash
.venv-voiceover/bin/python -m src.pipeline.voiceover.delivery_comparison \
  --script-result output/runs/{run_id}/script_generation/script_generation_result.json \
  --output-dir output/labs/voiceover_delivery_comparison/{run_id}_research_suite \
  --matrix gemini31_all_voices_fast \
  --matrix gemini31_focused_fast_deliveries \
  --matrix gemini25_flash_model_compare \
  --matrix gemini25_pro_model_compare \
  --resume
```

## Runtime

All providers use the Python 3.12 dependencies isolated in
`.venv-voiceover`. Hosted providers run there too so the stage has one stable
synthesis boundary:

```bash
.venv-voiceover/bin/python -m src.pipeline.voiceover.cli \
  --input-json output/runs/{run_id}/inputs/voiceover/{variant}.json
```

Model caches live under:

```text
.cache/ai_content_creation/models/
```

They are independent of output cleanup and ignored by Git.

## Outputs

```text
output/runs/{run_id}/voiceover/{variant}/
├── audio/full_voiceover.wav
├── audio/chunks/*.wav
├── audio/units/*.wav
├── captions/captions.srt
├── captions/captions.vtt
├── voiceover_package.json
├── voiceover_result.json
└── summary.json
```

The package contains:

- provider chunks retaining `section_id`, `story_id`, and `beat_id`
- one audio unit for the intro, each selected story, and the closing
- exact aligned beat start/end times derived from generated WAV durations
- a config-driven loudness-mastered full voiceover WAV
- SRT/VTT captions derived from the same aligned beats
- script and voiceover fingerprints that bind the WAV to one exact narration

The production profile uses two-pass ffmpeg `loudnorm` targeting `-16 LUFS`
and `-1 dBTP`. Mastering must preserve duration within the configured tolerance
because beat timing remains authoritative downstream. Caption and mastering
paths are excluded from artifact identity; their content hashes and settings
remain fingerprinted so a run can move without changing identity.

Visual planning consumes `audio_units[].aligned_beats`, not anonymous text
chunks. This is beat-level alignment; word-level forced alignment inside a
beat is not currently required.

## Notebook

Use `notebooks/production/voiceover_generation.ipynb`.

- `INPUT_MODE = "fixture"` tests the committed reference script.
- `INPUT_MODE = "run"` loads a real run.
- `SCRIPT_SOURCE = "auto"` succeeds only when exactly one canonical script exists.
- `SCRIPT_SOURCE = "app"` selects native script generation.
- `SCRIPT_SOURCE = "chatgpt"` selects the normalized manual handoff.

If multiple voice variants exist, downstream notebooks require an explicit
`VOICEOVER_VARIANT`; they do not pick the newest file. After synthesis, the
notebook runs deterministic metadata finalization so chapters use actual
section audio-unit starts.

The notebook rereads no production YAML after loading a frozen run context.
