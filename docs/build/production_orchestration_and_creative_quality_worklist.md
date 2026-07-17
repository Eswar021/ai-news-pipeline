# Production Orchestration and Creative Quality Worklist

Status: Active implementation tracker. Q-01 through Q-11 were implemented on
2026-07-17 and now require a fresh production episode plus human quality review.

Last updated: 2026-07-17

Target runtime: `src/pipeline/`

This document is a directional build tracker. The current architecture is
documented in `docs/current_system_architecture.md`; application code and
Pydantic contracts remain the implementation authority.

Documentation ownership:

- This file is the single active roadmap and defect tracker under `docs/build/`.
- `creator_voice_storytelling_rubric.md` is a small, current human-QA reference,
  not a second work tracker.
- `docs/archive/content_first_roundup_and_grounded_visuals.md` preserves product
  research and design rationale.
- `docs/archive/contextual_decision_audit_and_editorial_pipeline_redesign.md`
  preserves the original pipeline audit and cutover history.
- Archived files must not be used to infer current implementation status.

## 1. Current Workflow

```text
operator / scheduler / service
  -> orchestration.runner
     -> content stage
        -> news_collection
        -> evidence_prep
        -> editorial_triage
        -> story_mapping
        -> editorial_selection
        -> video_packaging
        -> script_generation
        -> metadata_creator
     -> voiceover stage
        -> fingerprint-select canonical script
        -> voiceover
        -> metadata_finalizer
     -> visuals stage
        -> fingerprint-select script + voiceover
        -> asset_catalog
        -> visual_planner
        -> media_discovery
        -> asset_resolver
        -> visual_render
        -> video_assembly
        -> visual_review
        -> publish_handoff (final mode only)
```

Each app remains independently callable through `run(input_json) -> dict`.
The router does not own editorial or rendering logic. It owns only stage
sequencing, effective envelopes, paths, resumability, state, and logging.

## 2. Runner Contract

Implemented entrypoints:

```text
src/pipeline/orchestration/runner.py
src/pipeline/orchestration/stages/content.py
src/pipeline/orchestration/stages/voiceover.py
src/pipeline/orchestration/stages/visuals.py
```

Operational behavior:

- A new content run freezes the selected authoring profile into
  `run_context.json`.
- `--run-id current` resumes the currently selected run.
- Completed upstream modules are reused by default.
- `--from-module X` reruns X and every downstream module in that stage.
- Visual preview and final render artifacts remain separate.
- `--input-json` accepts an exact stage request for future Django, API, queue,
  cron, or workflow-engine integration.
- Canonical artifacts are selected by run and parent fingerprint, never by
  modification time.

## 3. Logging and State

Implemented outputs:

```text
output/runs/{run_id}/orchestration/
  run_state.json
  content_stage_result.json
  voiceover_stage_result.json
  visuals_stage_result.json
  logs/
    content.log
    voiceover.log
    visuals.log
    events.jsonl
```

The stage wrapper emits one start and end/failure event around every app call.
This keeps logging integration out of app internals. Long-running CLI media
subprocess output is streamed into the owning stage log. Logging level,
rotation, console output, and summary/verbose event detail are config-driven
under `profile.orchestration.logging`.

Every stage response now returns `log_path`, `events_path`, and
`run_state_path`, so the CLI output points directly to the durable diagnostics.
Dependency log levels are also config-driven; routine HTTP client status lines
are suppressed without hiding pipeline warnings or provider failures. The
visual renderer forwards scene start, cache, batch progress, retry, and
completion events through the same stage logger while remaining independently
callable.

`run_state.json` records stage/module status, result paths, summaries, and
whether a result was reused. It improves inspection and restart behavior but
does not replace canonical app results or provenance validation.

## 4. Creative Hardening Implemented

### Script continuity

- Connector contracts now name `target_story_id`, not an ambiguous story ID.
- The transition line and title treatment must introduce that same target.
- Bookend prompts receive the ordered connector target manifest.
- Review prompts explicitly inspect shifted connectors, intro/body repetition,
  exact quotations, and preserved attribution.

### Creator voice

- Story and bookend prompts prioritize a story-specific premise, clear creator
  viewpoint, natural spoken rhythm, and actually expressed creative devices.
- Paraphrases must not be placed inside quotation marks.
- Opinions, forecasts, allegations, and company claims retain attribution.
- The intro previews the episode without repeating the first story's opening.
- These remain LLM and human editorial judgments. Code does not score prose
  using keyword lists, semantic thresholds, or engagement formulas.
- A structured source-research call now builds an additive semantic brief from
  complete records. Regex extraction and capped truth menus no longer define
  the writer's prompt boundary.
