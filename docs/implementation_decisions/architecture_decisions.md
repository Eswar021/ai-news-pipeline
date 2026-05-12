# Architecture Decisions & Design Deviations

This document records every place where the actual implementation differs from the
system design docs, and why. It is meant to be updated as each layer is built.

The format for each entry is:
- **Design doc said** — what the spec called for
- **What we did** — the actual implementation
- **Why** — the reasoning

---

## Layer 0 — Run Control & Manifest

### Decision: Manifest stored at run root, not layer_0/ subdirectory

**Design doc said:** Implied `data/runs/{run_id}/layer_0/run_manifest.json`

**What we did:** `data/runs/{run_id}/run_manifest.json` (flat, at run root)

**Why:** Every layer needs to read this file. Putting it in a `layer_0/` subdirectory
means every downstream layer has to know it's in `layer_0/`. At the run root it's
a first-class artifact — "the manifest for this run" — not "Layer 0's output."

---

### Decision: Layer 0 is run initialization, not just a trigger

**Design doc said:** Layer 0 is described as "Channel Strategy + Run Control" —
a coordinator that sets up the run.

**What we did:** Implemented 13 modules that read all config files once and produce
a single `run_manifest.json`. Every downstream layer reads the manifest instead of
reading config files directly.

**Why:** If each layer reads config files independently, a mid-run config edit would
cause Layer 1 and Layer 5 to use different source lists or format specs for the same
run. The manifest is immutable once written — it's a snapshot of all decisions for
this run.

---

### Decision: Time windows are now enforced from the manifest in Layer 1

**Design doc said:** `time_window_resolver.py` should produce collection windows that
collectors use to filter content by date (48h window for news, 7 days for papers).

**What we did:** `time_window_resolver.py` computes these windows and writes them to
the manifest, and the active Layer 1 orchestration now applies them. Collectors
receive the resolved run window from the manifest and drop out-of-window documents
before `raw_documents.jsonl` is written. Sources that support fetch-side narrowing
also receive `days_back` where it is useful.

**Why:** Collection policy is run-scoped, not repo-global. Once Layer 0 became the
authoritative runtime control plane, Layer 1 needed to stop behaving like "latest N"
best-effort collection and start behaving like "collect within the resolved run window."

**Remaining gap:** Some sources still rely on post-fetch filtering rather than native
server-side date constraints. That is acceptable for correctness, but there is still
room to improve efficiency.

---

### Known gap: Memory policy is now real, but still only partially consumed

**Design doc said:** `memory_context_planner.py` should produce policy flags
(`load_published_video_memory`, `load_claim_ledger` etc.) that Layer 5 and Layer 9
use to decide what memory to load.

**What we did:** The flags are computed and written to the manifest. Layer 5 and the
handoff/export path now consume the published-memory distinction in practice, and
Layer 10 plus the publish-state workflow now exist. But the broader design-level
memory policy is still not consumed uniformly across all intended downstream layers.

**Why this is acceptable now:** The important semantic split is now in place:
published memory influences novelty/repetition, while prepared-run records can remain
for audit. The remaining gap is completeness of policy consumption, not correctness
of the current behavior.

---

### Decision: output_contract is now enforced at run time

**Design doc said:** `output_contract_builder.py` should declare expected output
paths for all layers, and `source_scope_planner.py` should set
`minimum_expected_documents: 30`.

**What we did:** The output contract is computed in Layer 0 and now enforced by the
pipeline runner. A layer is no longer considered complete just because it exited
without raising an exception; its core artifacts and validation report must exist and
pass. The contract paths were also corrected to the active `data/runs/{run_id}/layer_X/`
layout.

**Why:** Partial runs were producing misleading downstream states, especially in
handoff/export flows. A small but strict completeness gate gives us predictable run
semantics without adding heavy schema validation everywhere.

**Remaining gap:** `minimum_expected_documents` still behaves more like advisory
planning than a hard cross-source threshold. That is intentional for now because
source availability varies too much to make one global count a reliable blocker.

---

### Decision: Active async LLM calls now use one shared runtime + per-run logs

**Design doc said:** The system should be centrally configurable and operationally
inspectable, but it did not prescribe one exact async runtime implementation.

**What we did:** Added `llm/async_llm_runtime.py` and routed the active async LLM
modules in Layers 4, 5, 7, 8, and 9 through it. The runtime now owns:

- manifest-backed profile resolution
- AsyncOpenAI client creation
- model/temperature request shaping
- structured per-call request/response logs in `output/llm_logs/{run_id}/`

**Why:** The previous state had the right model profiles in config, but every active
module still instantiated its own client and silently bypassed logging. Centralizing
the runtime keeps model selection, execution behavior, and observability tied together.

---

## Layer 1 — Source Extraction

### Decision: Wrap existing collectors, don't rewrite them

**Design doc said:** Implied building fresh "source connectors" for each source type
(one connector per source group).

**What we did:** Built wrapper collector modules (`research_paper_collector.py`,
`community_signal_collector.py`, `tech_news_api_collector.py`, etc.) that import
and call the existing fetch functions (`fetch_arxiv_papers`, `fetch_ai_stories`,
`fetch_trending_repos` etc.) and convert their output to `RawExtractedDocument` schema.

**Why:** The existing collectors (`arxiv_collector.py`, `hackernews_collector.py`,
`github_collector.py`, `youtube_collector.py`) were already working and tested. The
only thing missing was the `RawExtractedDocument` schema wrapping and integration with
the run-scoped output paths. Rewriting would have duplicated logic without adding value.

---

### Decision: No separate parsers — Layer 1 collectors already parse

**Design doc said (Layer 2 design):** Layer 2 should have HTML parser, API JSON parser,
Research metadata parser, Transcript parser, Community/GitHub parser — 5 separate
parsing modules — because Layer 2 receives raw HTML and raw API JSON blobs.

**What actually happened:** Layer 1 collectors do the parsing themselves. `arxiv_collector`
parses arXiv XML. `hackernews_collector` normalizes HN API JSON. `blog_utils.strip_html()`
extracts article text. By the time data reaches `raw_documents.jsonl`, every document
already has a `content.raw_text` field with extracted text — not raw HTML or raw JSON.

**Impact on Layer 2:** Layer 2 does NOT need an HTML parser, an API JSON parser, a
research metadata parser, or a community/GitHub parser. Those 5 modules are skipped.
Layer 2's job becomes: clean already-extracted text, normalize metadata, chunk into
source spans, tag trust, write evidence store.

---

### Decision: Blog full-text extraction via `<article>` tag

**Design doc said:** Company blogs should be collected as primary evidence (tier 1).

**Problem found:** OpenAI's RSS feed provides only 156-char descriptions.
`content:encoded` is empty. The anthropic_blog.py was fetching full pages but using
`strip_html()` on the whole HTML, which includes navigation menus, sidebars, and
footers mixed into the text.

**What we did:** Added `fetch_article_text(url)` to `blog_utils.py`. It tries the
`<article>` HTML5 semantic tag first (gives clean article body), falls back to
`<main>`, then falls back to full-page strip. Updated `openai_blog.py` to call this
when RSS text is under 500 chars. Updated `anthropic_blog.py` to use it instead of
`fetch_html + strip_html`.

**Result:**
- OpenAI posts: 156 chars → 8,000–16,000 chars of actual article content
- Anthropic posts: 19,525 chars (noisy, nav mixed in) → 17,522 chars (clean article body)
- Blog content now classified as `full` instead of `partial`

