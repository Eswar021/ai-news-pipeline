# Labs — sample gallery

A single home for **samples we judge and tune by**, and the source the Run Desk UI
will read to show them.

## Voices (`labs/voices/`)
The same representative channel line rendered in each candidate voice, so the
production narration is chosen by ear.

- Preview: open **`labs/index.html`** in a browser (no server needed).
- Regenerate: `.venv-voiceover/bin/python labs/generate_voice_samples.py`
- Manifest: `labs/voices/manifest.json` (line, delivery instructions, voices).

Current set: OpenAI `gpt-4o-mini-tts` — cedar (today's default), marin, coral, ash,
ballad, sage, verse, onyx. (Gemini `Puck` is the current production voice; add it
here when the daily quota resets.)

## Visual components (`labs/visuals/` — planned)
A snapshot of each of the 51 video-engine components (chat-exchange, stat-punch,
timeline, before-after, …) rendered with representative data, so components can be
reviewed and tuned. Not built yet.

## Why
Samples in one place → fast feedback loop: preview here, tell the tuner what to
change, iterate. The UI will surface this folder as a "Labs" tab.
