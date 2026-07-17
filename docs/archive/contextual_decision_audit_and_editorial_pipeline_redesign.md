# Contextual Decision Audit and Editorial Pipeline Redesign

Status: Archived audit and redesign record. Several findings were fixed or
superseded after this audit. Do not use this file as the active implementation
tracker; current validated work is tracked in
`docs/build/production_orchestration_and_creative_quality_worklist.md`.

Last reviewed: 2026-07-17

Target runtime: `src/pipeline/`

Related design:

- `docs/current_system_architecture.md`
- `docs/archive/content_first_roundup_and_grounded_visuals.md`
- `docs/build/creator_voice_storytelling_rubric.md`
- `src/pipeline/visuals/README.md`

## 1. Purpose

This document tracks places where the pipeline uses deterministic code to make
contextual or editorial decisions that code cannot reliably make.

The most important product objective is:

    Collect enough potentially useful news.
    Preserve the source context.
    Use semantic editorial judgment to rank and select stories.
    Give each selected story's real context to its writer.
    Preserve story and beat identity through voiceover and visuals.

The current system sometimes does the opposite. It repeatedly removes records
with keyword rules, title overlap, content length, source-group assumptions,
fixed point scores, and hard category flags. A useful record that is removed in
an early stage cannot be recovered by a better model later.

The same category error appears in the visual path. When semantic visual data is
missing, code can invent a chart, relationship, timeline, or workflow that looks
valid to the renderer but does not represent the narration.

This document does not propose removing all validation. It separates objective
integrity checks from semantic editorial judgment.

## 2. Executive Decision

Use code for facts the machine can prove exactly. Use an LLM or human for
meaning that depends on context.

Hard deterministic decisions are appropriate for:

- Required Pydantic fields and supported enum values.
- Valid identifiers, URLs, timestamps, and source ownership.
- A reliable collection-window comparison.
- Exact URL, provider ID, video ID, repository ID, and document ID duplicates.
- Section, story, beat, scene, and artifact ordering.
- Fingerprints, file existence, media streams, dimensions, and durations.
- Bounded count and diversity constraints after editorial selection.
- Timeline coverage and audiovisual synchronization.

Hard deterministic decisions are not appropriate for:

- Whether an article is relevant to the channel.
- Whether a tutorial, research paper, product update, or community project is
  worth covering.
- Whether a record is noise, important, surprising, novel, or useful.
- Whether two differently worded records describe the same evolving story.
- Whether one story deserves the lead position.
- Whether prose is engaging, overhyped, corporate, or sufficiently nuanced.
- Whether a narration clause implies a chart, flow, comparison, or visual
  metaphor.
- Whether a photo or video actually depicts the requested person, event,
  product, or concept.

Numerical signals such as recency, source type, stars, comments, and content
length may be supplied to an editorial model as evidence. They must not become
the sole eligibility rule.

## 3. Audit Scope

The audit covered the active canonical runtime only:

```text
news_collection
  -> evidence_prep
  -> editorial_triage
  -> story_mapping
  -> editorial_selection
  -> video_packaging
  -> script_generation
  -> metadata and voiceover
  -> visual planning
  -> media discovery and asset resolution
  -> rendering and assembly
```

The audit included:

- Active Python implementation under `src/pipeline/`.
- Effective behavior in `src/pipeline/config/workbench.yaml`.
- Collector configuration in `apps/news_collection/`.
- Production artifacts under `output/runs/`.
- Six available evidence-prep, story-mapping, and packaging run summaries.
- Full latest-run story ranking and packaging results.

The evidence in this section describes the runtime as originally audited. It is
retained as the regression baseline. Section 10 records the implemented
cutover; the shadow-only path described by the historical evidence is no longer
the production route.

## 4. Verified Run Evidence

### 4.1 Latest run funnel

Reference run:

```text
run_2026_07_13_223834_daily_48h_all_sources
```

Observed funnel:

| Stage | Input | Output | Observation |
| --- | ---: | ---: | --- |
| News collection | 301 fetched candidates | 153 records | Collector filters removed 118 counted candidates; per-source caps account for the remaining counted difference, while provider failures reduced coverage separately. |
| Evidence prep | 153 | 27 | 126 records were outside the frozen 48-hour window. |
| Story mapping | 27 | 26 stories | 25 stories were singletons and only one pair was semantically merged. |
| Video packaging | 26 stories | 5 selected | Selection was existing rank order plus fixed caps, not an episode-level editorial decision. |
| Script generation | 5 stories | 5 story sections | Full selected records reached the writer and the structural checks passed. |

The 126 time-window exclusions are not inherently bad. A reliable timestamp and
frozen run window are objective. The problem is that collectors fetch many stale
entries, some source timestamps are unreliable, and unknown or synthetic dates
can make an otherwise valid rule destructive.

### 4.2 Six-run retention evidence

Across the six available production run summaries:

| Measurement | Count |
| --- | ---: |
| Collected records entering evidence prep | 891 |
| Prepared records retained | 102 |
| Records excluded | 789 |
| Outside-window exclusions | 784 |
| Semantic crypto exclusions | 5 |
| Story-mapping singleton drops | 5 |
| Semantic cluster merges | 1 |

All five semantic crypto exclusions were the same clearly relevant AI story:

```text
Claude Code sends 33k tokens before reading the prompt; OpenCode sends 7k
```

The filter interpreted language-model tokens as cryptocurrency. The active
config now contains special AI-token exceptions, but that only patches one
word. It does not make regex-based topic judgment reliable.

### 4.3 Collector opacity

Across the same six runs:

| Source group | Fetched | Collected | Counted as filtered |
| --- | ---: | ---: | ---: |
| Company blogs | 438 | 402 | 36 |
| Tech news | 702 | 372 | 150 |
| Research | 60 | 60 | 0 |
| YouTube | 1 | 1 | 0 |
| Community signals | 600 | 56 | 544 |

The Hacker News path retained only 8 of 100 scanned stories in the latest run.
Filtered community candidates are not stored in a durable decision ledger, so
we cannot later inspect all 92 rejected titles or replay them through a better
classifier. That is both a retention and observability defect.

### 4.4 Fixed ranking produces inconsistent editorial results

The latest fixed score placed these very different stories in the same
`medium` bucket:

- Waze AI features.
- An Apple/OpenAI lawsuit.
- An extreme-event research result.
- Claude pricing in India.
- An Amazon SageMaker UI update.
- A celebrity reaction to Meta glasses.
- An Asus gaming-tablet discount.