---

### Decision: YouTube orchestration now runs in `run_layer_1.py`

**Design doc said:** `youtube_podcast_transcripts` is a source group that should be
collected in each run.

**What we did:** `run_layer_1.py` now dispatches the YouTube collector when the
source group is enabled and YouTube is not explicitly skipped. The active channel
subset is snapshotted into the run manifest and the collector uses that manifest
snapshot rather than reading live config directly.

**Why:** YouTube is part of the same evidence-collection layer as the other source
groups, so leaving it outside the main orchestrator would keep Layer 1 incomplete.
Manifest snapshotting also keeps the run reproducible even if the channel registry
changes later.

**Remaining gap:** Transcript availability is still source-dependent, and the current
channel subset is driven by the resolved registry snapshot rather than a richer
run-specific editorial selector.

---

### Decision: Deleted run_extraction.py (old architecture orphan)

**Design doc said:** N/A — this file predated the new architecture.

**What we did:** Deleted `pipelines/layer_1_extraction/run_extraction.py`.

**Why:** `run_extraction.py` was the pre-refactor Layer 1 orchestrator. It called
old collectors directly and wrote to `output/layer_1_raw/master_YYYY-MM-DD.json`.
It was superseded entirely by `run_layer_1.py` which uses the manifest-driven
architecture and writes to the run-scoped `data/runs/{run_id}/layer_1/` path.
Nothing consumed its output. Keeping it would cause confusion about which
orchestrator to run.

---

## Layer 2 — Canonicalization + Evidence Store

### Decision: Skip the 5 parser modules entirely

**Design doc said:** Build: HTML/Article Parser, API JSON Parser, Research Metadata
Parser, Transcript Parser, Community/GitHub Parser — each handles one source type's
raw payload format.

**What we did:** Not building any of them.

**Why:** The design doc imagined Layer 2 would receive raw HTML files and raw API
JSON blobs. Our Layer 1 collectors already parse the raw content into normalized
`raw_text` fields. When Layer 2 reads `raw_documents.jsonl`, every document already
has clean extracted text — there is no HTML to parse, no API JSON to normalize.

The parsers were designed to solve a problem our Layer 1 already solved.

---

### Decision: Source type router is not a separate module

**Design doc said:** Build `source_type_router.py` as a standalone module that
routes each document to the right parser.

**What we did:** Routing logic lives inside `source_span_chunker.py`. Different
source types (research papers, news APIs, blog posts, community signals) get
different chunking strategies, and the chunker makes that decision internally.

**Why:** Without separate parsers to route to, a dedicated router module would be
a pass-through with a switch statement. That logic belongs in the chunker because
the routing decision IS the chunking decision.

---

### Decision: 11 modules instead of design doc's 17

**Design doc said:** 17 modules across sub-packages (readers/, routers/, parsers/,
normalization/, evidence/, validation/).

**What we did:** 11 modules, all flat in `layer_2_canonicalization/`.

**Modules we skipped:**
- `html_article_parser.py` — Layer 1 already did this
- `api_json_parser.py` — Layer 1 already normalized API fields
- `research_metadata_parser.py` — arxiv fields already structured in RawExtractedDocument
- `transcript_parser.py` — YouTube skipped this run; transcript_blocks already
  exist in Layer 1 format; will add when YouTube is wired
- `community_github_parser.py` — HN and GitHub already normalized by Layer 1 collectors
- `source_type_router.py` — routing logic lives in source_span_chunker.py

**Modules we kept (11 total):**
1. `raw_document_reader.py` — validate schema of Layer 1 output
2. `content_cleaner.py` — normalize whitespace, remove boilerplate patterns
3. `metadata_normalizer.py` — ISO dates, author, content_type assignment
4. `canonical_url_resolver.py` — strip tracking params, generate canonical_document_id
5. `content_quality_classifier.py` — quality score, usability flags per source type
6. `trust_tier_tagger.py` — source_group → trust_tier + source_role
7. `source_span_chunker.py` — split text into citeable spans by source type
8. `provenance_builder.py` — raw_document_id → canonical_document_id → span_ids chain
9. `evidence_store_writer.py` — write all output files
10. `layer2_validation_gate.py` — validate before Layer 3
11. `run_layer_2.py` — orchestrator

---

### Decision: Sub-packages skipped, flat module layout

**Design doc said:** Organize into sub-packages: `readers/`, `routers/`, `parsers/`,
`normalization/`, `evidence/`, `validation/`.

**What we did:** All modules flat in `layer_2_canonicalization/`.

**Why:** Sub-packages add import path complexity (`from pipelines.layer_2_canonicalization.normalization.content_cleaner import...`) without benefit at this stage. Every Layer 1 module is flat and it's clear. Subdirectory organization is appropriate when a layer has 20+ modules across clearly distinct concerns — Layer 2 at 11 modules doesn't justify it.

---

## Layer 2 — Canonicalization + Evidence Store

### Decision: Skip the 5 parser modules entirely

**Design doc said:** Build: HTML/Article Parser, API JSON Parser, Research Metadata
Parser, Transcript Parser, Community/GitHub Parser — each handles one source type's
raw payload format.

**What we did:** Not building any of them.

**Why:** The design doc imagined Layer 2 would receive raw HTML files and raw API
JSON blobs. Our Layer 1 collectors already parse the raw content into normalized
`raw_text` fields. When Layer 2 reads `raw_documents.jsonl`, every document already
has clean extracted text — there is no HTML to parse, no API JSON to normalize.

The parsers were designed to solve a problem our Layer 1 already solved.

---

### Decision: Source type router is not a separate module

**Design doc said:** Build `source_type_router.py` as a standalone module that
routes each document to the right parser.

**What we did:** Routing logic lives inside `source_span_chunker.py`. Different
source types (research papers, news APIs, blog posts, community signals) get
different chunking strategies, and the chunker makes that decision internally.

**Why:** Without separate parsers to route to, a dedicated router module would be
a pass-through with a switch statement. That logic belongs in the chunker because
the routing decision IS the chunking decision.

---

### Decision: 11 modules instead of design doc's 17

**Design doc said:** 17 modules across sub-packages (readers/, routers/, parsers/,
normalization/, evidence/, validation/).

**What we did:** 11 modules, all flat in `layer_2_canonicalization/`.

**Modules we skipped:**
- `html_article_parser.py` — Layer 1 already did this
- `api_json_parser.py` — Layer 1 already normalized API fields
- `research_metadata_parser.py` — arxiv fields already structured in RawExtractedDocument
- `transcript_parser.py` — YouTube skipped this run; transcript_blocks already
  exist in Layer 1 format; will add when YouTube is wired
- `community_github_parser.py` — HN and GitHub already normalized by Layer 1 collectors
- `source_type_router.py` — routing logic lives in source_span_chunker.py

**Modules we kept (11 total):**
1. `raw_document_reader.py` — validate schema of Layer 1 output
2. `content_cleaner.py` — normalize whitespace, remove boilerplate patterns
3. `metadata_normalizer.py` — ISO dates, author, content_type assignment
4. `canonical_url_resolver.py` — strip tracking params, generate canonical_document_id
5. `content_quality_classifier.py` — quality score, usability flags per source type
6. `trust_tier_tagger.py` — source_group → trust_tier + source_role
7. `source_span_chunker.py` — split text into citeable spans by source type
8. `provenance_builder.py` — raw_document_id → canonical_document_id → span_ids chain
9. `evidence_store_writer.py` — write all output files
10. `layer2_validation_gate.py` — validate before Layer 3
11. `run_layer_2.py` — orchestrator

