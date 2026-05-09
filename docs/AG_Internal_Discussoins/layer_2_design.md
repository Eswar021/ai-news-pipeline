# Layer 2 Processing Pipeline — Design

> Layer 1 is closed. `run_extraction.py` produced **153 documents** in one master file.  
> Now let's design exactly what Layer 2 does.

---

## What Layer 2 Produces

Layer 2 takes 153 scattered documents and produces:

```
"Here are today's top AI stories, ranked by importance.
 Each story has all its source articles grouped together."
```

Concretely, the output is a file like this:

```json
{
  "date": "2026-05-08",
  "total_stories": 8,
  "stories": [
    {
      "rank": 1,
      "score": 85,
      "topic": "Google Chrome silently installs 4GB AI model",
      "source_count": 5,
      "sources": [
        { "title": "...", "url": "...", "source_type": "community_signal", "trust_tier": 3, "publisher": "HackerNews", "score": 1655 },
        { "title": "...", "url": "...", "source_type": "tech_news_api", "trust_tier": 2, "publisher": "Mediastack" },
        { "title": "...", "url": "...", "source_type": "tech_news_api", "trust_tier": 2, "publisher": "Newsdata" }
      ],
      "score_breakdown": {
        "multiple_sources": 20,
        "major_company": 15,
        "consumer_impact": 10,
        "high_community_signal": 10,
        "official_source_present": 30
      }
    },
    {
      "rank": 2,
      "score": 72,
      "topic": "Anthropic higher usage limits + SpaceX deal",
      "source_count": 3,
      "sources": ["..."]
    }
  ]
}
```

**This is what Layer 3 reads** to decide "which of these stories should become a video."

---

## The 4 Modules (in execution order)

I originally had 5 (cleaner + normalizer + dedup + cluster + ranker) but cleaner and normalizer
are really the same job — standardize the data format. So it's 4 modules:

```
master_2026-05-08.json
       │
       ▼
  ┌─────────────┐
  │ 1. NORMALIZE │  Standardize all 153 docs into one uniform field set
  └─────┬───────┘
        ▼
  ┌─────────────┐
  │ 2. DEDUP    │  Remove duplicate articles (same story from different APIs)
  └─────┬───────┘
        ▼
  ┌─────────────┐
  │ 3. CLUSTER  │  Group articles that are about the same story
  └─────┬───────┘
        ▼
  ┌─────────────┐
  │ 4. RANK     │  Score each cluster by importance
  └─────┬───────┘
        ▼
  ranked_stories_2026-05-08.json
```

---

## Module 1: normalizer.py

### Problem it solves

Right now the 153 docs have **different fields** depending on source:

| Field | arXiv | HackerNews | NewsAPI | GitHub | Blog |
|-------|-------|-----------|---------|--------|------|
| `title` | ✅ | ✅ | ✅ | ✅ (repo name) | ✅ |
| `url` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `published_at` | ISO format | ISO format | ISO format | ISO format | "Thu, 07 May 2026" |
| `raw_text` | abstract | (empty for links) | description (truncated) | README (huge) | full article |
| `authors` | ✅ list | single `author` | single `author` | `author` (owner) | `author` |
| `score` | ❌ | ✅ (upvotes) | ❌ | `stars` | ❌ |
| `categories` | ✅ | ❌ | ❌ | `topics` | ❌ |
| `description` | ❌ | ❌ | ✅ | ✅ | ❌ |

### What it does

Reads every doc, maps it to a **uniform schema** with exactly these fields:

```json
{
  "document_id": "...",
  "source_id": "...",
  "source_type": "research_paper | tech_news_api | community_signal | ...",
  "trust_tier": 1.5,
  "title": "...",
  "url": "...",
  "published_at": "2026-05-08T10:00:00Z",     ← always ISO 8601
  "author": "...",
  "publisher": "...",                           ← standardized
  "raw_text": "...",                            ← cleaned, no HTML remnants
  "description": "...",                         ← short summary if available
  "content_hash": "...",
  "collected_at": "...",
  "community_score": 0,                        ← HN upvotes, GitHub stars, or 0
  "comment_count": 0,                          ← HN comments, or 0
  "categories": [],                            ← arXiv cats, GitHub topics, etc.
  "entities": []                               ← extracted company/model names
}
```

**Key thing it does**: extracts entities (company names, model names) from the title + text using keyword matching. This is what the clusterer uses later.

```
Title: "OpenAI releases GPT-5 with new reasoning capabilities"
→ entities: ["OpenAI", "GPT-5"]
```