The Asus sale was not marked as noise and received the same bucket used for
strong AI stories. Meanwhile useful community projects were pushed into the
`low` bucket through source and self-published penalties. This demonstrates why
a scalar formula is useful as telemetry but unreliable as the editorial slate.

### 4.5 Destructive content cleaning is substantial

In the latest run, domain regex cleaning modified nine retained records and
removed 10,896 characters. The prepared record carries the cleaned content and
cleaning counts, but not a durable raw-content field for downstream recovery.
When a marker or regex is wrong, useful context is permanently hidden from the
writer.

## 5. Decision Ownership Model

Every pipeline decision should belong to one of four tiers.

### Tier A: Hard deterministic reject

Use only when the system can prove that the item cannot be used.

- Malformed input that fails the public contract.
- Empty record with no title, description, body, transcript, or usable URL.
- Invalid or unsupported URL scheme.
- Exact duplicate from a stable source identifier or canonical URL.
- Reliably dated record outside the frozen collection window.
- Missing required parent fingerprint or mismatched artifact lineage.
- Missing or corrupt media file.
- Invalid scene duration, timeline gap, overlap, or missing audio/video stream.

### Tier B: Quarantine or quality warning

Keep the item, but make uncertainty visible.

- Missing or ambiguous publication date.
- Short content.
- Title/body mismatch.
- Listing-page suspicion.
- Failed transcript fetch with usable video metadata.
- Article extraction with low confidence.
- Source relationship uncertainty.
- Screenshot target text not found.
- Text logo fallback instead of a verified brand asset.

### Tier C: AI editorial judgment

Return structured scores, reasons, and confidence. Do not delete the original
candidate.

- Channel relevance.
- Newsworthiness and novelty.
- Tutorial, promotion, opinion, event update, or noise classification.
- Viewer value and story potential.
- Same-event or follow-up relationship.
- Story ranking, roundup selection, and lead/major/brief roles.
- Script story engine, framing, explanation, humor, and payoff.
- Semantic visual type and grounded payload.
- Image/video semantic match.

### Tier D: Human review

Use where taste, identity, rights, or reputational risk remains material.

- Final episode slate when desired.
- Script creative quality.
- Ambiguous named-person or breaking-event media.
- Final voice and pronunciation review.
- Contact sheet and final video review.

## 6. Detailed Issue Inventory

Priority meanings:

- `P0`: Can delete valid context or fabricate false visual meaning. Address
  before trusting unattended production.
- `P1`: Directly affects story selection and script quality.
- `P2`: Important quality, maintainability, or handoff risk.
- `P3`: Low-risk cleanup or telemetry improvement.

### 6.1 News collection

#### COL-01: RSS relevance is a hard lexical filter (`P1`)

Location: `apps/news_collection/collectors/tech_news.py`,
`_is_relevant_article()`.

Current behavior: phrase and token counts decide whether an RSS entry is
collected. The rejected record is represented only by a note, often limited to
the first ten notes.

Risk: paraphrased AI stories can be removed, while unrelated stories containing
an AI keyword can pass.

Action: collect candidate metadata first. Move channel relevance to structured
editorial triage. Keep source-specific search terms as retrieval queries, not
post-fetch truth.

#### COL-02: Hacker News relevance is a hard lexical filter (`P0`)

Location: `apps/news_collection/collectors/community_signals.py`,
`_is_relevant()` and `_matches_relevance_text()`.

Current behavior: one phrase, two strong tokens, or a strong/weak token pair is
required. In the latest run, 92 of 100 scanned stories were removed before a
durable record existed.

Risk: high false-negative rate with no replayable candidate ledger.

Action: retain the scanned candidate metadata. Fetch full article text only for
the best retrieval candidates if cost matters, but let semantic triage rank all
candidate titles and summaries first.

#### COL-03: GitHub popularity and lexical rules are eligibility gates (`P0`)

Location: `apps/news_collection/collectors/community_signals.py`,
`_collect_github()`.

Current behavior: repositories require a configured star floor and lexical
match. The match excludes the README even though the README has already been
downloaded and becomes the record's main content.

Risk: a new, genuinely important AI project can be removed for low stars or a
minimal description. Popularity is not relevance.

Action: use stars, forks, update time, and repository age as model features.
Apply only a generous retrieval cap. Include the README in semantic triage.

#### COL-04: GitHub publication time is synthetic (`P0`)

Location: `apps/news_collection/collectors/community_signals.py`, record
construction in `_collect_github()`.

Current behavior: `published_at` is set to the collection-window end rather
than `pushed_at`, `updated_at`, or `created_at`.

Risk: every accepted repository appears maximally fresh and bypasses the time
window. Recency ranking becomes false.

Action: preserve all three GitHub timestamps. Define a config-driven editorial
event timestamp, normally `pushed_at`, without overwriting provenance.

#### COL-05: YouTube window calculation is not frozen-run accurate (`P1`)

Location: `apps/news_collection/collectors/youtube_transcripts.py`.

Current behavior: lookback hours are floored to whole days and subtracted from
the machine's current time. The frozen window start is not used directly.

Risk: a 36-hour window becomes one day, and notebook delay can shift results.

Action: pass the exact frozen `collection_window.start` to YouTube.

#### COL-06: Missing transcript deletes the whole video candidate (`P2`)

Location: `apps/news_collection/collectors/youtube_transcripts.py`.

Current behavior: a transcript failure removes otherwise usable title,
description, channel, date, and URL metadata.

Risk: potentially useful videos disappear instead of being marked
`transcript_unavailable`.

Action: retain metadata in quarantine. Editorial triage can decide whether it
is useful enough to pursue another transcript path.

#### COL-07: Research retrieval is broad, capped, and not theme-aware (`P1`)

Location: `apps/news_collection/collectors/research_papers.py`.

Current behavior: the newest papers in a broad arXiv category consume the cap
before query themes or semantic relevance are considered.

Risk: unrelated papers fill the limited candidate set while relevant papers
outside the first page are never seen.

Action: use broad semantic search queries or fetch a larger candidate pool,
then perform AI triage. Keep the cap as a cost boundary after triage.

#### COL-08: Article extraction is a low-observability heuristic (`P2`)

Location: `apps/news_collection/utils.py`, `extract_article_text()`.

Current behavior: the first sufficiently long `article` or `main` node wins;
otherwise the entire page is flattened.

Risk: navigation, unrelated article bodies, or page chrome can become source
context.