- Source-research notes, values, quotations, and punctuation are LLM-owned.
  Code validates their Pydantic shape and assigned record IDs but never compares
  them against article strings or launches semantic repair retries.
- The director classifies an episode as either a real shared tension or a
  curated roundup instead of inventing one universal thesis for unrelated
  stories.
- Each story brief now carries a detail palette, source-meaning boundaries,
  hook strategy, explanation path, creator reaction, and payoff chosen from
  the semantic brief while complete records remain available to the writer.
- Bookends are instructed to open with one clear curiosity gap and concise
  episode promise rather than reciting every headline before the stories begin.

### Visual grounding and pacing

- Native and ChatGPT visual plans may carry `evidence_truth_ids` for numeric
  graphics. Code validates identifier ownership and renderer payload shape but
  does not compare displayed values with source strings. Numeric meaning and
  treatment are planner/reviewer judgments.
- Intro and closing deterministic continuity scenes are emitted per authored
  script unit rather than grouping unrelated narration into one long text
  treatment.
- The planner continues to prefer real source/catalog assets and explanatory
  motion over repeated kinetic text.
- Unsupported or incomplete numeric graphics now return to the existing
  bounded story-planning retry. Code no longer converts them into screenshots
  or text scenes unless the profile explicitly selects that named legacy mode.
- A long voiceover unit must receive enough distinct semantic scene treatments.
  The stitcher only assigns authoritative timing; it refuses to manufacture
  variety by cloning one payload with different motion labels.
- Story-title treatments preserve the complete title while promoting the
  concise authored label. Logo resolution verifies installed Simple Icons
  exports and uses a full-name typographic identity when no real logo is
  available; it never fabricates initials.
- Source screenshots use a config-driven focus zoom and target highlight, and
  the article scene reserves more screen area for the captured page.
- The default planner vocabulary is now deliberately compact and asset-first:
  source page, source image, logo, editorial text, simple explainer, and one
  deterministic story transition. The old specialist renderers remain
  available only through explicit profiles rather than overwhelming every LLM
  planning call.
- The `editorial_minimal` Remotion style replaces dark dashboard panels with a
  warm editorial canvas, expressive serif headlines, large readable labels,
  restrained connectors, and card-free story transitions.

### Fresh-run audit and current remediation

The full run `run_2026_07_16_112045_daily_48h_all_sources` completed with exact
audio/video synchronization and 36 rendered scenes, but it was still an
assisted-production beta rather than unattended publish-ready output.

Observed issues:

- narration still used generic launch language and weak reusable bookends
- lead, major, and brief stories did not remain clearly differentiated
- one analogy materially overstated the scale of a one-million-token context
  window
- the selected voiceover measured about `-25.7 LUFS`, which was too quiet for
  normal YouTube playback
- only about 41% of the episode used real/catalog-backed visual duration
- the asset catalog retained some extreme banners and near-duplicate images
- selected source pages could expose useful direct video, but the catalog did
  not register it

Implemented in the current pass:

- writer, reviewer, revision-selector, bookend, and metadata prompts now
  calibrate against stock hype, misleading analogies, generic conclusions, and
  collapsed story roles
- role-specific word suggestions remain soft creative orientation rather than
  approval quotas
- voiceover now performs config-driven two-pass loudness mastering and writes
  aligned SRT/VTT captions
- mastering duration is verified before the original aligned timing is trusted
- the trusted asset catalog rejects extreme image aspect ratios, removes
  perceptual near-duplicates, and can register bounded direct and
  selected-source-linked videos
- the planner can choose exact story-owned `source_video` assets for short
  muted B-roll scenes; the editor reviews only named plan problems and does not
  treat unused assets as a quota

## 5. Validated Quality Work Items

These items were revalidated against the active code and the audited production
runs. The priority is better source use and better video storytelling, not
additional naive validators.

### Q-01: Complete source context (`P0`, implemented 2026-07-17)

Every selected story now receives one complete, versioned `story_context_v1`
packet. It contains all selected records with complete cleaned content and
source metadata. The source researcher, director, writer, reviewer, and
revision selector receive that same packet. Configured resource limits fail
clearly rather than clipping records. LLM call metadata records context mode,
record keys, per-record character counts, and serialized context size.
Story-level visual planning and conditional visual editing likewise receive
every selected record for their active story; the global episode visual
director receives the complete timed script plus ordered story summaries
because it controls style and pacing rather than source interpretation.

### Q-02: Semantic source briefs (`P0`, implemented 2026-07-17)

