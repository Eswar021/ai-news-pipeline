# Production Orchestration and Creative Quality Worklist

Status: Active implementation tracker. Q-01 through Q-26 are implemented and
now require a fresh production episode plus human quality review.

Last updated: 2026-07-20

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
- The default planner vocabulary is asset-first and limited to scene families
  with working Remotion and HyperFrames contracts. It includes source/context
  media, identity, clean typography, small explainers, source-proof montages,
  source-supported metrics and contrasts, and focused process/interface motion.
  Old card kinds remain excluded.
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

- writer, reviewer, bookend, and metadata prompts now
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
bookend writer receive the relevant complete context. Configured resource limits fail
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
LLM triage story keys expand recall. Candidate records receive independent
event-identity capsules from complete normalized context. The pair adjudicator
then processes exactly one pair per call so records from unrelated pairs cannot
be confused inside a large prompt. A proposed `same_event` merge receives a
second confirmation call containing both complete normalized records;
duplicate `content`, `cleaned_content`, `semantic_content`, and `raw_content`
aliases are represented by provenance rather than resending the same article
several times. Nothing is clipped. Calls use bounded, config-driven concurrency
and a separate hard single-pair context limit. A pair that embeddings did not
nominate is not silently treated as a negative decision. Candidate, worker,
confirmation, reconciliation, and merge telemetry is returned in the app
summary.

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

### Q-12: Event-component reconciliation and slate deduplication (`P0`, implemented 2026-07-18)

Focused pair decisions no longer merge directly in edge order. Only confirmed
`same_event` edges form proposed components; `follow_up` and
`broader_story_arc` stay as related-story links and cannot chain unrelated
events into one oversized prompt. The reconciler partitions each component
using independently extracted full-record event capsules and focused pair
decisions, so it does not resend every article body. A config-driven token
preflight runs before the provider call and prevents unrecoverable context-size
requests from consuming retries. Code verifies only that every supplied record
ID appears exactly once. This prevents an unrelated record from entering a
story through one mistaken transitive edge while allowing a preview, official
announcement, and independent report to remain one editorial story when their
semantic evidence supports it.

The final roundup selector now has a separate bounded LLM slate-review pass.
It compares the complete candidate stories, removes duplicate coverage of one
event, and can replace it with a distinct reserve candidate. Code enforces only
opaque-ID coverage, selected-count bounds, and one lead first. Script and
metadata prompts also reinforce concrete creator language, varied hook shapes,
memorable source details, and a ban on invented `X vs. Y` framing when the
episode contains no real comparison.

### Q-13: Wide finalist funnel and recoverable slate review (`P0`, implemented 2026-07-18)

Editorial screening no longer repeatedly halves a broad candidate pool until
only the final episode count remains. The production profile now preserves a
preferred 12-story finalist pool, with complete records for every story, before
the episode selector chooses three to five. The target is configurable and may
be reduced only when the complete contexts cannot fit the configured provider
budget; the effective target, screening reductions, and final pool width are
reported in the result.

The final semantic slate reviewer now receives the complete finalist pool plus
a bounded set of late-stage screening reserves when those records also fit the
same complete-context call. It may promote a reserve when that produces a
materially stronger or less repetitive episode. The reviewer separately
reports true duplicate-event groups and episode-level diversity, so shared
editorial texture is not mislabeled as `same_event`. Concrete source details
and legitimate visual potential are semantic tie-breakers, not deterministic
eligibility rules. Code owns only context budgets, opaque IDs, selected-count
bounds, one-lead structure, and exact decision-ledger coverage; it applies no
company, source, or topic quota.

### Q-14: Semantic state continuity and authoritative reviewer revisions (`P0`, implemented 2026-07-18)

The source research contract now carries explicit meaning boundaries for
current versus planned state, source attribution, claim strength, causality,
and terminology such as open-weight versus open-source. These LLM-authored
boundaries remain attached to the complete story context through direction,
writing, review, and metadata generation. Code validates only Pydantic shape
and selected record ownership; it does not infer or score contextual meaning.

The production script profile now treats the reviewer's bounded
`rewrite_required` decision as authoritative and applies a structurally valid
revision directly. The redundant A/B selector, its prompts, schema, config, and
telemetry were removed after a production run showed it reversing five requested
revisions while swapping phrases between current and candidate drafts. Reviewer
prompts require the proposed revision to resolve every reported issue and to
return KEEP when no material net improvement is available.