Action: retain extraction method, raw snapshot reference, body candidate, and
quality confidence. Do not convert low confidence into a semantic rejection.

#### COL-09: Company listing and content-integrity heuristics are too strong (`P1`)

Location: `apps/news_collection/collectors/company_blogs.py`.

Current behavior: URL path fragments, title/body length, and title-token overlap
create `wrong_article`, `title_mismatch`, and listing classifications. OpenAI
content is also trimmed at marker phrases.

Risk: a valid article with a creative lead, short release, or marker text in the
body can be mislabeled. Evidence prep later converts these labels into deletion.

Action: keep these as extraction-quality observations. Never let one heuristic
be the final semantic decision.

### 6.2 Evidence preparation

#### EV-01: Missing date is a hard deletion (`P1`)

Location: `apps/evidence_prep/app.py`, `_prepare_record()`.

Current behavior: any record without a parseable publication date is removed.

Risk: undated but current release pages and repositories disappear.

Action: hard-filter only reliably dated outside-window records. Quarantine
unknown dates and expose a `date_confidence` field.

#### EV-02: Official content length and title overlap delete valid sources (`P0`)

Location: `apps/evidence_prep/app.py`,
`_official_content_exclusion_reason()` and `_official_title_mismatch()`.

Current behavior: article bodies below 700 characters or with low title-token
overlap against the first 120 characters are deleted.

Risk: short announcements, pages with author biographies, and articles with a
narrative lead are valid but fail the rule.

Action: turn these into extraction confidence flags. Retain the source and let
editorial triage consider title, summary, body, URL, and source identity.

#### EV-03: Topic category regexes are hard deletion gates (`P0`)

Location: `apps/evidence_prep/app.py`, `_topic_exclusion_reason()` and its
crypto, finance, promotion, consumer, release, and developer helpers.

Current behavior: regexes and keyword lists decide semantic categories and
delete records.

Confirmed failure: the Claude Code token-usage story was repeatedly deleted as
cryptocurrency.

Action: remove semantic topic deletion from evidence prep. Return topic hints
as features if useful, but let editorial triage make the contextual decision.

#### EV-04: Research relevance is a lexical score with a hard zero (`P1`)

Location: `apps/evidence_prep/app.py`, `_rebalance_research_papers()` and
`_score_research_paper()`.

Current behavior: literal theme and priority-term occurrences determine a
score. Score zero is deleted and a fixed maximum deletes overflow.

Risk: relevant paraphrased research is removed, and keyword-heavy papers win.

Action: semantic triage should rank research with audience value, novelty,
technical significance, and source usability. The cap remains only after rank.

#### EV-05: Content cleaning is destructive and not reversible downstream (`P0`)

Location: `apps/evidence_prep/utils.py`, `clean_article_content()`.

Current behavior: domain marker and regex rules remove text. Only the cleaned
content is carried into the prepared record.

Risk: a broad marker or regex can erase facts needed by the script.

Action: retain `raw_content`, `cleaned_content`, rule name, removed spans or a
raw snapshot reference, and cleaning confidence. The writer may default to
cleaned content but must be able to recover the original.

#### EV-06: Source relationship can overwrite explicit provenance (`P1`)

Location: `apps/evidence_prep/app.py`, `_source_relationship()`.

Current behavior: GitHub domains are labeled `self_published` before an
existing upstream relationship is respected.

Risk: an official organization's repository can be mislabeled and penalized by
story ranking.

Action: respect explicit collector provenance first. Use domain inference only
when relationship is absent, and mark inference confidence.

#### EV-07: Listing and generic-title rules are hard exclusions (`P2`)

Location: `apps/evidence_prep/app.py`, `_is_listing_record()` and
`_is_generic_title()`.

Current behavior: path substrings and a small title set decide unusability.

Risk: some topic or index URLs contain a valid release body.

Action: keep clearly empty pagination pages as objective rejects. Quarantine
ambiguous pages based on extraction confidence rather than path alone.

#### EV-08: Exact deduplication is mostly appropriate (`KEEP`)

Location: `apps/evidence_prep/app.py`, `_build_dedup_key()`.

Canonical URL, video ID, arXiv ID, and exact same-title/day duplicate handling
is substantially safer than semantic filtering. Preserve it, but retain a
duplicate ledger pointing to the canonical record.

### 6.3 Story mapping

#### MAP-01: Semantic clustering uses strict lexical anchors (`P1`)

Location: `apps/story_mapping/clusterer.py`, `same_story_reason()`.

Current behavior: embedding similarity is accepted only with fixed title and
story-token overlap counts.

Risk: differently worded reports about the same event remain separate. The
latest run had 25 singleton stories and only one merged pair.

Action: use embeddings and objective time/source rules to generate candidate
pairs. Use structured LLM adjudication for ambiguous same-event, follow-up, and
broader-arc relationships.

#### MAP-02: Source-group rules prevent valid merges (`P1`)

Location: `apps/story_mapping/clusterer.py`, `_semantic_pair_allowed()`.

Current behavior: only configured source groups can participate in semantic
merging. Research and community sources can be prevented from joining news
coverage of the same story.

Risk: corroborating records are split across stories and the writer loses
multi-source context.

Action: source group should be evidence for adjudication, not a categorical
merge ban.

Implemented: source-group merge bans were removed. Candidate-pair context now
flows to bounded semantic adjudication without excluding research or community
records by source category.

#### MAP-03: Singleton storyworthiness is a hard numeric gate (`P0`)

Location: `apps/story_mapping/clusterer.py`,
`_is_storyworthy_singleton()`.

Current behavior: different source groups require fixed content lengths, stars,
HN score, or comment counts. Five available records were dropped across six
runs.

Risk: a new project, concise release, or quiet but important research story is
deleted before editorial selection.

Action: retain every usable singleton. Supply traction and content quality to
editorial triage as features.

Implemented: every triage-approved singleton is retained. The old helper and
the misleading `dropped_singleton_count` result field were removed rather than
left dormant.

#### MAP-04: Event types are assigned by regex and source assumptions (`P1`)

Location: `apps/story_mapping/signals.py`, `_classify_event_type()`.

Current behavior: every YouTube record defaults to `tutorial_or_demo`, every
GitHub URL to community tooling, and title prefixes decide tutorials and
updates.

Risk: interviews, announcements, investigations, and explainers are
misclassified. Packaging later consumes these labels.

Action: keep lexical signals as hints. Let the story-label model own the final
event and tutorial classifications.