### Input → Output

- **Input**: `master_2026-05-08.json` (153 docs, mixed schemas)
- **Output**: `output/layer_2_processed/documents/normalized_2026-05-08.json` (153 docs, uniform schema)

---

## Module 2: deduplicator.py

### Problem it solves

Multiple news APIs return the **same article**. Example from our actual data:

```
NewsAPI:    "Apple Reaches $250 Million Settlement Over Claims It Misled People on A.I."
Mediastack: "Apple Reaches $250 Million Settlement Over Claims It Misled People on A.I."
```

Same title, same story, from NYT — but collected via two different APIs.

### What it does

Two dedup passes:

**Pass 1 — Exact URL match**: If two docs have the same URL (after stripping tracking params like `utm_source`), keep the one with more content.

**Pass 2 — Title similarity**: If two docs from different sources have very similar titles (>80% word overlap), merge them into one entry, keeping the richer one and noting the other as an "also reported by" reference.

### Input → Output

- **Input**: `normalized_2026-05-08.json` (153 docs)
- **Output**: `output/layer_2_processed/documents/deduplicated_2026-05-08.json` (~100-120 docs, fewer dupes)

---

## Module 3: clusterer.py

### Problem it solves

After dedup, we might still have 100+ unique documents. But many are about the **same story** from different angles:

```
Article 1:  "Cloudflare lets AI agents create accounts and deploy"   (HackerNews, 628 upvotes)
Article 2:  "Agents can now create Cloudflare accounts"              (NewsAPI)
Article 3:  "Cloudflare launches AI agent deployment tools"          (Mediastack)
```

These are 3 articles about 1 story. The clusterer groups them.

### What it does

For each pair of documents, check if they should be in the same cluster:

```
Condition 1: Share 2+ entity names (e.g. both mention "Cloudflare" + "AI agents")
Condition 2: Published within 48 hours of each other
Condition 3: Title word overlap > 50%
```

If ANY two of these three conditions are true → same cluster.

Algorithm: simple single-pass greedy clustering. For each document, check against existing clusters. If it matches → add to cluster. If not → start new cluster.

Each cluster gets a `topic` label = the most common entity combination + the most frequent title words.

### Input → Output

- **Input**: `deduplicated_2026-05-08.json` (~100-120 docs)
- **Output**: `output/layer_2_processed/clusters/clusters_2026-05-08.json` (~20-40 story clusters)

Output structure:
```json
{
  "cluster_id": "cluster_001",
  "topic": "Cloudflare AI agent deployment",
  "entities": ["Cloudflare", "AI agents"],
  "source_count": 3,
  "trust_tiers_present": [2, 3],
  "earliest_published": "2026-05-07T10:00:00Z",
  "documents": ["doc_id_1", "doc_id_2", "doc_id_3"],
  "best_title": "Agents can now create Cloudflare accounts, buy domains, and deploy"
}
```

---

## Module 4: ranker.py

### Problem it solves

We have ~30 story clusters. Not all are video-worthy. Which ones matter most?

### How it actually works — 5 scoring dimensions

The ranker doesn't score individual documents. It looks at the **cluster as a whole** and evaluates it across 5 dimensions. Each dimension asks a different question about the cluster's quality.

#### Dimension 1: Source Authority (max 30 points)

> "How trustworthy is the best source covering this story?"

Look at the **highest trust tier** present in the cluster:

```
Has a Tier 1 source (official company blog)         → 30 pts
Best source is Tier 1.5 (research paper, arXiv)      → 20 pts
Best source is Tier 2 (news API — Verge, NYT, etc.)  → 10 pts
Only Tier 3 sources (HN, Reddit, GitHub)             →  0 pts
```

This is not additive per source. It checks the single best tier in the cluster.
Having 5 Tier 2 sources still gives 10, not 50.

#### Dimension 2: Source Coverage (max 25 points)

> "How many independent publishers covered this story?"