Metadata title drafting now receives episode shape and source meaning
boundaries. Every internal title candidate identifies its angle strategy,
represented story IDs, any real comparison basis, and a scope/state self-check
before the public title fields are retained. This remains semantic LLM
judgment; no regex rivalry filter or deterministic contextual title validator
was added.

### Q-15: Single revision authority and validator boundary (`P0`, implemented 2026-07-18)

The story and bookend reviewers are the only semantic revision authorities.
Each returns either KEEP or one complete replacement. The former A/B revision
selector was removed end-to-end: no prompt bundle, output schema, config key,
failure mode, invocation path, or selector telemetry remains.

The active post-LLM validation boundary was audited as follows:

| Boundary | Deterministic checks retained | Contextual decisions code must not make |
| --- | --- | --- |
| Editorial triage | Pydantic shape, known record IDs, and complete batch coverage | Relevance, newsworthiness, novelty, or advance/reserve/quarantine judgment |
| Story mapping | Known pair/component IDs, complete record coverage, and exactly-once partitions | Whether records describe the same event, a follow-up, or a broader arc |
| Editorial selection | Known story IDs, bounded selected count, one lead first, and complete decision ledger | Which stories are strongest, diverse, repetitive, or worth selecting |
| Script generation | Pydantic shape, selected story/source ownership, known truth IDs, section order, non-empty beats, deterministic projections, provenance, and one-pass loop bound | Hook quality, humor, prose style, claim interpretation, quote equivalence, metric support, or whether a rewrite is better |
| Metadata | Pydantic shape, option counts, chapter/source URL structure, deduplication, and platform caps | Whether a title angle is accurate, compelling, representative, or a real rivalry |
| Visuals | Pydantic shape, known asset ownership, render payload shape, timeline coverage, duration caps, media streams, and fingerprints | Whether an image or scene semantically fits the narration; LLM/human review owns that judgment |

Embeddings, token budgets, and bounded shortlist sizes may nominate or transport
context, but they cannot make the final semantic decision. Renderer payload
validation is intentionally strict because malformed numeric fields, unknown
assets, overlapping time ranges, or missing streams are executable media
errors rather than editorial opinions.

### Q-16: Role-specific K3 creative routing (`P0`, implemented and frozen-packet tested 2026-07-18)

The production profile keeps GPT-4o on source research and episode direction.
Those calls accurately surfaced complete-record details and meaning boundaries
in roughly 8-17 seconds per selected story, so moving high-volume extraction to
K3 would add latency without evidence of a quality gain. Kimi K3 now owns the
viewer-facing story writer/reviewer and bookend writer/reviewer roles.

The frozen five-story packet from
`run_2026_07_18_171428_daily_48h_all_sources` completed with
`worker_count: 2` in 768.23 seconds versus 1,170 seconds for the prior
sequential script run. All 12 K3 calls completed on their first attempt with no
rate-limit or schema retry. The resulting intro, connectors, and closing were
materially more concrete than the GPT-4o bookends. The evaluation also exposed
two remaining semantic prompt defects: an open-weight model was described as
published source code, and a closing about money arriving first inverted the
lead story's announced-before-close premise. Writer and reviewer prompts now
name both mechanism errors explicitly; the next fresh run must verify them.

Metadata creation now uses one Kimi K3 call and returns one complete chapter
label for every exact script section ID. Code owns timestamps, ordering, source
URLs, and section coverage; it no longer clips article headlines into fragments
such as `AI's` or `sales and`. On the same frozen script, K3 metadata completed
in 279.15 seconds without retry and produced concrete title strategies,
thumbnail text, blocked misleading angles, and seven complete chapter labels.
The isolated comparison artifacts live under
`output/labs/script_model_comparison/run_2026_07_18_171428_k3_creative_worker2/`.

### Q-17: Config-driven hosted voiceover (`P1`, implemented 2026-07-18)

