# Layer 3 Intelligence Pipeline — Design

> Layer 2 gives us: 118 ranked story clusters with scores.  
> Layer 3 turns the top story into a **context packet** — the structured document the script writer uses.

---

## What Layer 3 Produces

The final output is a **context packet** — one JSON file containing everything the script writer needs:

```json
{
  "topic": "Claude Opus 4.7 Release",
  "headline": "Anthropic releases Claude Opus 4.7 with 87% improvement in coding",
  "score": 95,

  "summary": "Anthropic has released Claude Opus 4.7, the latest version of their...",

  "key_facts": [
    {
      "claim": "Claude Opus 4.7 scored 92.3% on SWE-bench",
      "source_url": "https://www.anthropic.com/news/claude-opus-4-7",
      "source_name": "Anthropic (official)",
      "type": "statistic",
      "confidence": "high"
    },
    {
      "claim": "The model is now available via API at the same pricing as Opus 4.5",
      "source_url": "https://www.anthropic.com/news/claude-opus-4-7",
      "source_name": "Anthropic (official)",
      "type": "factual",
      "confidence": "high"
    }
  ],

  "background": "Anthropic last released Opus 4.5 in January 2026, which was...",
  "why_it_matters": "This release narrows the gap between Claude and GPT-5 on...",
  "technical_breakdown": "The key improvements are in the model's ability to...",
  "comparisons": "Compared to GPT-5, Claude Opus 4.7 leads on coding benchmarks but...",
  "audience_angle": "Developers who use Claude for coding will see immediate...",

  "all_sources": [
    {"title": "...", "url": "...", "publisher": "Anthropic", "trust_tier": 1, "type": "official blog"},
    {"title": "...", "url": "...", "publisher": "arXiv", "trust_tier": 1.5, "type": "research paper"},
    {"title": "...", "url": "...", "publisher": "CXOToday", "trust_tier": 2, "type": "news article"}
  ]
}
```

**This is what Layer 4's script writer reads.** It doesn't need to figure out what the story is, what's true, or why it matters — all that thinking is already done here.

---

## Why 5 Modules (Not Fewer)

The original blueprint had 4 (Claim Extractor → Fact Verifier → Research Expander → Context Generator).

I'm proposing 5, but with a clearer separation of responsibilities:

| # | Module | Uses LLM? | Why it's separate |
|---|--------|-----------|------------------|
| 1 | `topic_selector.py` | Optional | You might want to manually pick the topic. Or let the LLM suggest. Either way, the rest of the pipeline takes a topic as input. |
| 2 | `summarizer.py` | ✅ Yes | Synthesizing 6 articles into one coherent narrative is a single focused LLM task. Clean input (source texts) → clean output (summary). |
| 3 | `claim_extractor.py` | ✅ Yes | Extracting claims + mapping each to a source URL is a different LLM task than summarizing. The prompt and output format are completely different. |
| 4 | `context_enricher.py` | ✅ Yes | Adding "why it matters" and background requires the LLM to think beyond the source articles — to bring in general knowledge. That's a different mode than extraction. |
| 5 | `context_builder.py` | ❌ No | Pure code. Just assembles the outputs from steps 1-4 into the final JSON packet. No LLM needed. |

**Why not do it all in one big LLM call?**

You could. But:
- Each module is independently testable (you can run just the summarizer and check if the summary is good)
- If the summary is bad, you only re-run the summarizer — not the whole pipeline
- Different modules can use different LLM profiles (summarizer might use gpt-4o, claim extraction might use Claude for precision)
- Prompts stay focused — a prompt that tries to do everything at once performs worse than focused prompts

---

## The 5 Modules (in execution order)

```
ranked_2026-05-08.json (Layer 2 output)
       │
       ▼
  ┌──────────────────┐
  │ 1. TOPIC SELECTOR │  Pick which story to cover → selected_topic.json
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ 2. SUMMARIZER    │  Read all source articles → synthesis → summary.json
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ 3. CLAIM EXTRACT │  Pull out facts + link each to its source → claims.json
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ 4. ENRICHER      │  Add background, implications, comparisons → enriched.json
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ 5. CTX BUILDER   │  Assemble final packet (code only) → context_packet.json
  └──────────────────┘
```