Count **distinct publishers** (not distinct documents — if NewsAPI and Newsdata both returned the same NYT article, that's 1 publisher):

```
1 publisher only        →  0 pts
2 publishers            → 10 pts
3-4 publishers          → 15 pts
5+ publishers           → 25 pts
```

#### Dimension 3: Community Engagement (max 20 points)

> "Are developers/people actually talking about this?"

Look at the **max community score** across all docs in the cluster:

```
HN score > 500 OR GitHub stars > 10,000   → 15 pts
HN score 200-500 OR GitHub stars 1k-10k   → 10 pts
HN score 50-200                           →  5 pts
Below 50 or no community source           →  0 pts

Bonus: HN comments > 100                  → +5 pts
```

#### Dimension 4: Entity Significance (max 15 points)

> "Is a major company or product involved?"

Check the entities extracted by the normalizer:

```
Major AI company (OpenAI, Anthropic, Google, Meta, Microsoft, NVIDIA, Apple, Amazon)  → 15 pts
Known AI product/model (GPT, Claude, Gemini, Llama, Stable Diffusion)                → 10 pts
Other known company or product                                                        →  5 pts
No recognized entity                                                                  →  0 pts
```

#### Dimension 5: Content Richness (max 10 points)

> "What variety of source types does this cluster have?"

Check which source_types are present (cap at 10 total):

```
Has official_company_blog   → +4 pts
Has research_paper          → +3 pts
Has community_signal        → +2 pts
Has tech_news_api           → +2 pts
Has video_or_podcast        → +2 pts
(capped at 10)
```

A cluster with blog + research paper + HN discussion = 4+3+2 = 9 pts. Rich story.
A cluster with only news API articles = 2 pts. Thin coverage.

---

### Total score: max 100 points

```
Source Authority     → max 30
Source Coverage      → max 25
Community Engagement → max 20
Entity Significance  → max 15
Content Richness     → max 10
────────────────────────────
TOTAL                → max 100
```

---

### Worked Example 1: "Google Chrome silently installs 4GB AI model"

Documents in this cluster:
- HackerNews: 1706 upvotes, 1117 comments (Tier 3)
- Mediastack: NYT, BBC coverage (Tier 2)
- Newsdata: additional coverage (Tier 2)

Scoring:
```
1. Source Authority:   Best tier = 2 (news media)          → 10
2. Source Coverage:    3+ distinct publishers               → 15
3. Community:          HN 1706 > 500 → 15, comments > 100 → +5 = 20
4. Entity:             Google = major company               → 15
5. Content Richness:   community + news = 2+2               →  4
────────────────────────────────────────────────────
TOTAL: 10 + 15 + 20 + 15 + 4 = 64
```

### Worked Example 2: "Anthropic higher usage limits + SpaceX deal"

Documents in this cluster:
- Anthropic official blog (Tier 1)
- HackerNews: 399 upvotes, 350 comments (Tier 3)
- NewsAPI: TechCrunch coverage (Tier 2)

Scoring:
```
1. Source Authority:   Best tier = 1 (official blog!)       → 30
2. Source Coverage:    3 distinct publishers                 → 15
3. Community:          HN 399 → 200-500 range → 10, comments > 100 → +5 = 15
4. Entity:             Anthropic = major company             → 15
5. Content Richness:   blog + community + news = 4+2+2       →  8
────────────────────────────────────────────────────
TOTAL: 30 + 15 + 15 + 15 + 8 = 83
```

**The Anthropic story ranks HIGHER (83 vs 64)** because it has an official company source.
The Chrome story has more buzz but no official Google statement — just media speculation.
This is exactly the behavior we want: official source = most video-worthy.

---

### Input → Output

- **Input**: `clusters_2026-05-08.json` + `deduplicated_2026-05-08.json` (for full doc details)
- **Output**: `output/layer_2_processed/rankings/ranked_2026-05-08.json` (sorted story clusters with scores + breakdowns)

This is the **FINAL output of Layer 2** — the file Layer 3 picks up.

---

## Summary: What Each Step Produces

| Step | Input | Output | Result |
|------|-------|--------|--------|
| `run_extraction.py` | APIs | `master_2026-05-08.json` | 153 raw docs from 8 sources |
| `normalizer.py` | 153 raw docs | `normalized_2026-05-08.json` | 153 docs, uniform schema, entities extracted |
| `deduplicator.py` | 153 normalized | `deduplicated_2026-05-08.json` | ~100-120 unique docs |
| `clusterer.py` | ~100 unique | `clusters_2026-05-08.json` | ~20-40 story clusters |
| `ranker.py` | ~30 clusters | `ranked_2026-05-08.json` | Ranked stories with importance scores |

**None of these use LLM.** All pure Python code. Zero API costs.

---

## After Layer 2 Is Done

Layer 3 reads `ranked_2026-05-08.json` and asks the LLM:
- "From these top 5 stories, which one should be today's video?"
- "Summarize all source articles for that story"
- "Extract and verify claims"
- "Build a context packet for the script writer"

But that's for later. Layer 2 first.

**Ready to build?**