Voiceover now supports OpenAI `gpt-4o-mini-tts` and Gemini TTS as first-class
providers without changing the canonical script, beat timing, mastering,
captions, or fingerprint contracts. Model, voice, natural-language performance
direction, API-key aliases, bounded retries, timeout, and worker count are all
provider-local config. API calls synthesize existing beat-linked chunks in
parallel and deterministically restore original chunk order before timing.
Kokoro remains the free local switch. Provider settings participate in variant
identity so a model or delivery-direction change cannot reuse stale audio.
The current Google key reports a Gemini TTS free-tier limit of three requests
per minute, so Gemini remains an optional comparison provider with one worker;
OpenAI is the active hosted profile until Gemini billing/quota is upgraded.
Real one-chunk smokes passed for both providers. The full OpenAI run for
`run_2026_07_18_184808_daily_48h_all_sources` synthesized 1,380 words across
40 beat-linked chunks in 57.13 seconds. The mastered output is 535.20 seconds,
with seven section audio units, 39 aligned beats, two caption files, monotonic
chunk timing, and exact decoded-WAV/package duration agreement. The prior
Kokoro variant remains available at 585.33 seconds for human A/B listening.

### Q-18: Provider-neutral beat delivery (`P1`, implemented 2026-07-19)

Canonical script beats now carry provider-neutral delivery intent rather than
vendor tags embedded in narration. Voiceover adapters translate that intent
into OpenAI instructions, Gemini performance markup, or plain local synthesis
input while preserving the exact spoken text, beat IDs, section IDs, and
fingerprints. This keeps expressive direction reusable when the configured TTS
provider changes and prevents synthesis-specific syntax from leaking into
captions or script review.

### Q-19: Story-scoped visual capability contracts (`P0`, implemented and real-run tested 2026-07-19)

The visual planner now derives a strict provider schema separately for each
story from that story's available catalog assets. Asset-backed render kinds are
omitted when the required asset type does not exist, and provider-selected
asset IDs form a closed story-owned set. Code no longer substitutes unknown
assets, rewrites render kinds, fills semantic payloads, or hides failed story
plans behind generic text. Pydantic validates the selected render family's
payload shape, including explainer item cardinality, before a plan is accepted.
Deterministic code only binds exact catalog identity and expands long aligned
audio units into short timing continuations.

The frozen production input from
`run_2026_07_18_184808_daily_48h_all_sources` completed with five of five story
plans, 56 renderable scenes, 39 of 39 aligned units covered, no fallback, no
parse or payload-validation failures, and no editor failure. It produced 15
source-proof scenes and held text-like duration to about 25.5 percent. Planner
LLM roles are provider/model configurable. The earlier full-run Kimi attempt
was too broad to diagnose and was superseded by the bounded comparison in Q-24.

### Q-20: Explicit HyperFrames render backend (`P2`, implemented 2026-07-19; production default superseded by Q-26)

Visual rendering now has an explicit `remotion|hyperframes` backend boundary.
The optional HyperFrames adapter supports the active production vocabulary,
isolates one generated project per scene, copies only resolved local assets,
uses bounded scene/frame concurrency, participates in cache identity, and
never silently falls back to Remotion. Seven real scene-family smokes rendered
successfully; a five-scene 720p batch completed in 17.7 seconds with three scene
workers. The initial release kept Remotion as production default while the
recipe compiler was incomplete. Q-26 later promoted the hardened recipe-first
HyperFrames path. HyperFrames must still process pipeline-owned compositions
and trusted local assets only while the current dependency graph contains an
unresolved high-severity `adm-zip` denial-of-service advisory.

### Q-21: Capture-ready source assets and duplicate capture reuse (`P0`, implemented and real-run tested 2026-07-19)

The trusted catalog now verifies source-page screenshot readiness through the
same Chromium capture path used by the resolver. HTTP metadata status and
browser readiness remain separate: a browser-readable page can recover from a
metadata-client failure, while a real challenge, access-denied page, or HTTP
401/403/429 response is not offered to the planner as usable source proof.
Source-backed and quote-highlight scenes must select one exact available,
story-owned catalog asset ID.

The resolver now captures identical URL/target/treatment requests once and
reuses the successful pixels for each scene-owned output. This avoids repeated
publisher requests triggering anti-bot throttling without relaxing target-text
location or substituting fallback media. The frozen 57-scene plan for
`run_2026_07_18_184808_daily_48h_all_sources` resolved with zero failed assets;
six source scenes used the capture cache, including two repeated OpenAI scenes
that previously failed after the first request. The inspected frame showed the
real article and highlighted the requested headline.

### Q-22: Beat-aware TTS request ledger (`P1`, implemented and provider-smoke tested 2026-07-19)

Hosted and local synthesis now emit a provider-neutral `tts_requests.jsonl`
ledger. Each entry retains section, story, beat, and chunk identity; exact
spoken-text and direction hashes; provider/model/voice settings; attempt,
latency, status, and available usage metadata. API keys and binary audio never
enter the ledger. Voiceover summary telemetry reports directed-beat coverage,
while the canonical WAV and aligned beat timings remain authoritative.

