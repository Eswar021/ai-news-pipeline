# Current System Architecture

Status: Canonical runtime reference

Last updated: 2026-07-13

## Runtime

src/pipeline/ is the only active pipeline runtime.

    src/pipeline/
    |-- apps/
    |   |-- news_collection/
    |   |-- evidence_prep/
    |   |-- story_mapping/
    |   |-- video_packaging/
    |   |-- script_generation/
    |   |-- metadata_creator/
    |   `-- metadata_finalizer/
    |-- contracts/
    |-- handoffs/
    |-- orchestration/
    |-- voiceover/
    |-- visuals/
    `-- config/workbench.yaml

There is no central runner. Focused notebooks orchestrate apps by passing
JSON/dict envelopes between their public run(input_json) boundaries.

Pure apps validate with Pydantic v2, return status/data/summary/handoff
envelopes, and do not write output files. Voiceover and visual modules may
write caller-directed media because WAV, PNG, and MP4 files are their products.

## Production Workflow

    content_pipeline.ipynb
      -> news collection
      -> evidence preparation
      -> story mapping
      -> deterministic video packaging
      -> roundup script generation
      -> metadata draft creation

    voiceover_generation.ipynb
      -> select canonical script by fingerprint
      -> synthesize section-aware audio
      -> retain section, story, and beat identities
      -> finalize metadata chapter timestamps

    visual_production.ipynb
      -> select matching script and voiceover artifacts
      -> plan visuals against aligned audiovisual beats
      -> discover and resolve assets
      -> render scene clips
      -> assemble final video with audio
      -> create publish-review artifacts

Manual ChatGPT scripts and visual plans use chatgpt_handoffs.ipynb. Parsers
normalize manual output into the same canonical contracts used by native apps.
Downstream media code must not branch on a manual-only schema.

## Canonical Data Flow

    raw records
      -> prepared records
      -> ranked stories carrying records
      -> selected roundup packet carrying stories
      -> section-aware audiovisual script beats
      -> section-aware voiceover and aligned timing
      -> story-local visual scenes
      -> rendered video and finalized metadata

The retired fact-packet and numbered-layer paths are not part of this runtime.
Script generation receives selected stories with their full records.

## Script Contract

The authoritative script representation is:

    script_package.sections[].beats[]

Each beat carries stable section, story, beat, and source identities plus
spoken narration and a visual brief. Section narration and full_script are
deterministic projections of those beats.

The roundup generation flow is:

    selected stories
      -> roundup director
      -> parallel story-local writers
      -> bounded story-local reviews
      -> bookend and continuity writer
      -> bounded bookend review
      -> deterministic assembly

No LLM call rewrites the complete episode. Suggested word counts and duration
are guidance and diagnostics, not approval quotas. Content completeness owns
script length, and actual voiceover timing owns downstream media timing.

The proposed creator-led quality redesign is documented in:

- docs/build/content_first_roundup_and_grounded_visuals.md

## Artifact Identity

Canonical scripts, voiceovers, visual plans, and assembled media carry
deterministic provenance and fingerprints. Artifact selection must match the
selected run and upstream fingerprint. Newest-file-wins behavior is forbidden.

Production artifacts use:

    output/
    |-- current_run.json
    `-- runs/{run_id}/
        |-- run_context.json
        |-- news_collection/
        |-- evidence_prep/
        |-- story_mapping/
        |-- video_packaging/
        |-- script_generation/
        |-- metadata_creator/
        |-- metadata_finalizer/
        |-- voiceover/
        `-- visuals/

output_v2/ is historical only. Model caches live under
.cache/ai_content_creation/models/.

## Configuration

Operator-authored configuration lives in src/pipeline/config/workbench.yaml.
The content notebook freezes the selected profile and config hash into
run_context.json. Apps receive effective config inside their input envelope and
do not read YAML directly.

Behavioral values such as providers, models, prompt versions, source policies,
selection limits, voices, visual capabilities, render settings, and bounded
revision loops remain config-driven.

## Synchronization Contract

Voiceover synthesizes the intro, each complete story, and closing as identified
audio units. Provider-level chunks retain their parent section and story
identity. Global timing is derived from concatenated audio units.

Visual planning consumes the same canonical beats and authoritative voiceover
timing. It must not reconstruct story boundaries from full_script, invent raw
episode duration, or select an unrelated voiceover artifact.

Final assembly verifies:

- matching run and script provenance
- complete scene coverage
- no gaps or unintended overlaps
- video duration aligned to voiceover
- valid rendered clips
- audio present in the final media

## Operator Notebooks

- notebooks/production/content_pipeline.ipynb
- notebooks/production/voiceover_generation.ipynb
- notebooks/production/visual_production.ipynb
- notebooks/handoffs/chatgpt_handoffs.ipynb
- notebooks/labs/visual_assets_lab.ipynb

Committed notebooks must have empty outputs and null execution counts.

## Verification

The deterministic media fixture lives at:

    tests/fixtures/media_roundup_reference/

Relevant checks:

    python3 -B -m compileall src/pipeline
    python3 -m pytest -q
    cd src/pipeline/visuals/remotion_engine
    npm run typecheck

Visual changes also require rendering and inspecting fixture frames or clips.
Metadata-only inspection is not sufficient visual QA.
