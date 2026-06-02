# Local Kokoro Voiceover Setup

Kokoro `0.9.x` currently supports Python `>=3.10,<3.13`. The default Python on
this machine is `3.14`, so use a separate Python 3.12 virtual environment for
voiceover generation.

```bash
brew install python@3.12
/opt/homebrew/bin/python3.12 -m venv .venv-voiceover
source .venv-voiceover/bin/activate
PIP_USER=false python -m pip install --upgrade pip
PIP_USER=false python -m pip install -r requirements-voiceover.txt
PIP_USER=false python -m src.voiceover.runner --audition --style general_youtube --force
PIP_USER=false python -m src.voiceover.runner --run-id current --style general_youtube --force
```

The first Kokoro synthesis may download model weights. After the voiceover is
generated, check:

```bash
ls -lh output/current_manifest.json
find output -path '*/voiceover/voiceover_package.json' | tail -1
```

The voiceover module reads the approved `L8/verification_package.json`. It will
refuse to run if Layer 8 is not approved.

Do not run the main rebuild pipeline from `.venv-voiceover`; that environment is
intentionally voiceover-only. Leave it first:

```bash
deactivate
/opt/homebrew/bin/python3 -m src.pipeline.runner 0 1 2 3 4 5 6 7 8 9 --run-profile daily_48h_all_sources
```

Available local style profiles:

```bash
PIP_USER=false python -m src.voiceover.runner --run-id current --style warm_explainer --force
PIP_USER=false python -m src.voiceover.runner --run-id current --style general_youtube --force
PIP_USER=false python -m src.voiceover.runner --run-id current --style dramatic_news --force
PIP_USER=false python -m src.voiceover.runner --run-id current --style calm_documentary --force
```

To compare voices quickly:

```bash
PIP_USER=false python -m src.voiceover.runner --audition --style general_youtube --force
PIP_USER=false python -m src.voiceover.runner --audition --style dramatic_news --voices af_bella,af_nicole,am_puck --force
```

If pip says it cannot perform a `--user` install inside the virtualenv, your
global pip config probably has `global.user = true`. Keep using `PIP_USER=false`
for voiceover venv install and generation commands.
