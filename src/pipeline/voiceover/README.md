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

The production notebook always prefers the canonical envelope so timing and
source provenance remain available.

## Providers

- `kokoro_local`: fast, free local default
- `chatterbox_local`: slower expressive local model
- `f5_tts_local`: reference-voice local synthesis
- `dia_transformers`: experimental dialogue-style local synthesis

Provider, voice, style, speed, chunking, pauses, sample rate, and provider
settings come from the input config. `llm_client` is not involved.

The default profile in `src/pipeline/config/workbench.yaml` uses Kokoro with
`af_heart`, `general_youtube`, and speed `1.0`. Change those values in YAML
before creating a production run so the frozen profile records the choice.

## Runtime

Kokoro and the optional local providers use Python 3.12 dependencies isolated
in `.venv-voiceover`:

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
├── voiceover_package.json
├── voiceover_result.json
└── summary.json
```

The package contains exact chunk start/end times used by visual planning.

## Notebook

Use `notebooks/production/voiceover_generation.ipynb`.

- `INPUT_MODE = "fixture"` tests the committed reference script.
- `INPUT_MODE = "run"` loads a real run.
- `SCRIPT_SOURCE = "app"` selects native script generation.
- `SCRIPT_SOURCE = "chatgpt"` selects the normalized manual handoff.

The notebook rereads no production YAML after loading a frozen run context.