#### MAP-05: Hardcoded entity/product aliases go stale (`P2`)

Location: `apps/story_mapping/signals.py`.

Current behavior: a fixed alias map recognizes a small set of organizations
and products.

Risk: new companies, models, and ambiguous product names receive weak story
keys and poor clustering.

Action: use the alias list only for deterministic normalization after entity
extraction. Make aliases config data and let structured semantic extraction
identify unknown entities.

#### MAP-06: Fixed additive ranking is acting as editorial judgment (`P0`)

Location: `apps/story_mapping/ranker.py`.

Current behavior: authority, source count, recency, content length, stars,
comments, tutorial flags, source relationship, and penalties are added into one
score and mapped to high/medium/low buckets.

Risk: arbitrary weights create false precision. Source-type and self-published
penalties can outrank actual audience value. The latest Asus sale example
demonstrates that a medium score is not an editorial guarantee.

Action: keep objective measurements in a `ranking_features` object. Replace the
formula as the authoritative ranking with an episode-aware editorial ranker.

#### MAP-07: LLM story labels are partially overwritten by code (`P1`)

Location: `apps/story_mapping/story_label.py`, `validate_story_label()`.

Current behavior: code rewrites `is_tutorial` and `is_event_update` from action
and story-type enums after the LLM has evaluated the records.

Risk: contextual model judgment is discarded by categorical coupling.

Action: validate enum shape only. Preserve the model output, confidence,
rationale, and prompt version.

#### MAP-08: Story-label context is first-N and character capped (`P2`)

Location: `apps/story_mapping/story_label.py`, `_build_user_prompt()`.

Current behavior: only the first configured records and first 1,800 fingerprint
characters per record are shown.

Risk: the most relevant corroboration may be omitted because of order rather
than semantic value.

Action: select context by source diversity and semantic relevance to the
cluster identity. Record exactly which source chunks were shown.

### 6.4 Roundup selection and packaging

#### PKG-01: Packaging trusts the fixed story rank (`P0`)

Location: `apps/video_packaging/formats/roundup.py`,
`select_roundup_stories()`.

Current behavior: only the first `candidate_limit` stories by fixed rank are
considered.

Risk: a bad upstream score permanently hides better stories from episode-level
selection.

Action: give an editorial selector the full bounded candidate slate plus
ranking features. Code should validate returned IDs, not choose their meaning.

#### PKG-02: Noise and tutorial flags are hard exclusion gates (`P0`)

Location: `apps/video_packaging/formats/roundup.py`, `_rejection_reasons()`.

Current behavior: `is_noise`, `is_tutorial`, and priority bucket can reject a
story before the episode slate is considered.

Risk: a useful tutorial, demo, or technical release is excluded even when it
would make the best story for the audience.

Action: treat these as editorial features. A selector can reject them with a
reason, but the record stays in the decision ledger.

#### PKG-03: Diversity keys are assumed to be semantically correct (`P1`)

Location: `apps/video_packaging/formats/roundup.py`.

Current behavior: entity, product, and canonical-event caps use upstream labels
without confidence.

Risk: a wrong entity or event key can reject an unrelated story.

Action: keep hard maximum story count. Apply diversity as a selector objective
or a post-selection validation that can request a targeted replacement.

#### PKG-04: Minimum-story failure has no editorial reserve list (`P1`)

Location: `apps/video_packaging/app.py`.

Current behavior: the run fails when too few stories survive the fixed filters.

Risk: usable low-bucket candidates exist but are not reconsidered.

Action: editorial selection should return selected and reserve stories in
order. Packaging can deterministically backfill from that approved reserve list
without inventing a choice.

### 6.5 Script generation

The native script-generation path is currently much healthier than the stages
before it. It receives selected stories with full records and now limits hard
checks to structural integrity and provenance.

#### SCR-01: Native structural validation is appropriate (`KEEP`)

Location: `apps/script_generation/formats/roundup/checks.py`.

Keep checks for section count/order, beat identity, non-empty narration,
selected-story ownership, source-key ownership, deterministic projections,
title-card contract, bounded loops, and fingerprints.

The visual-direction substring check may be narrowed if it flags natural spoken
language, but it is not an editorial scoring system.

#### SCR-02: Source truth ranking uses lexical categories (`P2`)

Location: `apps/script_generation/formats/roundup/source_truth.py`.

Current behavior: sentence keywords classify limitations, mechanisms, results,
examples, and events. Fixed ordering and context caps decide what reaches each
prompt.

Risk: this no longer blocks script approval, but it can hide the most useful
details or misdescribe their narrative function.

Action: preserve full records. Retrieve source chunks per story engine and beat
using semantic relevance, source diversity, and explicit model selection.
Treat truth types as model hints, not factual categories proven by regex.

#### SCR-03: Any number creates a chart hint (`P1`)

Location: `apps/script_generation/formats/roundup/asset_hints.py`.

Current behavior: a broad metric regex marks `chart` as available whenever a
number-like string appears in a title, summary, or description.

Risk: dates, model names, prices, token counts, and unrelated numbers can
encourage decorative or misleading charts.

Action: a chart hint must carry the exact source text, record key, meaning,
units, comparison basis, and whether a quantitative relationship truly exists.

#### SCR-04: Manual plain-script fallback invents story boundaries (`P1`)

Location: `handoffs/chatgpt_script_parser/app.py`, `_partition_script()`.

Current behavior: unstructured paragraphs are distributed across stories by
position and count.

Risk: narration can be assigned to the wrong story and therefore to the wrong
source and visual context.

Action: production manual handoffs must provide canonical section IDs. Keep the
plain-text fallback only in an explicitly selected lab/manual recovery mode and
mark it not ready for production media.

#### SCR-05: Manual beat inference overstates grounding (`P0`)

Location: `handoffs/chatgpt_script_parser/app.py`, `_build_beats()`.

Current behavior: inferred beats receive every allowed record key for the
story when the response provides none. Beat type and function are assigned by
position.

Risk: downstream visuals believe each inferred beat is supported by every
story source even when no such link was provided.

Action: require source keys per structured beat or leave support empty and
request semantic alignment. Never fill all source keys as proof.

### 6.6 Metadata and voiceover

#### META-01: Metadata output bounds are appropriate (`KEEP`)

Title option counts, tag counts, chapter title length, deduplication, and raw
domain tag filtering are presentation constraints, not editorial story
deletion. Keep them.

Metadata prompt previews are capped, so ensure the final full script remains the
source of truth and that title generation represents the complete episode.

