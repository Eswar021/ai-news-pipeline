# Deep-Dive Research Architecture (planned)

Status: Design / not built
Last updated: 2026-08-03

## Context

Today a `deep_dive` run **repackages one article**: `video_packaging` picks the
lead story from the shared corpus and `script_generation` expands *that story's
already-collected records* into angle sections. It is deeper than a roundup blurb,
but it is not *researched* — it never looks beyond what ingestion happened to
collect for that one story.

A genuine deep-dive should be **researched before it is written**: given the
selected topic, go to the internet, gather more information from multiple sources
(the primary paper/docs, other outlets, expert takes, counterpoints), and build a
grounded body of material — then write an authoritative, discussion-style script
from *that*.

This is **not a separate system or branch**. It is one new pipeline module that
enriches the source material for the deep_dive format; everything else (the
module contract, orchestration, config, provenance, the deep_dive script format)
is reused unchanged.

## Where it fits

A new content module `topic_research` runs in the deep_dive **Phase-2**, between
`video_packaging` (which picks the topic) and `script_generation` (which writes
it). It is **format-gated**: roundup skips it; deep_dive requires it.

```mermaid
flowchart TB
  ES["editorial_selection<br/><small>(shared corpus)</small>"] --> VP["video_packaging<br/><small>picks the lead topic</small>"]
  VP --> TR
  subgraph TR["topic_research  — NEW module (deep_dive only)"]
    direction TB
    Q["1 · Frame<br/><small>LLM → focused research questions<br/>(what happened · mechanism · numbers · history · skeptics · primary source)</small>"]
    Q --> S["2 · Search<br/><small>web search per question (Tavily / Exa)</small>"]
    S --> F["3 · Fetch + extract<br/><small>clean passages, dedup, rank; reuse evidence_prep cleaning</small>"]
    F --> SY["4 · Synthesize<br/><small>LLM → grounded research dossier</small>"]
  end
  TR --> SG["script_generation (deep_dive)<br/><small>writes from the dossier, not one article</small>"]
  SG --> MD["metadata_creator → voiceover → visuals"]
```

## The research dossier (module output)

`topic_research.run(input) -> dict` returns a structured, **grounded** dossier
that `script_generation` consumes as its source context in place of (or alongside)
the single story's records:

- **claims** — each with supporting evidence and the source it came from
- **quotes** — verbatim, attributed to a person/outlet
- **numbers / benchmarks** — with units and source
- **timeline** — how the story unfolded (dated events)
- **angles** — candidate facets for the director to build sections around
- **counterpoints / skeptics** — the honest other side
- **sources** — the fetched URLs, each fingerprinted like current provenance

Every item carries a source reference; nothing is un-cited. This keeps the same
source-fidelity discipline the pipeline already enforces (no fabrication; measured
vs claimed preserved; exact quotes).

## Design principles (same as the rest of the pipeline)

- **Pure module.** `run(input_json) -> dict`, Pydantic-validated; the orchestrator
  persists artifacts. No new architecture.
- **LLM for judgment, code for guardrails.** LLM frames questions and synthesizes;
  deterministic code does search/fetch/cleaning, dedup, provenance + fingerprints,
  and caps (max questions, max sources, max depth).
- **Config-driven.** Search provider, research depth (questions × sources), model,
  `reasoning_effort`, and `prompt_version` all live in the profile
  (`profiles/daily_deep_dive/content/topic_research.yaml`). No hardcoding.
- **Grounded + bounded.** Every claim cites a fetched source; a config-driven hard
  cap bounds search/fetch cost and time. No un-sourced synthesis.

## New dependencies / decisions to make

- **Search capability** the *pipeline* owns (distinct from the agent tools used in
  chat). Recommended: **Tavily** or **Exa** — built for agentic research, return
  clean extracted content + citations. Alternative: a general search API (Serper /
  Brave) + the existing fetch/clean stack.
- **Cost + time.** Adds N search calls + fetches + 2 LLM passes (frame, synthesize)
  on top of the ~14 min deep_dive script. Budget it via the depth caps.
- **Embeddings (optional).** Reuse `all-MiniLM` (already in story_mapping) to dedup
  and rank fetched passages before synthesis.
- **Trust / recency.** Prefer primary sources and trusted outlets; timestamp-filter
  to the story window where relevant.

## Build outline

1. `content/topic_research/` module: `contract.py` (dossier schema), `app.py`
   (frame → search → fetch → synthesize), `prompts/v1/{framer,synthesizer}/`,
   a `search_client` (Tavily/Exa) + reuse of evidence_prep cleaning.
2. Wire it into the deep_dive Phase-2 module sequence (format-gated in
   `stages/content.py` / the format's app list), and add
   `topic_research.yaml` to the `daily_deep_dive` profile.
3. Point deep_dive `script_generation` at the dossier as `source_context`.
4. Validate with a real deep_dive run + editorial review (before/after vs the
   current repackage-one-article deep_dive).