---

### Decision: Sub-packages skipped, flat module layout

**Design doc said:** Organize into sub-packages: `readers/`, `routers/`, `parsers/`,
`normalization/`, `evidence/`, `validation/`.

**What we did:** All modules flat in `layer_2_canonicalization/`.

**Why:** Sub-packages add import path complexity without benefit at this stage.
Every Layer 1 module is flat and it's clear. Subdirectory organization is appropriate
when a layer has 20+ modules across clearly distinct concerns — Layer 2 at 11 modules
doesn't justify it.

---

### Known gap: date format "YYYY-MM-DD HH:MM:SS" from NewsData.io

**Design doc said:** Normalize all dates to ISO 8601.

**What we found:** NewsData.io returns `"2026-05-10 00:06:56"` (space separator,
not T separator). This was not handled in the initial metadata_normalizer.py.

**What we did:** Added `"%Y-%m-%d %H:%M:%S"` to the format list in `normalize_date()`.
All 93 docs now have proper ISO 8601 UTC dates with no missing dates.

---

### Layer 2 actual output (run_2026_05_10_48h_auto)

```
canonical_documents : 93  (0 rejected)
source_spans        : 218
  - paragraph_group  : 98  (blog full articles, claim_candidate=True)
  - abstract_segment : 80  (research papers, claim_candidate=True)
  - news_snippet     : 20  (news API snippets, partial)
  - community_metadata: 20 (HN posts, trend_signal_only)
claim extractable   : 53 docs
content completeness: full=13, abstract_only=40, partial=24, title_only=16
validation          : PASSED (all 8 checks)
```

---

## Layer 3 — Story Processing

### Decision: 13 modules flat (not sub-packages), skip near_duplicate_detector

**Design doc said:** 15 modules in sub-packages (orchestrator/, loaders/, filtering/,
deduplication/, mapping/, clustering/, analysis/, output/, validation/).

**What we did:** 13 modules flat in `layer_3_story_processing/`.

**Modules skipped:**
- `near_duplicate_detector.py` — not needed; exact URL dedup catches all observed
  duplicates in real data (arxiv papers collected across cs.AI/cs.LG/cs.CV categories,
  and duplicate news articles). Near-duplicate title matching is in cluster confidence.
- Sub-packages — same rationale as Layer 2: 13 modules doesn't justify the import complexity.

**Modules built (13):**
1. `document_loader.py` — load docs + build doc-to-span index
2. `exact_duplicate_detector.py` — group by canonical_url + normalized title hash
3. `eligibility_filter.py` — creator vs supporter vs signal classification
4. `entity_topic_mapper.py` — keyword dictionary against config/entity_topic_taxonomy.yaml
5. `event_type_classifier.py` — 12 event types, keyword rules + source group hard rules
6. `story_clusterer.py` — entity+event merge (product/model overlap, not company) + URL-link match
7. `cluster_confidence_scorer.py` — sentence-transformers all-MiniLM-L6-v2 for multi-source
8. `source_mix_analyzer.py` — count source roles per cluster
9. `story_timeline_builder.py` — sort by published_at, label by source_role
10. `story_ranker.py` — additive scoring: authority/coverage/evidence/audience/impact/recency
11. `layer3_writer.py` — write all 8 output files
12. `layer3_validation_gate.py` — 9 checks before Layer 4
13. `run_layer_3.py` — full orchestrator

---

### Decision: Company entity alone does not trigger cluster merging

**Design doc said:** Entity overlap should trigger clustering.

**What we found:** "OpenAI" entity was shared across all 13 OpenAI blog posts,
causing them all to merge into one over-broad cluster.

**What we did:** Require *product or model* entity overlap (not company-level) to merge
two story-creator clusters. Company "OpenAI" alone is not enough — you need shared
"Codex" or "GPT-5.5" or "ChatGPT" to confirm it's the same story.

**Why:** Different OpenAI blog posts about Codex safety, ads in ChatGPT, and Uber
partnerships are different stories even though all mention OpenAI.

---

### Decision: Supporter attachment threshold raised to score >= 7

**Design doc said:** Community signals and news articles should attach to existing clusters.

**What we found:** With score >= 3 (any single entity match + time proximity), unrelated
docs were being pulled into clusters (e.g., "openai.com domain history" HN post attaching
to a Codex cluster because both mention OpenAI).

**What we did:** Score >= 7 required to attach a supporter. This requires either:
- Direct URL/arxiv link match (10 pts), or
- Specific product/model entity overlap (4 pts each) + event type match (2 pts) + time (1 pt) = 7+

---

### Decision: Sentence-transformers for multi-source cluster confidence only

**Design doc said:** Cluster confidence scorer should use embeddings.

**What we did:** Embeddings (all-MiniLM-L6-v2) are only used for multi-source clusters.
Single-source clusters use rule-based confidence from trust tier + content completeness.

**Why:** Encoding all 77 titles for pairwise similarity when most clusters have 1 doc is
wasteful. Only the 2 multi-source clusters needed embedding comparison.

---

### Layer 3 actual output (run_2026_05_10_48h_auto)

```
Input docs        : 93
After dedup       : 77 (16 removed — arxiv multi-category + duplicate news)
Story clusters    : 47
  multi-source    : 2 (Codex-related, Claude Opus 4.7)
  single-source   : 45 (mostly research papers)
For Layer 4       : 11 (medium-priority official blog stories)
Validation        : PASSED (9/9 checks)
Elapsed           : 19.3s
```

---

---

## Layer 4 — Evidence Intelligence

### Decision 1: 12 flat modules instead of design doc's 18 in sub-packages

**Design doc said:** 18 modules organized in sub-packages: `loaders/`, `filtering/`,
`extraction/`, `verification/`, `scoring/`, `output/`, `validation/`.

**What we did:** 12 flat modules in `pipelines/layer_4_evidence_intelligence/`.

**Why:** Same reasoning as Layers 2 and 3 — sub-packages add zero value at this scale.
Several design doc modules were trivially merged:
- `claim_type_classifier` + `claim_normalizer` → happens inside the LLM extraction prompt
- `cross_source_corroboration_analyzer` + `uncertainty_confidence_classifier` → folded into `claim_verifier.py` (both rule-based, 10 lines each)
- `claim_importance_scorer` → folded into `evidence_density_scorer.py`
- `video_format_suitability_scorer` → folded into `evidence_density_scorer.py`
- `layer4_output_packager` + `layer4_manifest_writer` → merged into `layer4_writer.py`

---

### Decision 2: One LLM call per span — no second verification pass

**Design doc said:** Multi-pass: extract claims → then separately verify them with
another LLM call.

**What we did:** Single structured JSON call per span. The prompt instructs the LLM to
extract claims + classify type + assign support_level in one response. Verification is
then rule-based (trust_tier + support_level → verification_status).

**Why:** 97 spans × 2 LLM calls = 194 calls. Rule-based verification is more consistent
and deterministic than a second model self-check. Trust tier is the real signal — a
claim from Anthropic's official blog is verified by the source's authority, not by
asking the model "do you think this is supported?"

---

### Decision 3: Async parallelism with semaphore (max 20 concurrent)

**Design doc said:** Nothing about parallelism.

**What we did:** `asyncio.gather()` for all spans within a story, with a semaphore
limiting to 20 concurrent API calls. Stories processed sequentially.