#### VO-01: Beat-aware voiceover structure is appropriate (`KEEP`)

Voiceover chunk length, provider chunking, WAV validation, section/story/beat
identity, and observed timing are operational constraints. Keep them.

Do not ask voiceover to reconstruct sections from anonymous prose. Production
should continue to require the canonical script package and fingerprint.

### 6.7 Visual planning

#### VIS-01: Uncovered ranges receive deterministic semantic scenes (`P0`)

Location: `visuals/planner/app.py`, `_stitch_section()`,
`_deterministic_scenes_for_range()`, and `_fallback_candidate_for_slice()`.

Current behavior: any uncovered narration range is filled by keyword rules,
visual-intent strings, group position, and modulo-based scene rotation.

Risk: a structurally successful LLM plan can still contain many semantically
unplanned scenes that do not match the narration.

Action: deterministic code may assign timing, split duration, and preserve
coverage. Missing semantic plans must trigger a targeted LLM repair or an
explicitly safe exact-text/source fallback, not a guessed chart or diagram.

#### VIS-02: Visual payload helpers fabricate data and relationships (`P0`)

Location: `visuals/planner/app.py`, payload fallback helpers.

Confirmed examples in code include:

- Bar values `82`, `64`, `48`, and `36` when no metrics exist.
- Capability rows with invented `high`, `med`, `low`, `wide`, and `yes` values.
- Timeline events such as `Signal appears`, `Momentum builds`, and `T+1`.
- Radar signal values beginning at `88`.
- Default metric value `AI`.
- Default rising trend direction.
- Default nodes `AI`, `Developers`, and `Users` connected by `connects`.
- Generic decision branches and developer/SDK/model/user workflow steps.

Risk: rendered graphics can look polished while making claims the script and
sources never made.

Action: delete semantic placeholder generation for production. A quantitative
or relational scene is valid only when its complete payload is supplied by the
planner and linked to narration/source evidence. Otherwise request repair or
choose a non-claiming scene.

#### VIS-03: Scene caps can replace meaning with an unrelated kind (`P0`)

Location: `visuals/planner/app.py`, `_fallback_non_capped_kind()`.

Current behavior: when a scene-kind cap is reached, code chooses the first
available kind from a global preference list.

Risk: a requested diagram can become B-roll, a chart, a matrix, or another
unrelated scene solely because of count.

Action: scene mix caps should produce a planner repair request. Safe
substitution must come from an explicit compatibility map and retain the same
semantic payload.

#### VIS-04: Visual source context is order-capped (`P1`)

Location: `visuals/planner/app.py`, source-index and story-prompt builders.

Current behavior: bounded record text is chosen primarily by record order and
character cap.

Risk: the planner may receive the wrong part of a long record for the active
beat.

Action: retrieve story-local source chunks against the active beat and visual
goal. Include exact source keys and quoted support spans in the planning call.

#### VIS-05: Manual visual parser repairs can change semantics silently (`P1`)

Location: `handoffs/chatgpt_visual_plan_parser/app.py`,
`_close_timeline_gaps()` and `_compact_semantic_scenes()`.

Current behavior: the parser stretches neighboring scenes, inserts filler, and
merges short graphic scenes based on timing, kind, or headline equality.

Risk: large repairs can turn an incomplete visual plan into an apparently valid
one without a semantic review.

Action: keep small timing normalization. Return `needs_repair` when semantic
coverage changes, and require targeted re-planning before production.

#### VIS-06: Timeline and provenance checks are appropriate (`KEEP`)

Keep hard validation for supported render kinds, source URL/key ownership,
maximum scene duration, complete audio coverage, gap/overlap checks, and parent
fingerprints.

### 6.8 Media discovery and asset resolution

#### MED-01: Media ranking is mostly lexical and the threshold is permissive (`P0`)

Location: `visuals/media_discovery/ranking.py` and
`visuals/media_discovery/app.py`.

Current behavior: semantic relevance is token overlap weighted at 36 percent.
Aspect ratio, resolution, provider quality, rank, and license can let a
zero-relevance asset exceed a low selection threshold.

Observed consequence: unrelated historical and weather imagery has been
selected for named people and privacy stories.

Action: use metadata retrieval only as candidate generation. Add image-text or
vision-model reranking against exact `must_show`, `must_avoid`, entity identity,
story, and beat context. Require an independent semantic minimum.

#### MED-02: Broad fallback queries dilute scene intent (`P1`)

Location: `visuals/media_discovery/app.py`, `_queries_for_scene()`.

Current behavior: story title, broad visual intent, and a script excerpt are
always added to explicit search queries.

Risk: precise queries are diluted and generic but technically attractive media
wins.

Action: search explicit intent first. Add fallbacks only as a separate attempt
with a lower confidence class.

#### MED-03: Video clip start is pseudo-random (`P1`)

Location: `visuals/media_discovery/app.py`, `_prepare_video_clip()`.

Current behavior: clip start is derived from the scene ID hash.

Risk: the downloaded video may be relevant overall while the selected seconds
show the wrong moment.

Action: use provider timestamps, captions, shot sampling plus vision ranking, or
start-at-zero only when the asset contract says the whole clip is generic.

#### MED-04: Missing media silently becomes kinetic text (`P2`)

Location: `visuals/media_discovery/app.py`, `_apply_explicit_fallback()`.

Current behavior: unresolved media becomes a text scene and the pipeline can
continue.

Risk: repeated text fallbacks make the final video structurally complete but
creatively weak.

Action: retain fallback metadata, but set a configurable episode fallback
budget. Exceeding it should require review or re-planning.

#### AST-01: Text badges are reported as resolved logos (`P0`)

Location: `visuals/generators/logo_reveal/resolver.py`.

Current behavior: a generated initials SVG is returned with status `resolved`
when a real logo is unavailable. Substring alias matching can also choose the
wrong brand icon.

Risk: fabricated or misleading brand identity appears as an actual logo.

Action: distinguish `verified_logo`, `verified_favicon`, `simple_icon`, and
`text_identity_fallback`. A text badge must never be presented as a real logo.

#### AST-02: Logo resolver config is not fully honored (`P1`)

Location: `visuals/asset_resolver/app.py`, `_resolve_logo()`.

Current behavior: local logo directory is passed to the resolver, but configured
simple-icons, favicon, and text-fallback switches are not passed or enforced.

Action: implement the declared resolution chain and expose resolution quality
in the asset manifest.

#### AST-03: Screenshot target failure still counts as resolved (`P1`)