An app-local structured source-research call now identifies concrete details,
mechanisms, memorable examples, quotations, caveats, personality opportunities,
and visual anchors from the complete records. Regex metric extraction no longer
decides what the writer sees. Code verifies only response shape, record
ownership, and stable provenance IDs. It does not compare notes, quotations,
values, paraphrases, or punctuation with source strings and does not assign
editorial meaning.

### Q-03: Shared story packet (`P0`, implemented 2026-07-17)

All story-local semantic agents share the same full packet. Episode direction
also receives the ordered complete packets, preventing an early compact
projection from hiding material later agents need.

### Q-04: Reversible article normalization (`P0`, implemented 2026-07-17)

Generic HTML-to-text normalization removes markup and suppressed page elements
before semantic use, then applies domain-specific chrome removal. The original
source body remains in `raw_content`, and cleaning provenance records whether
markup was removed and which rule ran. This is format cleanup, not relevance
filtering.

### Q-05: Detail palette and hook strategy (`P1`, implemented 2026-07-17)

The director receives each complete story packet and semantic brief, then
chooses a useful detail palette, hook, explanation, creator reaction, and
payoff. These remain creative guidance; no deterministic quota forces the
writer to use a weak selection.

### Q-06: High-recall pair nomination (`P0`, implemented 2026-07-17)

Embeddings now nominate a config-driven top-k neighbor set inside the run
window instead of rejecting pairs at one fixed similarity threshold. Compatible
LLM triage story keys expand recall. The pair adjudicator receives every
candidate's complete normalized semantic body and non-text metadata once;
duplicate `content`, `cleaned_content`, `semantic_content`, and `raw_content`
aliases are represented by provenance lengths rather than resending the same
article three or four times. Nothing is clipped. Pair batches use bounded,
config-driven concurrency and a separate hard single-pair context limit. Only
`same_event` merges. Explicit `follow_up`, `broader_story_arc`, or `unrelated`
cross-pair judgments prevent transitive over-merges; a pair that embeddings did
not nominate is not silently treated as a negative decision. Candidate, batch,
worker, and merge telemetry is returned in the app summary.

### Q-07: Trusted source-linked video (`P1`, implemented 2026-07-17)

The trusted catalog recognizes selected-source YouTube, X, and Vimeo links and
embeds. A config-driven `yt-dlp` adapter enforces provider, count, duration,
resolution, byte-size, and timeout limits. Resolution failures remain visible
warnings and never trigger unrelated media substitution.

### Q-08: Conditional visual editor (`P0`, implemented 2026-07-17)

The editor now runs only for named plan problems such as invalid structure,
repeated exact treatments, or a text-heavy story. Unused assets remain
telemetry, not a defect or usage quota. The editor prompt defaults to KEEP and
forbids revisions made merely to consume assets.

### Q-09: Trust versus suitability (`P0`, implemented for trusted-only profile 2026-07-17)

Catalog selections now report deterministic `provenance_verification`
separately from `semantic_verification` and `narration_suitability`. The default
profile relies on the story planner's exact asset-ID decision from rich catalog
metadata and truthfully records that no independent vision review occurred.
Paid frame-level vision review remains an explicit later profile choice.

### Q-10: Media-backed story transitions (`P1`, implemented 2026-07-17)

The deterministic story transition reuses the opening image, video, or logo
that the story-level planner selected for that exact beat, then overlays the
canonical story number/title while narration continues. Code does not choose a
background by keyword or list order. A short clean full-screen reset remains
only when the semantic plan supplied no suitable opening asset.

### Q-11: Repository-wide semantic gate audit (`P0`, implemented 2026-07-17)

The active runtime was audited from collection through visual production for
code-owned contextual approval. The resulting boundary is explicit:

- collectors retrieve configured sources and record objective fetch outcomes;
  they do not stamp lexical relevance, title-overlap, listing-suspicion, or
  topic labels
- evidence prep rejects only empty records, valid timestamps outside the run
  window, and exact structural duplicates; it retains raw and cleaned content
- triage, story identity, episode selection, source research, prose review, and
  visual meaning remain structured LLM decisions
- embeddings, lexical media scores, and provider rank may nominate or order a
  bounded candidate pool, but they cannot approve a merge, story, rewrite, or
  external media asset
- source research and reviewer candidates are checked for Pydantic shape and
  known story/record/truth IDs, never exact source wording, punctuation,
  keyword overlap, metric matching, claim strength, or prose similarity
- asset cataloging preserves source-declared hero/document order, accepts
  structurally usable portrait imagery, and reports candidate omissions caused
  by explicit resource caps
- visual text-mix, per-kind repetition, and other creative diagnostics are
  warnings or LLM review context, not code approval gates
- manual visual-plan parsing preserves authored beat actions and emphasis; code
  does not infer creative behavior or critique labels with keyword lists
