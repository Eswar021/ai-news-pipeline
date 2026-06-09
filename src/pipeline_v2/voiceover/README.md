# Pipeline v2 Voiceover

`src.pipeline_v2.voiceover` is the v2 media-generation module. It keeps the same
app-like boundary as the pure v2 apps:

```python
from src.pipeline_v2.voiceover import run

result = run(input_json)
```

Unlike the pure apps, voiceover is allowed to write WAV files because audio is
the product of this step. The caller must provide `config.output_dir`.

## Providers

| Provider | Best Use | Status |
| --- | --- | --- |
| `kokoro_local` | Fast local smoke tests and simple narration. | Real smoke passed. |
| `chatterbox_local` | Best current default for expressive YouTube narration. | Real smoke passed. |
| `f5_tts_local` | Voice/style transfer from a reference WAV plus matching text. | Real smoke passed. |
| `dia_transformers` | Expressive dialogue-style generation with speaker tags. | Adapter tested; CPU generation is too slow for regular use here. |

Use `chatterbox_local` first when testing script quality. Use `f5_tts_local`
when you have a reference voice clip you want the model to imitate. Keep
`dia_transformers` for GPU testing.

Chatterbox runs a 1000-step sampling loop for every text chunk. That is normal,
but a full 8-minute script can take a long time if the script is split into many
small chunks. For full-script tests, prefer `general_youtube` plus larger chunk
settings. For quick audio checks, generate a 1-2 sentence preview first.

## Notebook Usage

For the ChatGPT-assisted production path, use:

```text
notebooks/v2_chatgpt_voiceover_workbench.ipynb
```

The notebook resumes from an App 4 `video_packaging` run, exports a ChatGPT
content-packet handoff, parses the returned `[SCRIPT]` block, and then runs
voiceover from `input.script_text`.

Voiceover settings come from:

```text
src/pipeline_v2/config/workbench.yaml
```

Change the `voiceover` section there:

```yaml
voiceover:
  provider: chatterbox_local
  style: dramatic_news
  voice: null
  speed: 0.96
```

Supported provider values:

```text
kokoro_local
chatterbox_local
f5_tts_local
dia_transformers
```

For F5-TTS, also set:

```yaml
f5_tts:
  ref_audio_path: "path/to/reference.wav"
  ref_text: "Exact or close transcript of the reference audio."
```

The voiceover cell reloads `workbench.yaml` every time it runs. After changing
provider, style, voice, speed, or provider-specific settings, rerun the
voiceover cell to produce a new audio variant. The notebook writes outputs
under:

```text
output_v2/voiceover/{RUN_ID}_{provider}_{style}_{voice}_{speed}_chatgpt_script/
```

The notebook prints the planned chunk count before synthesis. If the count is
above about 25 and you are using `chatterbox_local`, expect a slow run.

## CLI Usage

The CLI reads the same JSON envelope as `run(...)`:

```bash
.venv-voiceover/bin/python -m src.pipeline_v2.voiceover.cli --input-json output_v2/voiceover/{RUN_ID}/voiceover_input.json
```

The output folder will contain:

```text
audio/full_voiceover.wav
audio/chunks/*.wav
voiceover_package.json
summary.json
```

## Provider Config Snippets

Chatterbox:

```json
{
  "provider": "chatterbox_local",
  "chatterbox": {
    "device": "auto",
    "exaggeration": 0.65,
    "cfg_weight": 0.5,
    "audio_prompt_path": null,
    "cache_dir": "output_v2/model_cache/huggingface_local"
  }
}
```

Chatterbox tuning:

```text
exaggeration: 0.45-0.8, higher is more expressive
cfg_weight: 0.35-0.7, higher follows the text/style more tightly
audio_prompt_path: optional WAV reference for voice cloning/style prompting
```

F5-TTS:

```json
{
  "provider": "f5_tts_local",
  "f5_tts": {
    "model": "F5TTS_v1_Base",
    "device": "auto",
    "ref_audio_path": "output_v2/voiceover/_smoke_chatterbox_no_xet/audio/full_voiceover.wav",
    "ref_text": "Today, we are testing a more expressive local voiceover model for the new pipeline.",
    "cache_dir": "output_v2/model_cache/f5_tts",
    "nfe_step": 32,
    "cfg_strength": 2.0,
    "seed": 1234
  }
}
```

F5-TTS tuning:

```text
nfe_step: 8 for quick smoke, 16 for draft, 32 for better quality
ref_audio_path/ref_text: required and should match each other closely
speed: still controlled by top-level config.speed
```

Dia:

```json
{
  "provider": "dia_transformers",
  "sample_rate_hz": 44100,
  "dia": {
    "model_checkpoint": "nari-labs/Dia-1.6B-0626",
    "device": "auto",
    "cache_dir": "output_v2/model_cache/dia",
    "max_new_tokens": 256,
    "speaker_tag": "S1"
  }
}
```

Dia tuning:

```text
Use a GPU/MPS/CUDA device when possible.
For dialogue text, include speaker tags like [S1] and [S2].
On CPU, loading works but generation is not practical for full scripts here.
```

## Verified Local Smokes

These were tested in `.venv-voiceover`:

```text
kokoro_local: output_v2/voiceover/_smoke_kokoro_after_chatterbox/audio/full_voiceover.wav
chatterbox_local: output_v2/voiceover/_smoke_chatterbox_no_xet/audio/full_voiceover.wav
f5_tts_local: output_v2/voiceover/_smoke_f5_tts/audio/full_voiceover.wav
dia_transformers: import/contract/model-load path tested; CPU synthesis did not finish quickly enough
```

## Install

Use the voiceover Python environment:

```bash
PIP_USER=false .venv-voiceover/bin/python -m pip install -r requirements-voiceover.txt
```