Location: `visuals/generators/source_screenshot/web_capture.py` and
`visuals/asset_resolver/app.py`.

Current behavior: a page capture can succeed while `target_found` is false; the
asset resolver still marks the screenshot resolved.

Risk: the video shows the article top or unrelated page area while narration
refers to a specific claim.

Action: make target-match quality explicit. A source-proof scene should fail or
request repair when its target is not found. A generic article-establishing
scene may allow page-top capture only when configured.

### 6.9 Rendering, assembly, and orchestration

#### SAFE-01: Artifact fingerprint selection is appropriate (`KEEP`)

Keep run ID, script fingerprint, voiceover fingerprint, visual-plan
fingerprint, and parent-lineage validation. Never return to newest-file-wins.

#### SAFE-02: Render validation and bounded parallelism are appropriate (`KEEP`)

Keep supported scene contracts, maximum render duration, output-file checks,
retry limits, worker limits, ffprobe validation, and resolution settings.

#### SAFE-03: Final audiovisual assembly validation is appropriate (`KEEP`)

Keep ordered scene coverage, real clip duration, audio duration, stream
presence, and final synchronization checks.

These checks validate mechanics. They do not prove that a scene is editorially
correct, which is why semantic validation must happen before rendering.

## 7. Root Cause

The current pipeline compounds both false negatives and false positives.

False-negative path:

```text
collector keyword filter
  -> evidence topic/content filter
  -> singleton gate
  -> fixed rank penalty
  -> priority-bucket/tutorial/noise exclusion
  -> script writer never sees the record
```

False-positive visual path:

```text
broad numeric or keyword hint
  -> deterministic scene choice
  -> invented chart/flow/map payload
  -> lexical media selection or text-logo fallback
  -> renderer validates files and timing
  -> polished but semantically wrong final video
```

A successful run currently proves mechanical completeness more strongly than
editorial or semantic correctness.

## 8. Target Pipeline

The recommended content path is:

```text
broad news acquisition
  -> reversible extraction and normalization
  -> AI editorial triage
  -> exact dedupe plus semantic story mapping
  -> AI roundup slate selection
  -> deterministic format packaging
  -> story-local creator-led script generation
  -> beat-aware voiceover
  -> beat-local semantic visual planning
  -> semantically verified media and grounded asset resolution
  -> rendering and sampled human visual review
  -> fingerprint-validated assembly
```

### 8.1 Broad news acquisition

Acquisition should optimize recall, not final precision.

- Use source APIs, feeds, queries, and generous caps to find candidates.
- Hard reject malformed or provably unusable records only.
- Store every scanned candidate in a durable candidate ledger.
- Separate `retrieved`, `fetch_failed`, `quarantined`, and `hard_rejected`.
- Preserve raw provider metadata and timestamps.

### 8.2 Reversible evidence preparation

Evidence prep should normalize and describe quality.

- Canonicalize URLs and timestamps.
- Extract body, summary, and source metadata.
- Preserve raw and cleaned content.
- Add extraction-quality and date-confidence flags.
- Remove exact duplicates with canonical pointers.
- Do not decide topic relevance, newsworthiness, tutorial value, or noise.

### 8.3 AI editorial triage

Add a self-contained app boundary:

```python
def run(input_json: dict) -> dict:
    ...
```

Suggested location:

```text
src/pipeline/apps/editorial_triage/
```

The app receives prepared candidates and channel/profile context. It returns a
structured decision for every candidate:

```json
{
  "record_key": "record_...",
  "topic_relevance": "high|medium|low|uncertain",
  "newsworthiness": "high|medium|low|uncertain",
  "audience_value": "high|medium|low|uncertain",
  "content_usability": "full|partial|metadata_only|unusable",
  "likely_content_type": "news|research|tutorial|opinion|promotion|community_project|other",
  "novelty": "new_event|follow_up|evergreen|unknown",
  "confidence": 0.0,
  "reason": "...",
  "possible_story_keys": [],
  "recommended_action": "advance|reserve|quarantine"
}
```

Requirements:

- Pydantic structured output.
- Config-driven provider, model, prompt, batch size, and bounded retries.
- One decision per supplied record key.
- No generated replacement content.
- No record deletion from the returned package.
- A reserve pool for uncertain or lower-priority candidates.
- Full decision provenance and LLM call logs.
- Batch prompts sized by source chunks, not arbitrary first-N record order.

The model should rank context, not imitate a keyword filter. Prompt examples
must include difficult cases such as language-model tokens versus crypto,
tutorials with strong viewer value, low-star new tools, and non-AI product
deals containing incidental AI language.

### 8.4 Semantic story mapping

Story mapping should use a hybrid design:

- Code performs exact duplicate detection.
- Embeddings generate possible related-record pairs.
- Time is an eligibility/context feature, never a merge reason by itself.
- A structured LLM adjudicates ambiguous pairs or candidate clusters.
- Every usable singleton becomes a story candidate.
- The output carries all records, triage decisions, and cluster rationale.

The LLM should distinguish:

- Same event.
- Follow-up to the same event.
- Broader story arc.
- Similar topic but different story.
- Unrelated.

### 8.5 AI roundup slate selection

Add a separate editorial selection boundary or make it an explicit LLM-owned
substage before deterministic video packaging.

Recommended final location:

```text
src/pipeline/apps/editorial_selection/formats/roundup/
```

The selector receives all bounded story candidates, their records, triage
features, source diversity, and channel promise. It returns:

- Selected story IDs in editorial order.
- Lead, major, and brief recommendations.
- A story-specific selection reason.
- Rejected and reserve story IDs with reasons.
- Confidence and any human-review warning.
- Episode compatibility notes without forcing a universal thesis.

Code then validates that IDs exist, maximum story count is respected, and
duplicates are not selected accidentally. It does not decide which story is
interesting.

### 8.6 Deterministic video packaging

After editorial selection, video packaging remains simple:

- Copy selected full story objects.
- Attach selected order and role.
- Add format contract and script app route.
- Preserve selected, reserve, and rejected decision provenance.
- Do not rescore or semantically reject stories.

### 8.7 Story-local script context

Each story writer receives:

- One selected story and all of its records.
- Raw and cleaned source content references.
- Semantically selected source chunks relevant to that story.
- The editorial selection reason and intended viewer payoff.
- Source identity and relationship metadata.
- A bounded list of grounded visual opportunities.

The writer decides which facts do narrative work. Code validates only identity,
structure, source ownership, and artifact provenance.