- external provider media cannot be selected by lexical/numeric ranking alone;
  enabling that path requires the explicit semantic vision-review profile

Hard failures remain appropriate for schema, required IDs, source/asset
ownership, run and parent fingerprints, configured resource ceilings, timeline
coverage, render payload shape, media integrity, and bounded-loop behavior.

### Standing Semantic Policy (`KEEP`)

Engagement, humor, hook quality, claim interpretation, tone, visual meaning,
and source relevance remain LLM or human judgments. Code validates schema,
record ownership, timing, identity, bounded loops, renderer shape, and artifact
provenance. Do not add exact-text comparisons, regex prose scores, keyword
approvals, semantic-overlap gates, or numeric relevance formulas as final
decisions.

### External Media Capability

External media discovery is already implemented for Wikimedia, Pexels, and
Pixabay. It is not Google Images. The active production profile deliberately
sets `trusted_catalog_only=true` and `allow_query_fallback=false`; Pexels and
Pixabay are disabled, and semantic vision verification is disabled. Therefore
the audited run used only story-owned catalog media. Q-09 now separates trust
from suitability, but provider search and paid frame review remain deliberately
deferred until the fresh-run source, script, and trusted-catalog foundations
pass human review.

## 6. Next Evaluation Gate

Q-01 through Q-11 are implemented. The next gate is a fresh production episode
from evidence preparation onward, followed by artifact inspection rather than
summary-only review. External provider search and paid vision verification stay
disabled during this evaluation so source-context, grouping, script quality,
trusted catalog selection, and transition behavior can be judged independently.

Script review:

- Every story opens differently and has a recognizable mini-arc.
- Intro language does not repeat the first story body.
- Story-title motion and spoken transition name the same story.
- Quotes are exact; paraphrases are unquoted; forecasts and allegations retain
  attribution.
- The narrator has a useful point of view without fabricated experience.
- Heterogeneous stories are allowed to coexist without a fake universal
  thesis.

Visual review:

- The active visual explains or shows the sentence being spoken.
- Numeric charts display only source-carried values.
- Source pages, product imagery, logos, diagrams, and contextual media provide
  variety; kinetic text is supporting rather than dominant.
- Intro beats receive distinct treatments instead of one overloaded screen.
- Repeated catalog assets and repeated render kinds are visible in the contact
  sheet and corrected before final render.
- Audio/video synchronization remains exact at story boundaries and episode
  end.
- Mastered voiceover measures near the configured loudness target without
  duration drift, and generated captions remain aligned.
- Extreme banners and perceptual duplicate images do not survive cataloging.
- Direct or provider-linked source video is used only when a selected source
  actually exposes a compatible trusted clip and the planner selects it for the
  active narration beat.

## 7. Other Deferred Work

After the validated Q-01 through Q-11 foundation, keep these operational and
product tasks visible without mixing them into the current evaluation:

- Keep Wikimedia, Pexels, Pixabay, and paid frame-level vision verification
  disabled until fresh-run script, grouping, and trusted-catalog quality is
  accepted. Re-enable them only through an explicit profile and human-reviewed
  cost/quality comparison.

- Improve asset briefs and catalog coverage for software interfaces, product
  screenshots, people, and official imagery.
- Add a deliberate official product/interface adapter for sources that expose
  assets through JavaScript or authenticated media APIs.
- Improve source-page camera moves and crop targets where screenshots remain
  static or unreadable.
- Add a thumbnail-production workflow only after title/thumbnail options have a
  human-selected direction; metadata options alone are not a publish-ready
  thumbnail.
- Decide whether intro/closing deserve an additional bookend visual-planning
  LLM call. This changes provider cost and call count, so it remains a
  deliberate product/config decision rather than a hidden implementation
  assumption.
- Add a scheduler/service adapter that submits exact stage JSON envelopes.
- Add cancellation and heartbeat events for long renders.
- Add optional remote artifact storage without changing app contracts.
- Add a small run-inspection UI over `run_state.json` and `events.jsonl`.

## 8. Commands

New full content run:

```bash
python -m src.pipeline.orchestration.runner content \
  --profile daily_48h_all_sources
```

Resume a run from script generation after prompt/code changes:

```bash
python -m src.pipeline.orchestration.runner content \
  --run-id current \
  --from-module script_generation
```

Generate matching voiceover and finalized metadata:

```bash
python -m src.pipeline.orchestration.runner voiceover \
  --run-id current \
  --script-source app
```

Build a fast visual preview:

```bash
python -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode preview
```

After manual preview approval, render final delivery media:

```bash
python -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode final \
  --from-module visual_render
```