---

## Module 1: topic_selector.py

### What it does

Takes the ranked stories from Layer 2 and picks which one to cover.

Two modes:
- **Manual mode** (default): Shows you the top 10 ranked stories with scores. You pick by number.
- **LLM mode** (`--auto`): Sends the top 10 to the LLM with this question: *"Which of these stories would make the best YouTube video for an AI-focused audience? Consider freshness, audience interest, depth of available source material, and visual/demo potential."*

### Input → Output

- **Input**: `ranked_2026-05-08.json` (all 118 ranked stories)
- **Output**: `output/layer_3_intelligence/selected_topic_2026-05-08.json`

Contains the selected cluster + all its source documents' full text loaded and ready.

```json
{
  "selected_rank": 1,
  "selected_score": 95,
  "topic": "Claude Opus 4.7 Release",
  "reason": "Official Anthropic announcement with research paper + wide media coverage",
  "source_articles": [
    {"title": "...", "url": "...", "raw_text": "full article text here..."}
  ]
}
```

---

## Module 2: summarizer.py

### What it does

Takes ALL source articles for the selected topic and asks the LLM to produce a **comprehensive synthesis**.

This is NOT just concatenation. The LLM reads 6 articles from different perspectives (official blog, research paper, news coverage, community discussion) and produces one coherent narrative that:
- Covers what happened
- Notes where sources agree
- Notes where sources differ or add unique info
- Preserves specific numbers, dates, and names

### The LLM prompt (simplified)

```
You are a senior research analyst. Below are {N} articles about the same topic 
from different sources. Synthesize them into a comprehensive summary.

Rules:
- Preserve all specific numbers, dates, benchmarks, and quotes
- Note which source each key fact comes from  
- If sources disagree, mention both perspectives
- Write 400-800 words

ARTICLES:
[Source 1: Anthropic Official Blog]
{full text}

[Source 2: arXiv Paper]
{full text}

[Source 3: CXOToday News]
{full text}
...
```

### Input → Output

- **Input**: `selected_topic_2026-05-08.json` (topic + all source texts)
- **Output**: `output/layer_3_intelligence/summaries/summary_2026-05-08.json`

```json
{
  "topic": "Claude Opus 4.7 Release",
  "summary_text": "On May 7, 2026, Anthropic released Claude Opus 4.7...",
  "word_count": 650,
  "sources_referenced": 5,
  "llm_model_used": "gpt-4o"
}
```

---

## Module 3: claim_extractor.py

### What it does

Reads the summary + original source articles and extracts every **verifiable factual claim**, linking each back to its source.

### Why this is separate from the summarizer

The summarizer produces narrative prose. The claim extractor produces a **structured list** of discrete facts. Different output format, different prompt, different quality criteria.

### The LLM prompt (simplified)

```
Below is a summary and the original source articles about "{topic}".

Extract every specific factual claim from the summary. For each claim:
1. The exact claim as a clear statement
2. Which source URL supports this claim
3. The type: "statistic", "quote", "date/event", "opinion", or "factual"
4. Confidence: "high" (directly stated in source), "medium" (implied), "low" (inferred)

Only include claims that are backed by at least one source article.
```

### Input → Output

- **Input**: `summary_2026-05-08.json` + source articles
- **Output**: `output/layer_3_intelligence/claims/claims_2026-05-08.json`

```json
{
  "topic": "Claude Opus 4.7 Release",
  "total_claims": 12,
  "claims": [
    {
      "claim": "Claude Opus 4.7 scored 92.3% on SWE-bench",
      "source_url": "https://www.anthropic.com/news/claude-opus-4-7",
      "source_name": "Anthropic (official blog)",
      "type": "statistic",
      "confidence": "high"
    },
    {
      "claim": "The model uses an improved RLHF training approach",
      "source_url": "https://arxiv.org/abs/2605.05175",
      "source_name": "arXiv research paper",
      "type": "factual",
      "confidence": "medium"
    }
  ]
}
```