### 8.8 Voiceover and visual production

The canonical script remains section and beat aware.

- Voiceover preserves section, story, and beat IDs.
- Synthesized audio timing is authoritative.
- The visual planner receives one active beat or coherent beat group plus its
  story-local sources.
- The planner returns a complete semantic payload for every requested scene.
- Code maps semantic scenes to exact audio timing.
- The renderer animates supplied values and relationships but never invents
  them.

## 9. Data Retention and Decision Ledger

Every stage that narrows candidates must return both the surviving objects and
the decision ledger.

Minimum ledger entry:

```json
{
  "object_id": "...",
  "stage": "editorial_triage",
  "decision": "advance|reserve|quarantine|hard_reject",
  "reason_code": "...",
  "reason": "...",
  "confidence": 0.0,
  "decision_owner": "code|llm|human",
  "model": "...",
  "prompt_version": "...",
  "parent_ids": []
}
```

Required run-level funnel telemetry:

- Retrieved candidate count by source.
- Fetch failure count by source and reason.
- Hard reject count by objective reason.
- Quarantine count by quality reason.
- Triage advance/reserve counts.
- Story cluster and singleton counts.
- Selected/reserve/rejected story counts.
- Script context record and chunk counts per story.
- Visual repair, fallback, and unresolved counts.
- Media semantic confidence and asset-quality class.

No stage should report only `filtered_out_count` for contextual decisions.

## 10. Implementation Priorities

The implementation sequence should follow information loss, not folder order.

### Phase 0: Freeze regression cases (`P0`)

Implementation status: implemented. Content-triage fixtures cover the Claude
token false positive, a consumer deal, a low-star useful project, a valuable
tutorial, a missing-date official item, a recoverable title/body mismatch,
crypto noise, and a reliable outside-window rejection. Visual regressions cover
invented rich payloads, source ownership, manual-plan repair state, contextual
media verification, and bounded B-roll clip sampling.

Deliverables:

- Add candidate-triage fixtures for obvious keep, reject, and uncertain cases.
- Include the Claude Code token story as a required retain case.
- Include an incidental-AI product deal such as the Asus sale as a low-value or
  reserve case.
- Include a low-star but clearly useful new AI tool.
- Include a tutorial that is valuable enough to select.
- Include a short official release and a title/body mismatch that remains
  recoverable.
- Add visual fixtures that fail if numeric values or graph relationships are
  invented.

Exit condition: current known false positives and false negatives are
reproducible without calling live providers.

### Phase 1: Stop irreversible context loss (`P0`)

Implementation status: implemented and active.

- News collection returns `data.candidate_ledger` alongside its `records`
  stream. Collector lexical relevance and listing suspicion are telemetry;
  objective rejections remain explicit.
- Evidence prep now returns one complete prepared `records` stream plus a
  `decision_ledger`. Prepared records retain `raw_content`, `cleaned_content`,
  quality flags, and legacy-filter telemetry; there is no second semantic
  approval subset.
- Missing dates, short official content, title mismatch, listing suspicion, and
  topic regex decisions remain recoverable candidates instead of being erased.
- GitHub uses repository activity time and no longer requires a star floor in
  search. YouTube uses the frozen run-window start and retains metadata when a
  transcript is unavailable.
- Story clustering no longer deletes weak singletons.

Story mapping now consumes the reversible candidate stream together with
authoritative triage decisions. Collector/provider retrieval caps remain
explicit acquisition resource bounds; this system does not claim to archive
every result a provider could return.

Deliverables:

- Preserve collector candidate ledgers.
- Preserve raw plus cleaned evidence content.
- Fix GitHub and YouTube timestamps.
- Convert missing date, short content, title mismatch, and ambiguous listing
  checks to non-blocking quality hints.
- Disable hard semantic topic deletion in evidence prep.
- Remove singleton hard deletion.

Rollout state: the comparison period is complete and the decision ledger is
inspectable. The production notebook now blocks when authoritative triage does
not produce a usable handoff rather than silently reverting to legacy filters.

Exit condition: no contextual record is permanently deleted by a keyword,
content length, title-overlap ratio, star count, or comment threshold.

### Phase 2: Add AI editorial triage (`P0/P1`)

Implementation status: implemented and authoritative.

- `apps/editorial_triage/` uses an app-local Pydantic v2 contract, versioned
  prompts, LangChain structured output, a provider-only LLM client, separate
  in-memory logging, batching, and bounded retry attempts.
- It evaluates evidence candidates plus collector-level quarantines and returns
  `advance`, `reserve`, and `quarantine` pools with reasons and confidence.
- Unresolved batches become recoverable `reserve` decisions and return visible
  partial state; they do not masquerade as affirmative editorial decisions.
- `content_pipeline.ipynb` writes the result under
  `output/runs/{run_id}/editorial_triage/` and passes it with reversible
  prepared records to story mapping.

Deliverables:

- Build `apps/editorial_triage/` with Pydantic structured output.
- Add config-driven model/provider/prompt/retry settings.
- Batch candidates while preserving one decision per record.
- Return advance, reserve, and quarantine pools.
- Add audit summaries and LLM call logs.

Exit condition: the fixture decisions are sensible, every input record has a
decision, and uncertain records remain recoverable.

### Phase 3: Replace fixed story ranking and packaging filters (`P1`)

Implementation status: implemented and active.

- Exact pair identity and objective time eligibility remain deterministic;
  ambiguous related pairs use bounded structured LLM adjudication.
- When pair adjudication is deliberately disabled, semantic candidates remain
  separate and are reported as `uncertain`; the runtime has no lexical or
  embedding-threshold fallback that can merge them contextually.
- Story scores and priority buckets remain observable telemetry only.
- `apps/editorial_selection/formats/roundup/` chooses and orders the slate with
  structured LLM output, reasons, reserve IDs, and bounded per-call context.
- Candidate overflow uses bounded, balanced LLM screening rounds followed by a
  cross-batch final selector; a numeric call-size limit never rejects the whole
  run or chooses which story to discard.
- Screening returns only an explicit semantic shortlist. Every non-shortlisted
  story remains a recoverable reserve, avoiding brittle model-authored coverage
  ledgers and deterministic contextual rejection.
- Video packaging validates selected IDs, caps, order, and format structure but
  does not independently rescore or semantically reject the approved slate.

Deliverables:

- Hybrid cluster candidate generation plus semantic adjudication.
- Remove source-group merge bans and code-overwritten semantic labels.
- Convert fixed rank score to non-authoritative features.
- Add episode-aware roundup editorial selection with a reserve list.
- Keep packaging structural only.