### Q-23: Bookend planning and dual-renderer visual recipes (`P0`, implemented and rendered 2026-07-19)

Intro and closing visuals now use one bounded structured bookend-planner call.
It receives the authored beat-level visual briefs and cannot manufacture
display copy by slicing narration words. The planner advertises named recipes
only when both required render backends implement the payload contract.

The first recipe set includes editorial hooks, source scans and highlights,
annotated image/video focus, metric countups and contrasts, relationship/process
motion, interface walkthroughs, evidence stacks, and source-proof montages. The
montage binds two or three exact story-owned source-page IDs; the resolver
captures each page and both HyperFrames and Remotion rendered inspected 16:9
smokes. A persistent source-capture cache with a config-driven TTL reduces
repeated publisher requests across runs without hiding capture failures.

### Q-24: Bounded Kimi K3 visual-planner comparison (`P1`, implemented 2026-07-19)

The provider path was tested in layers. K3 returned a raw probe in 2.63 seconds
and a strict Pydantic/JSON-schema probe in 16.71 seconds. The exact frozen
77,448-character Agility Robotics story prompt then completed in 303.79 seconds
with six scenes and zero production validation errors. GPT-4o-mini completed
the same prompt in 17.95 seconds.

K3's plan was materially stronger on this sample: it avoided duplicated scene
payloads, used two distinct exact source passages, selected a verified robot
image, preserved the narration's “once” contrast, and closed on a supported
two-node explainer. The daily profile now uses K3 for the per-story planner and
story-plan editor because quality takes priority over the roughly 17x latency
on this request. Episode direction and bookends remain GPT-4o-mini because the
bounded comparison did not establish a K3 advantage for those roles. K3 omits
temperature, uses a 600-second timeout, and has one provider attempt per
bounded role call. A fresh five-story run then exposed a provider-policy edge:
Moonshot rejected two otherwise ordinary story prompts as high risk before
returning output. The planner now keeps K3 primary but uses a config-declared
GPT-4o route only for explicit 400/403 content-filter rejections. Rejected and
secondary calls are both logged, and unrelated API, schema, validation, or
timing failures do not trigger provider rotation.

The exact five-story July 19 regression input passed after this change with 37
scenes, all 35 audio-aligned units covered, and zero gaps, overlaps, long
scenes, or story-planner failures. Moonshot rejected the Kimi and perimenopause
story prompts plus one Kimi editor prompt; those calls alone rotated to GPT-4o.
One fallback scene plan needed its second bounded structured attempt. A separate
Kimi story call timed out at 600 seconds and correctly did not rotate providers;
the existing LLM visual editor later supplied a valid complete plan. Total LLM
latency was 2,268.59 seconds: 1,271.90 seconds in Kimi story planning and 847.92
seconds in Kimi visual editing. Correctness is now verified, but per-story cache
or a faster editor route should be evaluated before treating this latency as a
routine iteration loop.

### Q-25: Named event identity and focused slate duplicate audit (`P0`, implemented and regression-tested 2026-07-20)

Story identity now separates supported proper-noun entity/product names from
generic descriptions, preserves aliases and identity evidence, and emits an
event fingerprint. Pair adjudication is isolated to one candidate pair per LLM
call. Same-event proposals, unresolved named identities, and ambiguous
follow-up/story-arc decisions receive a full-record GPT-4o review before a
merge decision is accepted. This fixes the failure mode where one large batch
described unrelated records while adjudicating a different pair.

Editorial selection now performs a second focused semantic duplicate audit on
only the proposed roundup stories. Its result is supplied to the final slate
reviewer, and the final structured slate may retain at most one story from each
reported same-event group. This is not a title/keyword deduper: broad themes and
shared companies remain valid when the concrete events differ. A focused Kimi
K3/Comic Chat/TechCrunch regression recreates the observed failure: indirect
and named Kimi coverage resolves to one event while the unrelated Microsoft
Comic Chat record remains separate.

### Q-26: Recipe-first HyperFrames production design (`P0`, implemented and rendered 2026-07-20)