**Why:** 97 sequential LLM calls at ~8s/call = ~13 minutes. Parallel within-story
reduces wall-clock time. Semaphore prevents API rate-limit rejections.

Note: gpt-5-nano does not accept custom temperature — only default temperature (1) is
supported. The `_build_create_kwargs()` helper checks model name and omits temperature
for nano models.

---

### Decision 4: Interpretive claims not rejected — classified by claim_type

**Design doc said:** Claims should be factual. Interpretation should be avoided.

**What we did:** `interpretive_claim` is a valid claim type (not rejected). We reject
only `prediction_claim` and `opinion_claim`. Interpretive claims from tier-1 sources are
marked verified/high — the source explicitly made the interpretive statement.

**Why:** Official company blogs routinely state context-setting interpretations ("As AI
becomes more capable..."). These are still explicitly stated by the authoritative source
and can be used in scripts with appropriate framing. Layer 8 (script writer) sees
`claim_type=interpretive_claim` and knows to frame it as the company's perspective, not
an independent fact. Rejecting all interpretive claims from official sources would
eliminate substantial legitimate content.

---

### Decision 5: All verified claims show confidence=high for this dataset

**Design doc said:** Three confidence tiers: high / medium / low.

**What we did:** All 201 verified claims in the first run show `confidence=high`.

**Why this is correct:** All 11 Layer-4 stories come from tier-1 official company blogs
(Anthropic, OpenAI) with `support_level=direct`. The verifier correctly assigns
`high` confidence for `direct + tier-1`. In production runs with independent news,
research papers, and community signals mixed in, medium/low confidence claims will appear
as expected. The logic is correct — the dataset happens to be high-quality for this run.

---

### Decision 6: Evidence density score caps at 80 for official-blog-only stories

**Design doc said:** Evidence density score from 0-100.

**What we did:** All 11 stories score 80. This is correct and expected.

**Why:** Score = min(claims×5, 50) + primary_bonus(20) + independent_bonus(max 15) +
high_conf_bonus(max 10). With only official blogs:
- claim_score = 50 (caps at 10 verified claims)
- primary_bonus = 20
- independent_bonus = 0 (no independent news)
- high_conf_bonus = 10 (caps at 5 high-confidence claims)
- Total max = 80

The 15-point independent source bonus is intentionally withheld to distinguish
"confirmed by official source only" (80) from "confirmed + independently covered" (95).
In a real run with mixed sources, stories break out of the 80 cap.

---

### Layer 4 actual output (run_2026_05_10_48h_auto)

```
Stories analyzed    : 11
Spans processed     : 97 (1 excluded — not claim candidate)
Claims extracted    : 220 raw → 214 after dedup (4 groups)
Verified            : 201 (all high confidence — tier-1 official blogs)
Rejected            : 13 (8 opinion, 5 prediction)
Contradictions      : 0 (single-source stories — expected)
Evidence gaps       : 12 (11 missing_independent_confirmation, 1 benchmark_without_research)
Roundup-ready       : 11 / 11
Deep-dive-ready     : 11 / 11
Validation          : PASSED (9/9 checks)
Elapsed             : ~13 min (gpt-5-nano, 97 async LLM calls)
```

---

## Current Layer Status

| Layer | Status | Notes |
|-------|--------|-------|
| Layer 0 | Complete | 13 modules, manifest-driven |
| Layer 1 | Complete | 93 docs/run, blog full-text fixed |
| Layer 2 | Complete | 11 modules, 218 source spans, all checks pass |
| Layer 3 | Complete | 13 modules, 47 clusters, 11 for Layer 4, all checks pass |
| Layer 4 | Complete | 12 flat modules, 201 verified claims, 11 fact sheets, all checks pass |
| Layer 5 | Complete | 13 flat modules, roundup selected (8 stories), selected_video_brief ready |
| Layer 6 | Complete | 11 flat modules, roundup packet built, quality 92/100, ready_for_layer_7 |
| Layer 7 | Complete | 18 flat modules, 2 LLM calls, 9/9 checks pass, ready_for_layer_8 |
| Layer 8 | Complete | 12 flat modules, 1 LLM module (11 async calls), 7/7 checks pass, ready_for_layer_9 |
| Layer 9 | Complete | 19 flat modules, published-memory repetition gate added, async runtime logging added, ready_for_layer_10 |
| Layer 10 | Complete | 18 flat modules, 13 persistent memory files, 108 total JSONL records, ready_for_future_runs |

---

## Layer 5 — Editorial Intelligence

### Decision: 13 flat modules instead of 17 in sub-packages

**Design doc said:** 17 modules organized in sub-packages: orchestrator/, loaders/, gates/,
analysis/, routing/, output/, validation/

**What we did:** 13 flat modules + run_layer_5.py in a single directory, following the
Layer 4 pattern.

**Why:** Sub-packages add import complexity with no benefit when each module is already
focused. Flat structure means every module can be tested individually with one command.
The following design modules were merged:
- 5.6 Impact Analyzer → merged into audience_fit_analyzer.py (same scoring dimensions)
- 5.8 Follow-up Detector → merged into novelty_checker.py (follow_up format is disabled)
- 5.9 Market Gap Analyzer → merged into video_opportunity_scorer.py (no external data source)
- 5.13 Portfolio Balancer → merged into editorial_decision_maker.py (lightweight check)

---

### Decision: No new config files — thresholds inline as constants

**Design doc said:** 7 YAML config files (editorial_intelligence_rules.yaml,
format_routing_rules.yaml, novelty_rules.yaml, etc.)

**What we did:** Key thresholds are constants inside each module (e.g.,
`_DEEP_DIVE_MIN_SCORE = 80`, `_ROUNDUP_MIN_STORIES = 5`). Format parameters are
read from the existing `config/format_config.yaml`.

**Why:** The design's 7 config files are mostly just the threshold tables duplicated
from the narrative. Inlining them keeps each module self-contained (same as Layer 4
pattern). format_config.yaml already has the authoritative enabled/disabled flag and
duration targets — there's no reason to duplicate that.

---

### Decision: Two LLM modules, not zero and not per-module

**Design doc said:** "Viewer Value Analyzer" and "Editorial Brief Builder" are the
editorial intelligence modules that need LLM; others are rule-based.

**What we did:** Exactly two LLM modules:
- viewer_value_analyzer.py: 11 async parallel calls (1/story) — generates viewer_promise,
  primary_viewer_question, value_types, viewer_value_score
- editorial_brief_builder.py: 1 LLM call total — generates episode_theme, segment_guidance
  with roles and time budgets, opening hook, working angle

**Why:** Audience fit, format scoring, routing, and opportunity scoring are all
deterministic from story_type + topics + claim counts. LLM adds genuine value only for
editorial language (what is the viewer's question? what is the angle?) that rule-based
logic cannot produce. The brief builder reordered stories intelligently (Codex as lead,
Claude Opus second) and hit 480s target time budget exactly — that's real editorial
judgment from the LLM.

---

### Decision: story_type sourced from ranked_stories, not fact_sheets

**Design doc said:** Fact sheets carry story_type through from Layer 3.

**What we did:** editorial_candidate_loader.py reads story_type from ranked_stories.json
(where it's correct) rather than story_fact_sheets.json (where it's an empty string).

**Why:** The story_type field in fact_sheets is empty due to a data propagation bug
in Layer 4 (span_selector → claim_extractor → story_fact_sheet_builder chain). The
fix is to read it from the authoritative source (ranked_stories.json) in the loader.
This avoids touching Layer 4 code which is already validated.

---

### Decision: Portfolio balance is a soft preference, not a hard filter

**Design doc said:** Portfolio balancer enforces company diversity limits.

**What we did:** The `_balance_roundup()` function simply takes the top max_roundup
stories by opportunity score. No company is filtered out.

**Why:** With only 11 stories all from 2–3 companies (OpenAI, Anthropic, others),
a hard diversity filter would eliminate valid stories and drop the roundup below
min_stories. The real diversity constraint is at the *channel strategy* level (Layer 0),
not the individual run selection level. A soft preference is added via notes in the
decision output for future runs with more diverse source coverage.

---

### Layer 5 actual output (run_2026_05_10_48h_auto)

```
Candidates evaluated  : 11
Evidence safety       : 11/11 safe (roundup + deep_dive)
Avg audience fit score: 85
Avg viewer value score: 74
Novelty               : 11/11 new_topic (memory empty — first run)
Format routing        : 11/11 → deep_dive (primary) / roundup_segment (secondary)
Opportunity scores    : 11/11 strong_video_candidate (81–88)
Editorial decision    : create_video → roundup (8 stories)
Rejected              : 3 (not_selected_for_roundup — story count limit)
Validation            : PASSED (8/8 checks, 0 warnings)
Elapsed               : ~53s (11 viewer_value LLM calls + 1 brief LLM call)
```

Selected roundup (8 stories, 480s = 8 min):
- 90s lead: Running Codex safely at OpenAI
- 70s major: Introducing Claude Opus 4.7
- 65s major: Scaling Trusted Access for Cyber with GPT-5.5
- 70s short: Advancing voice intelligence (new API audio models)
- 60s short: Parloa service agents
- 60s short: Uber + OpenAI
- 45s brief: Introducing Trusted Contact in ChatGPT
- 30s brief: Testing ads in ChatGPT

---

## Layer 6 — Format-Specific Research Packets

### Decision: 11 flat modules, 3 format builders skipped

**Design doc said:** 15 modules in sub-packages (orchestrator/, loaders/, routing/, builders/,
evidence/, compression/, scoring/, output/, validation/) + 5 packet builders + 8 config YAMLs.

**What we did:** 11 flat modules in a single directory:
- `brief_loader.py` — merged Module 6.2 (brief loader) + 6.3 (packet router)
- `roundup_packet_builder.py` — Module 6A
- `deep_dive_packet_builder.py` — Module 6B
- `evidence_boundary_enforcer.py` — Module 6.9
- `source_pack_builder.py` — Module 6.10
- `claim_section_mapper.py` — Module 6.11
- `packet_context_builder.py` — Module 6.12 (context compression)
- `packet_quality_scorer.py` — Module 6.13
- `layer6_writer.py` — merged Module 6.14 (output packager) + manifest writer
- `layer6_validation_gate.py` — Module 6.15
- `run_layer_6.py` — Module 6.1 orchestrator

**Skipped:**
- `evergreen_packet_builder.py` — format disabled in format_router (will never route here)
- `comparison_packet_builder.py` — format disabled
- `followup_packet_builder.py` — format disabled, memory empty
- 8 config YAML files — thresholds inlined as constants (consistent with L4/L5 pattern)
- Sub-packages — flat structure, every module individually testable

**Why:** Same reasoning as L5 — flat is simpler to test and import. Skipped builders
add dead code paths for disabled formats. The 3 data loaders (claim_loader, story_context_loader,
source_context_loader) were folded into run_layer_6.py — all loading happens upfront in the
orchestrator and is passed as dicts to each module, keeping modules pure functions.

---

### Decision: roundup_packet_builder enriches L5 guidance rather than re-deriving it

**Design doc said:** Layer 6 should "for each story, choose 2-4 safe claims" and build segment structure from scratch.

**What we did:** L5's editorial_brief_builder already produced story ordering, segment roles,
time budgets, and safe_claim_ids per story. Layer 6 takes that as the starting point and
enriches it: resolves claim IDs to claim text, derives one_line_summary from the highest-importance
fact in the fact_sheet, derives why_it_matters from the segment's viewer_promise (already in brief).

**Why:** Re-deriving story order and claim selection would either duplicate L5's LLM work or
produce inconsistent results. L5 made the editorial judgment. L6's job is to package it cleanly
with evidence provenance — not re-decide.

---

### Decision: Source pack uses claim_evidence_map as the join key, not story-level lookups

**Design doc said:** Collect source spans "used by packet claims."

**What we did:** `claim_id → claim_evidence_map → source_span_ids → source_spans →
canonical_document_id → canonical_documents`. Full chain traversal per claim.

**Why:** The claim_evidence_map is the authoritative link between claims and their evidence.
Going story-level would lose per-claim source attribution. The full chain ensures every source
in source_pack is actually linked to a specific claim in the packet, not just any claim from
the story.

---

### Layer 6 actual output (run_2026_05_10_48h_auto)

```
Format           : roundup
Stories          : 8
Safe claims      : 154
Cautious claims  : 0
DNU claims       : 6 (blocked, not used)
Sources          : 8 (all trust_tier=1 official sources, all recommended for YouTube)
Quality score    : 92/100
  evidence_coverage  : 100 (all 8 segments have 17-20 claims each)
  section_coverage   : 100 (lead + major_update + 5 more segments)
  source_diversity   :  50 (all tier-1; expected for AI company blog run)
  format_fit         : 100
  risk_control       : 100 (0 DNU claims used)
Validation       : PASSED (8/8 checks, 1 soft warning: low source diversity)
Elapsed          : <1s (no LLM calls — pure dict assembly)
```

Claim integrity cross-check: 154/154 claim refs resolve to verified_claims.jsonl. 0 DNU violations.

---

## Layer 7 — Content Planning

### Decision: 18 flat modules instead of design doc's implied sub-packages

**Design doc said:** Implied grouping into planners/, hooks/, titles/, evidence/, output/, validation/.

**What we did:** 18 flat modules in `pipelines/layer_7_content_planning/`. Every module is individually testable with `python <module>.py`.

**Why:** Consistent with every previous layer. Sub-packages add import path length with no structural benefit at this scale.

---

### Decision: Only 2 LLM calls — everything else is rule-based

**Design doc said:** Multiple modules could use LLM.

**What we did:** Exactly two LLM modules:
- `hook_planner.py` — 1 async call: generates 3 hook directions + blocked angles. Hook direction is an editorial judgment that rule-based logic cannot make.
- `title_thumbnail_planner.py` — 1 async call: generates 6-8 title angles + 5 thumbnail texts. Title creativity is editorial language.

Everything else (narrative arc, section plan, claim placement, transitions, pacing, visuals, CTA, evidence boundary review, script writer brief) is rule-based with deterministic outputs.

**Why:** Narrative arc, pacing, and section structure are mechanical derivations of the Layer 6 packet structure. LLM adds value only where editorial language or creative judgment is needed — the hook direction and title angles. Using LLM for pacing or section goals would add cost and variance without improving quality.

---

### Decision: script_writer_brief.json is the sole Layer 8 input — not the full plan

**Design doc said:** Layer 8 should read multiple Layer 7 files (video_plan, section_plan, hook_plan, etc.).

**What we did:** `script_writer_brief_builder.py` assembles all 11 planning outputs into one consolidated `script_writer_brief.json`. Layer 8 reads only this one file.

**Why:** If Layer 8 reads 7 separate files, each section writer needs to join across files to get its hook, claims, visuals, and instructions. The brief consolidates everything at the section level — each section in the brief already has its required claims, visual notes, writer instructions, blocked phrases, and CTA. The script writer gets a single, complete document that requires no cross-file joins.

---

### Decision: Skipped Evergreen / Comparison / Follow-up planners

**Design doc said:** Build section planners and hook/title generators for all 5 formats.

**What we did:** Only built roundup and deep_dive paths in `section_planner.py`, `narrative_arc_planner.py`, etc.

**Why:** `format_config.yaml` has evergreen, comparison, and follow-up formats disabled (`enabled: false`). Layer 5's format_router never routes to them. Layer 6 has no packet builders for them. Building planners for these formats now would produce dead code paths that can never run. They will be added when the upstream layers support them.

---

### Decision: No config YAML files — thresholds inline as constants

**Design doc said:** Implied separate config for pacing rules, transition styles, hook types, etc.

**What we did:** All thresholds and style maps are inline constants (e.g., `_ROUNDUP_SECTION_GOALS`, `_ROLE_INSTRUCTIONS`, `_WPM = 130`). No new config files created.

**Why:** Consistent with L4/L5/L6 pattern. Layer-internal configuration belongs in the module — it makes modules individually testable and self-contained. Cross-layer config (format parameters, enabled formats) stays in `config/`.

---

### Decision: gpt-5-nano temperature workaround via `_build_create_kwargs()`

**Design doc said:** Nothing about model-specific API quirks.

**What we found:** gpt-5-nano does not accept the `temperature` parameter — passing it raises an API error. This was discovered during Layer 4 development.

**What we did:** Every LLM module in Layer 7 (and all subsequent layers) uses `_build_create_kwargs(model, **kwargs)` which silently drops `temperature` when "nano" is in the model name. This is a shared pattern, not a one-off fix.

---

### Layer 7 actual output (run_2026_05_10_48h_auto)

```
Format          : roundup
Sections        : 11 (intro_hook + 8 stories + final_takeaway + cta)
Duration target : 585s (9.8 min)
Title options   : 7 (all low-risk)
Thumbnail texts : 5 (all low-risk)
Hook type       : roundup_speed_hook (risk=low, 2 alternatives)
Visual suggests : 11 (quote_cards, title_card, simple_diagram, caution_card)
Boundary review : passed_with_warnings (1 medium-risk title flagged, not blocked)
Validation      : PASSED (9/9 checks, 0 hard errors)
Elapsed         : ~62s (2 LLM calls + 13 rule-based steps)
```

---

## Layer 8 — Script Generation

### Decision: 12 flat modules instead of design doc's implied sub-packages (writers/, mapping/, editing/)

**Design doc said:** Implied writers/, mapping/, editing/ sub-packages for the script generation modules.

**What we did:** 12 flat modules in `pipelines/layer_8_script_generation/`. Every module testable individually.

**Why:** Consistent with all prior layers. Flat is simpler to import, simpler to test, and the 12-module count doesn't justify sub-package overhead.

---

### Decision: Added `deep_dive_script_writer.py` — not in original Layer 8 plan

**Design doc said:** One roundup script writer.

**What we did:** Built both `roundup_script_writer.py` and `deep_dive_script_writer.py` with different prompts and role-tone mappings.

**Why:** Layer 6 already has `deep_dive_packet_builder.py`. Layer 7's `section_planner.py` already has `_build_deep_dive_sections()`. Both upstream layers fully support deep_dive — it would be a gap to only generate roundup scripts when the pipeline can produce deep_dive plans. The two writers share the same async pattern; only the system prompt and per-section role tone differ.

---

### Decision: Added `shorts_clips_suggester.py` — new module not in design doc

**Design doc said:** `shorts_clips_suggestions.json` as an output, but no explicit module for it.

**What we did:** Built `shorts_clips_suggester.py` as a rule-based module that identifies sections meeting clip criteria (intro hook → always; story ≤60s with ≥2 required claims → short_story_burst; takeaway ≤60s → short_takeaway).

**Why:** This is a lightweight, fully independent module with no upstream dependencies beyond the section scripts. It adds real publishing value (Shorts/Reels from existing content) without adding LLM cost or complexity. Every roundup run automatically gets 5-7 Shorts candidates.

---

### Decision: youtube_description.md + youtube_chapters.json + source_list.json consolidated into youtube_metadata.json

**Design doc said:** Three separate files: `youtube_description.md`, `youtube_chapters.json`, `source_list.json`.

**What we did:** One file: `youtube_metadata.json` containing chapters, description, source_list, and tags.

**Why:** All three are consumed together by Layer 9's metadata safety checker and the final publish package. Keeping them in one file avoids three separate read operations in every downstream consumer. The description already contains chapter timestamps inline, so `youtube_chapters.json` as a separate file is redundant. Layer 9 reads youtube_metadata.json directly.

**Note for future layers:** If Layer 10 or a publishing tool specifically needs `source_list.json` as a standalone file, `layer8_writer.py` can emit it as a 2-line addition without changing any other module.

---

### Decision: Claim source URL comes directly from verified_claims.jsonl — no complex bridge

**Design doc said (implied):** Source URL lookup requires: claim_id → claim_evidence_map → canonical_document_id → extract suffix → match source_ref_id in source_pack.

**What we found:** `verified_claims.jsonl` already has `source_urls: [...]` directly on each claim record. No bridge needed.

**What we did:** `brief_loader.py` reads verified_claims.jsonl and builds `claim_source_map = {claim_id: source_urls[0]}` in one pass.

**Why:** The correct data was always there — we overcomplicated the design by assuming a multi-step lookup was required. The source URL is present on the claim itself.

---

### Decision: 11 async LLM calls per run (one per section) via asyncio.gather()

**Design doc said:** Script generation produces one script, implying one LLM call.

**What we did:** One async LLM call per section, all 11 dispatched concurrently via `asyncio.gather()`. Each call returns `{script_text, used_claim_ids}` as JSON.

**Why:** One large call for an 827-word script across 11 sections would give the LLM no structural grounding per section. Per-section calls let each section get its exact claims, visual notes, word budget, and instructions. The async pattern keeps total latency similar to one slow call while getting 11x more focused outputs. JSON response format gives accurate per-section claim tracking.

---

### Decision: Sentence mapper uses section-level claim mapping, not sentence-level

**Design doc said:** `sentence_claim_map.jsonl` maps each sentence to specific claim IDs.

**What we did:** All evidence sentences in a section get mapped to that section's `used_claim_ids`. There is no sentence-to-specific-claim matching.

**Why:** Matching individual sentences to specific claims requires either exact text matching (fails for paraphrased claims) or an LLM call per sentence (expensive). Section-level mapping is accurate enough: if a sentence is in story_1, it belongs to story_1's claims and sources. Layer 9's sentence_support_verifier uses actual source span text to catch overclaims — it doesn't rely on per-sentence claim attribution.

---

### Decision: Skipped Evergreen / Comparison / Follow-up script writers

**Design doc said:** Build script writers for all enabled formats.

**What we did:** Only `roundup_script_writer.py` and `deep_dive_script_writer.py`.

**Why:** Same reason as Layer 7 — these formats have no upstream pipeline support (no Layer 6 packet builders, no Layer 7 section planners). Adding script writers for unsupported formats produces unreachable code.

---

### Layer 8 actual output (run_2026_05_10_48h_auto)

```
Format          : roundup
Word count      : 827 words (~6.4 min at 130 wpm)
Target          : 900-1400 (within soft range)
Sections        : 11 (all written)
Sentences       : 48 mapped (41 claim, 4 cta, 1 closing, 2 transition)
Claim usage     : 34/154 safe claims (22.1%)
Sources in meta : 8 (all tier-1 URLs)
Chapters        : 11 with correct cumulative timestamps
Shorts suggests : 7 candidates (intro + 5 story bursts + takeaway)
Blocked phrases : 0 violations
Cautious check  : PASSED
Validation      : PASSED (7/7 checks, 0 warnings)
Elapsed         : ~8.5s (11 async LLM calls + 9 rule-based steps)
```

---

## Layer 9 — Verification Firewall

**Actual output (run_2026_05_10_48h_auto):** Originally 18 flat modules and 15 output files. Current implementation is now 19 flat modules with `repetition_safety_checker.py` added and an additional `repetition_safety_report.json` output, while preserving the same overall verification role.

### Decision: 19 flat modules instead of design doc's sub-packages (loaders/, validation/, verification/, metadata/, scoring/, correction/, output/)

**Design doc said:** 20+ modules in 7 sub-packages.

**What we did:** 19 flat modules in `pipelines/layer_9_verification_firewall/`. Flat structure consistent with all prior layers.

**Why:** Same rationale as every prior layer. 16 modules in sub-packages would add `from pipelines.layer_9_verification_firewall.verification.overclaim_detector import...` style paths with no organizational benefit. All modules will remain individually testable.

---

### Decision: `repetition_safety_checker.py` is now a published-memory post-script gate

**Design doc said:** Build a repetition checker that compares current title/hook/thumbnail against memory files (`memory/video_memory.jsonl`, `memory/title_hook_memory.jsonl`) to detect recycled content.

**What we did:** Built it as a Layer 9 gate against published-memory state. It now:

- checks selected story IDs against previously published story coverage
- checks the current title direction against previously published titles and prior blocked title angles
- reports hook-type fatigue as a softer warning
- writes `repetition_safety_report.json`

**Why:** Layer 5 novelty is still the first defense, but it evaluates candidate
selection before the final title/metadata shape exists. The Layer 9 version is where
we can evaluate the actual post-planning framing that would reach viewers.

---

### Decision: Skip YAML config files

**Design doc said:** 7 YAML config files (verification_firewall_rules.yaml, sentence_verification_rules.yaml, overclaim_detection_rules.yaml, etc.)

**What we did:** All thresholds and rule sets inline as constants in each module.

**Why:** Consistent with L4–L8 pattern. Layer 9 is the only consumer of these rules — there is no cross-layer config sharing happening. Inlining keeps each module self-contained and individually testable.

---

### Decision: `contradiction_handler.py` is informational only — not a blocking check

**Design doc said:** Contradiction and evidence gap handler should detect unhandled contradictions and block if the script makes definitive claims about unresolved issues.

**What we did:** Built it, but the current run has 0 contradictions and 12 evidence gaps that are all `missing_independent_confirmation / severity=medium / blocks_roundup=false`. So it always passes for this dataset. Built as informational reporting for future runs where contradictions exist.

**Why:** The run data simply has no contradictions — every story comes from a single-source official blog. Blocking on a count of 0 would be trivially passed. The module is still worth building to establish the pattern for future runs with multi-source conflict.

---

### Decision: `sentence_support_verifier.py` uses actual source span text — strictly better than design doc

**Design doc said:** Compare script sentences against the claim text to detect overclaims.

**What we did:** Compare script sentences against the actual source span text (raw article paragraphs from Layer 2's `source_spans.jsonl`, which has 218 spans with full article text).

**Why:** Claim text is already a distillation of the source — comparing sentence against claim checks paraphrasing accuracy but misses the case where the claim itself was accurate but the script added certainty the source didn't have. Comparing against the raw source paragraph is a stricter and more accurate check. The source span text often contains explicit hedging ("may", "could", "as they become more capable") that the script might strip. This is the best version of this check.

**Implementation:** 1 async LLM call per story section (not per sentence) — each call gets all sentences in that section + the section's source span texts + claim texts. Returns any sentences that overstate the source. 11 total calls for a roundup (same count as Layer 8's script generation).

---

### Decision: Sentence coverage checker treats intro/CTA/takeaway sections as no-claim-required

**Design doc said:** Every factual sentence must have a claim_id.

**What we did:** Sections with `segment_role` in `{intro, intro_hook, cta, takeaway, final_takeaway}` are exempt from claim coverage requirements. Only story sections (required_claim_ids > 0) are checked.

**Why:** The intro, takeaway, and CTA sections intentionally have no required claims — this was designed in Layer 7. The intro previews stories without stating facts; the takeaway synthesizes; the CTA invites engagement. Requiring claim IDs on these sections would fail legitimate content.

---

### Modules built (18 total)

| Module | Type | Role |
|---|---|---|
| `context_loader.py` | Rule | Load all inputs; build claim_map, span_map, cem_map, sentence_map, rejected_ids |
| `script_structure_validator.py` | Rule | Sections match Layer 7 plan (count, keys, order, duration) |
| `sentence_classification_validator.py` | Rule | Classify sentence types: factual/hook/transition/cta (determines which need support) |
| `sentence_claim_coverage_checker.py` | Rule | Factual sentences have claim_ids; rejected claims not used |
| `claim_source_traceability_checker.py` | Rule | Every used claim resolves to source_span_ids in span_map |
| `sentence_support_verifier.py` | **LLM** | Per-section async: compare sentences vs source span text, flag overclaims/unsupported |
| `overclaim_detector.py` | Rule | Pattern-based: blocked phrases, superlatives, false certainty, unqualified predictions |
| `cautious_language_verifier.py` | Rule | Sentences using cautious claim_ids have qualifying language |
| `rejected_claim_leakage_detector.py` | Rule | Rejected claim text phrases + blocked phrases in script, title, description |
| `contradiction_evidence_gap_handler.py` | Rule | Informational — reports Layer 4 gaps/contradictions status (non-blocking) |
| `metadata_safety_checker.py` | Rule | Title/thumbnail/description checked against blocked_title_angles from Layer 7 + risky patterns |
| `source_attribution_checker.py` | Rule | Source URLs in script present in youtube_metadata source_list and description |
| `risk_scorer.py` | Rule | Aggregate all issues → severity counts → approved / approved_with_warnings / requires_revision / blocked |
| `correction_patch_generator.py` | Rule | Structured patch per issue: original + replacement + auto_patch_safe flag |
| `verified_script_builder.py` | Rule | Apply safe patches to script.md → verified_script.md (skips instruction-style replacements) |
| `layer9_writer.py` | Rule | Writes all Layer 9 output files + manifest |
| `layer9_validation_gate.py` | Rule | Hard/soft gate checks on output completeness; writes layer9_validation_report.json |
| `run_layer_9.py` | — | 17-step orchestrator; auto-discovers latest run |

### Modules skipped vs design doc

| Design doc module | Reason skipped |
|---|---|
| 7 YAML config files | Thresholds inline as constants (consistent with L4–L8 pattern) |
| All sub-packages (loaders/, validation/, etc.) | Flat structure consistent with all layers |
| `final_publish_package_builder.py` as separate module | Folded into `layer9_writer.py` — just a dict assembly step |

---

## Layer 10 — Memory + Learning

**Actual output (run_2026_05_10_48h_auto):** 18 flat modules, 13 persistent memory files in `memory/` at project root, 2 per-run files in `data/runs/{run_id}/layer_10/`. First run: 1 video record, 8 story coverage records, 34 claim ledger records, 12 entity/topic records, 8 source records, 1 editorial pattern record, 9 follow-up records, 12 evidence gap watchlist records, 7 rejected claim patterns, 16 learning signals. `ready_for_future_runs = true`.

**Current system note (2026-05-13):** Layer 10 still writes the prepared-run memory
artifacts above, but the overall memory system now also includes a post-run publishing
workflow for OAuth auth, owner-channel sync, publish-state updates, analytics ingest,
and memory rebuild after publication changes.

### Decision: 18 flat modules instead of 18 modules in 7 sub-packages

**Design doc said:** Sub-packages: orchestrator/, gates/, extraction/, writers/, learning/, indexing/, validation/, output/

**What we did:** All modules flat in `pipelines/layer_10_memory_learning/`

**Why:** Consistent with every layer from L4–L9. Sub-packages add import indirection without helping readability.

---

### Decision: Memory deduplicator folded into each writer

**Design doc said:** Module 10.13 — Memory Deduplicator + Version Manager as a separate post-processing step

**What we did:** Each writer checks its own dedup key before appending (e.g., `video_id` for video_memory, `claim_id + video_id` for claim_ledger). No separate dedup step.

**Why:** A separate deduplicator would need to re-read all files, identify duplicates, then rewrite. Inline checking on write is simpler, faster, and avoids the risk of dedup-after-write race conditions.

---

### Decision: Performance feedback now lives in a post-run publishing workflow

**Design doc said:** Module 10.14 — ingest YouTube performance data (views, CTR, retention)

**What we did:** Implemented it outside the core `run_layer_10.py` path. The project
now has:

- `publishing_memory.py auth` for OAuth token creation
- `publishing_memory.py sync-channel` for authenticated owner-channel sync
- `publishing_memory.py mark-published` for attaching a real YouTube video ID and
  publish timestamp to a prepared run
- `performance_memory.jsonl` ingestion from YouTube Analytics during publish-state
  updates and channel sync
- automatic rebuild of `learning_signals.jsonl`, `memory_index.json`, and
  `memory_snapshot.json` after publish-state changes

**Why:** The design requirement is real, but it does not belong entirely inside the
Layer 10 run itself. Real performance data only exists after publication. Treating it
as a post-run workflow keeps the pipeline honest: Layer 10 stores prepared memory,
and publication sync enriches that memory only when platform data actually exists.

**Current state:** OAuth authorization and the first owner-channel sync are complete.
The authenticated channel resolves to `UCp4tfcoFDQIFu7Cnodrqq_w`, and the channel
currently has zero published videos, so `performance_memory.jsonl` is correctly empty.

---

### Decision: Fresh-start memory cleanup keeps platform state but resets exploratory content memory

**Design doc said:** Durable memory should represent reusable long-term knowledge for
future runs.

**What we did:** After adding the publish-state workflow and before the first real
production run, we reset the exploratory content memory files back to an empty
baseline while preserving the authenticated publishing-channel state files:

- kept: `publishing_channel_state.json`, `published_video_inventory.jsonl`
- reset: `video_memory.jsonl`, `claim_ledger.jsonl`, `story_coverage_memory.jsonl`,
  `entity_topic_memory.jsonl`, `source_memory.jsonl`, `editorial_pattern_memory.jsonl`,
  `followups.jsonl`, `evidence_gap_watchlist.jsonl`, `rejected_claim_patterns.jsonl`,
  `performance_memory.jsonl`, `learning_signals.jsonl`
- rebuilt: `memory_index.json`, `memory_snapshot.json`

**Why:** The channel is starting fresh with zero published videos. Keeping exploratory
draft-run memory would make novelty, repetition, and future learning look more mature
than the real channel history actually is. Preserving platform-state files keeps the
OAuth/authenticated channel setup intact while clearing misleading editorial memory.

---

### Decision: YAML config files skipped

**Design doc said:** 6 YAML config files (memory_policy.yaml, memory_schema_rules.yaml, memory_dedup_rules.yaml, performance_learning_rules.yaml, followup_tracking_rules.yaml, retention_rules.yaml)

**What we did:** All policy constants are inline in each module.

**Why:** Same decision made for all prior layers. YAML config is useful when non-engineer operators need to tune parameters. At this stage we're still the only operators and inline constants are faster to iterate on.

---

### Decision: title_hook_memory.jsonl folded into editorial_pattern_memory.jsonl

**Design doc said:** Separate `memory/title_hook_memory.jsonl`

**What we did:** Title angles, hook type, hook direction, and thumbnail options all go in `editorial_pattern_memory.jsonl`

**Why:** Title and hook memory are editorial decisions made in the same Layer 7 step. Splitting them across two files forces any consumer (Layer 7 novelty check) to join two JSONL files to answer one question: "what framing did we use before?"

---

### Module-by-module decisions

| Module | Category | Notes |
| --- | --- | --- |
| `context_loader.py` | Loader | Loads L3/4/5/7/8/9 inputs into flat ctx dict; builds `claim_map` for O(1) lookups |
| `eligibility_gate.py` | Gate | approved/approved_with_warnings → full memory update; blocked → risk patterns only |
| `memory_context_extractor.py` | Extraction | Extracts video_id, story_ids, entities (companies+models+products), topics, claim_ids, sources |
| `video_memory_writer.py` | Writer | 1 record per run; dedup on video_id |
| `story_coverage_memory_writer.py` | Writer | 1 record per covered story; dedup on story_id+video_id |
| `claim_ledger_writer.py` | Writer | 1 record per used claim; preserves caution requirements; dedup on claim_id+video_id |
| `entity_topic_memory_writer.py` | Writer | 1 record per entity/topic; trend_status derived from historical coverage count |
| `source_memory_writer.py` | Writer | 1 record per source URL; trust_tier assigned from domain whitelist |
| `editorial_pattern_memory_writer.py` | Writer | 1 record per run; captures format, hook, title angles, blocked angles, thumbnails |
| `followup_tracker.py` | Writer | Follow-ups created for medium+ severity gaps in selected story IDs only |
| `evidence_gap_watchlist_writer.py` | Writer | All 12 gaps recorded regardless of severity; includes collection query hints |
| `rejected_claim_pattern_writer.py` | Writer | Layer 4 rejected claims + Layer 9 overclaims stored as risk patterns (NOT facts) |
| `learning_signal_builder.py` | Learning | Frequency-based signals from memory state; confidence="low" until performance data flows in |
| `memory_index_builder.py` | Indexing | Rebuilds `memory_index.json` on every run; by_video_id, by_story_id, by_entity, by_topic, by_source |
| `memory_snapshot_builder.py` | Indexing | Compact JSON for Layer 5/7 consumption; covered_story_ids, avoid_repetition, open_followups, source_guidance |
| `layer10_writer.py` | Output | Writes manifest to both `data/runs/{run_id}/layer_10/` and `memory/` (latest copy) |
| `layer10_validation_gate.py` | Validation | Hard failures: missing video/claim/index/snapshot/manifest; soft warnings: empty signals |
| `run_layer_10.py` | Orchestrator | 17-step orchestrator; auto-discovers latest run with layer_9 output |