Exit condition: story order is explainable as an editorial decision, not a sum
of arbitrary points, and packaging never fails while an approved reserve story
exists.

### Phase 4: Improve story-to-writer context (`P1/P2`)

Implementation status: implemented for the active contract, with semantic
vector retrieval left as an optional future optimization.

- Every story writer receives the full selected story records, so a compact
  truth index is not the only available source context.
- App-local truth indexes prioritize source-diverse article body material and
  preserve source/truth references for focused writer and reviewer context.
- Native and manual scripts normalize to explicit sections and audiovisual
  beats; downstream modules never infer story boundaries from prose.
- Manual grounding aligns supplied source references with canonical selected
  records instead of assigning every story source to every beat.

Deliverables:

- Replace first-N and lexical truth context selection with story/beat semantic
  chunk retrieval.
- Require structured manual section and beat boundaries for production.
- Stop assigning every story source to every inferred manual beat.
- Make chart hints source-linked and semantically complete.

Exit condition: each story writer can see the relevant source context and each
beat's claimed support is explicit rather than inferred by position.

### Phase 5: Remove semantic fabrication from visual planning (`P0`)

Implementation status: implemented.

- Production code no longer synthesizes chart values, benchmark values,
  timelines, matrix cells, graph nodes/edges, or process steps from generic
  text heuristics.
- Provider structured output uses a strict schema with dynamic payload JSON,
  then performs app-side nested payload and grounding validation.
- Native planning, manual-plan parsing, and render preflight share the same
  render-kind validator, preventing a structurally incomplete payload from
  entering through a less common path.
- Incomplete rich scenes receive bounded targeted replanning; they are not
  repaired with fabricated semantic data.
- Uncovered time may use exact narration-derived kinetic text or exact source
  proof only. Manual plans needing semantic ownership or substantial timing
  repair return `needs_repair`.
- Remotion components no longer contain demo metrics, entities, relationships,
  timelines, process steps, or generic editorial copy as production defaults.

Deliverables:

- Delete invented production values, relationships, timelines, matrix cells,
  and workflow steps.
- Add targeted per-scene planning repair.
- Replace global scene-kind substitution with compatible semantic fallback.
- Add grounded payload validators for quantitative and relational scenes.
- Mark substantial manual-plan repairs as `needs_repair`.

Exit condition: every rendered value, node, edge, label, quote, and source image
can be traced to the script, selected records, or an explicitly non-factual
visual metaphor.

### Phase 6: Add semantic media and asset verification (`P1`)

Implementation status: implemented; external B-roll remains profile-disabled
until an operator explicitly enables its provider/cost policy.

- Candidate image/video retrieval is followed by a bounded structured vision
  decision. Exact person/product/event identity requires explicit
  confirmation, and verifier failure rejects the candidate by default.
- Lexical and provider scores rank the candidate pool but cannot veto a
  candidate that passed semantic vision verification. They become eligibility
  gates only when semantic verification is deliberately disabled.
- Long videos are sampled into bounded candidate windows; a second structured
  vision call selects a supplied window instead of using a random offset.
- Logo resolution exposes actual quality classes, source screenshots report
  target-text misses, and episode fallback usage is visible and bounded.
- Final assembly feeds a sampled contact-sheet review artifact into the manual
  publish handoff.

Deliverables:

- Add vision/image-text reranking after provider search.
- Add identity-sensitive rules for named people, products, and events.
- Replace random clip start with semantic clip selection.
- Implement configured logo resolution and quality classes.
- Enforce screenshot target confidence for source-proof scenes.
- Add an episode fallback budget and contact-sheet review.

Exit condition: technically attractive but irrelevant assets cannot pass on
resolution and aspect ratio alone.

### Phase 7: Update canonical architecture after cutover (`P2`)

Implementation status: implemented.

Deliverables:

- Update `docs/current_system_architecture.md` after new stages are active.
- Update notebook flow and frozen run config.
- Retire obsolete semantic-filter behavior rather than carrying a hidden legacy
  selection path beside the authoritative flow.
- Document migration and rollback using decision ledgers, not compatibility
  shims.

## 11. Verification Strategy

### Deterministic tests

Keep tests for:

- Contract validation.
- Reliable time-window behavior.
- Exact deduplication and canonical pointers.
- Source/story/beat ownership.
- Fingerprint lineage.
- Scene timing and coverage.
- Media existence, dimensions, duration, and stream presence.
- Bounded LLM and render retries.

### Semantic regression tests

Use model-backed or recorded-output fixtures for:

- Record relevance and uncertainty.
- Tutorial and promotion context.
- Story identity and follow-up relationships.
- Roundup selection quality.
- Source-chunk relevance.
- Visual scene and payload grounding.
- Media semantic match.

Do not assert that one exact prose sentence or one exact story order is always
correct. Assert required inclusions, prohibited category mistakes, traceable
IDs, confidence behavior, and decision completeness.

### Human evaluation

Use pairwise or rubric review for:

- Whether the selected slate is worth watching.
- Whether each script has a clear story engine and viewer payoff.
- Whether the narration and visual meaning match moment by moment.
- Whether the final video feels like a creator-led YouTube video rather than a
  report or presentation.

## 12. Non-Goals

This redesign does not mean:

- Passing every raw record to one enormous prompt.
- Removing collection windows or exact duplicates.
- Letting an agent invent source content or rewrite source records.
- Trusting one LLM score without reasons, confidence, and a reserve pool.
- Removing structural script, timing, provenance, or media checks.
- Treating all overclaiming as acceptable for engagement.
- Building an unbounded autonomous loop.
- Replacing human creative review with another numeric formula.

## 13. Cutover State

The production notebook now follows the target ownership boundaries:

- collection and evidence preparation preserve candidates and decision ledgers
- authoritative LLM triage owns candidate meaning
- semantic story mapping owns identity, including bounded ambiguous-pair review
- LLM editorial selection owns the roundup slate and order
- packaging owns structure only
- story-local writers receive full selected records
- visual planning rejects invented semantic payloads
- contextual media passes semantic candidate and clip-window verification
- final video review includes a sampled contact sheet

The implementation is complete enough for a fresh end-to-end production
evaluation. That run still matters: deterministic and recorded-output tests can
prove contracts, lineage, bounded behavior, and known regressions, but they
cannot prove that a new slate, script, voice, or final edit is creatively good.