### Why this matters for your YouTube channel

When you say "Claude Opus 4.7 scored 92.3% on SWE-bench" in your video, you can show the source on screen. This is what separates a credible AI news channel from one that just repeats rumors. **Every fact you say in the video has a traceable source.**

---

## Module 4: context_enricher.py

### What it does

Takes the summary + claims and asks the LLM to add **context that isn't in the source articles**:

| Section | What the LLM adds |
|---------|-------------------|
| **Background** | What happened before this? Previous Claude versions, the competitive landscape |
| **Why it matters** | What are the implications? For developers, for the industry, for users |
| **Technical breakdown** | Explain the technical aspects simply — for a general audience |
| **Comparisons** | How does this compare to GPT-5, Gemini, Llama? (based on LLM's training knowledge) |
| **Audience angle** | What should the YouTube audience care about most? |

### Why this is separate

The summarizer and claim extractor work strictly FROM the source articles — they don't add anything.
The enricher deliberately goes BEYOND the sources, using the LLM's general knowledge.
That's a fundamentally different task with a different prompt.

### Input → Output

- **Input**: `summary_2026-05-08.json` + `claims_2026-05-08.json`
- **Output**: `output/layer_3_intelligence/research/enriched_2026-05-08.json`

```json
{
  "background": "Anthropic last released Opus 4.5 in January 2026...",
  "why_it_matters": "This release is significant because...",
  "technical_breakdown": "The key improvement is in how the model handles...",
  "comparisons": "Compared to OpenAI's GPT-5, Claude Opus 4.7...",
  "audience_angle": "Developers using Claude for coding will see..."
}
```

---

## Module 5: context_builder.py

### What it does

**Pure code — no LLM.** Reads the outputs from steps 1-4 and assembles them into the final context packet.

This is just merging JSON files into one structured document.

### Input → Output

- **Input**: All files from steps 1-4
- **Output**: `output/layer_3_intelligence/context_packets/context_packet_2026-05-08.json`

This is the **FINAL output of Layer 3** — the one file Layer 4's script writer reads.

---

## LLM Cost Estimate

For the top story with ~6,700 tokens of source text:

| Module | Input tokens | Output tokens | Model | Approx cost |
|--------|-------------|---------------|-------|------------|
| Topic selector (auto) | ~2,000 | ~200 | gpt-4o | $0.01 |
| Summarizer | ~8,000 | ~1,000 | gpt-4o | $0.04 |
| Claim extractor | ~10,000 | ~800 | gpt-4o | $0.04 |
| Context enricher | ~3,000 | ~1,500 | gpt-4o | $0.02 |
| **Total per story** | | | | **~$0.11** |

About **11 cents per story** with GPT-4o. Less with Gemini Flash or a local model.

---

## Summary Table

| Step | Module | LLM? | Input | Output |
|------|--------|------|-------|--------|
| 1 | `topic_selector.py` | Optional | ranked stories | selected topic + source texts |
| 2 | `summarizer.py` | ✅ | source articles | synthesized summary |
| 3 | `claim_extractor.py` | ✅ | summary + sources | verified claims with source URLs |
| 4 | `context_enricher.py` | ✅ | summary + claims | background, implications, comparisons |
| 5 | `context_builder.py` | ❌ | all above | final context packet |

**Layer 3 total: 3 LLM calls, ~$0.11 per story, produces one context packet.**

Layer 4 then reads this context packet and writes the actual YouTube script.

---

> [!IMPORTANT]
> **Key design decision**: The summarizer and claim extractor work strictly FROM source articles (extraction). The enricher deliberately goes BEYOND sources using LLM knowledge (generation). This separation is important — you can always trust claims from step 3 because they map to sources. Step 4's enrichment adds value but should be fact-checked by you before recording.