The daily visual profile now uses HyperFrames with the shared
`editorial_minimal` design contract. Every planner-advertised render kind must
have an allowed named recipe supporting the configured production backends, and
every production scene must return its exact `payload.recipe_id`. Missing,
unknown, mismatched, or unsupported recipes fail before rendering. The planner
can no longer hand a broad scene type to a renderer and receive unrelated
legacy styling.

The recipe compiler implements editorial hooks and chapters, source proof,
annotated image/video, identity reveals, short mechanisms, metric countups and
contrasts, process traces and detail zooms, interface walkthroughs, evidence
stacks/montages, and interface transformations. All projects receive
`frame.md`: warm paper, near-black ink, one burnt-orange accent, EB Garamond
headlines, Oswald labels, large readable zones, restrained motion, and no
decorative cards. The circular identity treatment and montage label overlays
were removed during frame QA.

Eleven representative recipe projects pass HyperFrames runtime, layout, motion,
and WCAG contrast checks and render as valid 1280x720 MP4 clips. The inspected
contact sheet is stored at
`output/labs/hyperframes_recipe_qa/contact_sheet.png`. Remotion remains a
compatibility and visual-lab backend for historical scene families, not the
daily design authority. The upstream ZIP advisory remains an operational
constraint: use only pipeline-owned composition code and trusted local assets.

The frozen July 19 production episode also completed the full live path with
Kimi planning: five stories, 37 scenes, 35 aligned audio units covered, zero
gaps/overlaps/fallbacks, and no missing recipe IDs. HyperFrames rendered all 37
720p preview clips in 80.44 seconds with four scene workers, then assembly and
review completed successfully at the authoritative 397.31-second voiceover
duration. The contact sheet confirms one coherent visual system. Its remaining
creative limitation is asset mix: 10 editorial-text scenes versus only two
context images and one source-owned video, which belongs to future asset/planner
quality work rather than renderer architecture.

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

Q-01 through Q-26 are implemented. The next gate is a fresh production episode
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
- Every planned production scene carries a valid named recipe and the complete
  episode stays within the shared `editorial_minimal` HyperFrames design system.
- Audio/video synchronization remains exact at story boundaries and episode
  end.
- Mastered voiceover measures near the configured loudness target without
  duration drift, and generated captions remain aligned.
- Extreme banners and perceptual duplicate images do not survive cataloging.
- Direct or provider-linked source video is used only when a selected source
  actually exposes a compatible trusted clip and the planner selects it for the
  active narration beat.

## 7. Other Deferred Work

After the validated Q-01 through Q-26 foundation, keep these operational and
product tasks visible without mixing them into the current evaluation:

- Keep Wikimedia, Pexels, Pixabay, and paid frame-level vision verification
  disabled until fresh-run script, grouping, and trusted-catalog quality is
  accepted. Re-enable them only through an explicit profile and human-reviewed
  cost/quality comparison.

- Inspect Kimi K3 story-planning latency and Moonshot rate behavior over several
  fresh episodes before adding provider-safe story-call concurrency. The
  content-filter-only GPT-4o route is operational resilience, not evidence that
  more parallel K3 calls are safe.

- Monitor the HyperFrames transitive `adm-zip` advisory and upgrade when
  upstream ships a fixed release. Until then, render only pipeline-owned
  compositions and trusted local assets; do not accept arbitrary composition
  archives or untrusted project trees.

- Compare the verified OpenAI `gpt-4o-mini-tts` baseline against a
  non-deprecated hosted speech path before production lock. The model still
  works and is highly steerable, but OpenAI currently labels it deprecated;
  replacement quality, exact-script adherence, latency, and episode cost need
  a human-listened A/B rather than an automatic model-name swap.

- Improve asset briefs and catalog coverage for software interfaces, product
  screenshots, people, and official imagery.
- Add a deliberate official product/interface adapter for sources that expose
  assets through JavaScript or authenticated media APIs.
- Improve source-page camera moves and crop targets where screenshots remain
  static or unreadable.
- Add a thumbnail-production workflow only after title/thumbnail options have a
  human-selected direction; metadata options alone are not a publish-ready
  thumbnail.
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

Rerender with the daily HyperFrames backend after a valid plan and resolved
assets already exist (`--render-backend` is optional because the profile now
selects it):

```bash
python -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode preview \
  --render-backend hyperframes \
  --from-module visual_render
```

After manual preview approval, render final delivery media:

```bash
python -m src.pipeline.orchestration.runner visuals \
  --run-id current \
  --plan-source generate \
  --render-mode final \
  --from-module visual_render
```
