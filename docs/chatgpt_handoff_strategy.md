# ChatGPT Handoff Strategy

## What we are doing and why

Our pipeline collects, processes, and structures AI news data automatically. But writing
a compelling YouTube script is a creative job — it requires judgment about what's interesting,
how to sequence stories, and how to phrase things for a specific audience.

Rather than automate the creative writing with more API calls (and more cost per run), we
stop the pipeline at a chosen point, export everything into three structured files, and hand them
to ChatGPT. ChatGPT is extremely good at this task when given clean, structured input —
which is exactly what our pipeline produces.

**The division of labor:**

| What our pipeline does | What ChatGPT does |
| --- | --- |
| Collects news from 10+ sources automatically | Reads and understands the data |
| Deduplicates and clusters related stories | Selects which stories to cover |
| Scores stories for newsworthiness | Decides the story order |
| Extracts and verifies individual claims | Writes the hook, segments, transitions |
| Records which sources back each claim | Produces inline `[SOURCE:]` citations for on-screen visuals |
| Tracks what we've already covered | Ensures the script has the right tone |
| Flags evidence gaps and company-only stories | Handles honest uncertainty appropriately |

---

## The three handoff files

Every `python chatgpt_export.py` run produces three files in `output/chatgpt_handoffs/{run_id}/`:

### `01_instructions.md` — paste this first

The complete brief for ChatGPT. Contains:
- Channel identity (name, content promise, tone) pulled from the run manifest
- Audience profile (who watches, what they want, what they hate)
- Video format requirements (type, length, story count, structure)
- Language rules (short sentences, no hollow openers, zero hype words, active voice)
- Source citation format (`[SOURCE: domain/path]` tags for every factual sentence)
- Step-by-step writing task (8 steps from reading to close)
- Content memory from previous runs (what to avoid repeating)
- Memory update JSON format (required output after the script)

### `02_stories.md` — paste alongside instructions

All collected stories with everything ChatGPT needs to write from. For each story:
- Title, type, importance score, priority bucket
- **Source coverage** — e.g. "Official: 2 | Independent: 0 — ⚠ Company-only"
  (tells ChatGPT exactly when to use "according to" vs stating as fact)
- Companies, models, products, topics
- **Full article text** for every cluster member document
- **Why it ranked** — human-readable reasons (e.g. "major_company, model_release")
- ✓ FACTS badge and verified fact sheet for stories that went through Layer 4:
  - Each verified fact with its `[SOURCE: domain/path]` tag pre-populated
  - Claims requiring cautious language flagged separately
  - Rejected claims listed so ChatGPT knows what to avoid
  - Evidence gaps explicitly called out

### `03_dump.md` — use if ChatGPT needs to go deeper

The raw everything. Use in Deep Research mode or when a story needs more depth:
- All source documents **grouped by story** (with independence flag)
- Full article text for every document (no truncation)
- Extracted source span paragraphs (the exact passages used for fact extraction)
- All verified claims with their source URLs
- Entity and topic map for all 41 stories
- Story timeline
- Cross-run memory snapshot

---

## The three handoff points

### Option 1: Stop after Layer 3 — `collection_only`

**Run:** `python pipeline.py` (default, zero API cost)

**What you get in `02_stories.md`:** All ranked stories with full article texts, source
independence flags, entity tags, and ranking reasons. No individual fact extraction.

**`03_dump.md`:** All raw source documents grouped by story, extracted paragraphs,
entity and topic map, timeline.

**ChatGPT's job:** Read all story articles, decide which 5–8 to cover, and write the script.
In Deep Research mode it should visit the source URLs to verify and enrich.

**When to use:** Quick turnaround. You want ChatGPT to have full creative freedom and will
use Deep Research mode to fill in specifics.

**Limitation:** No fact-level verification. ChatGPT must do its own research to get
specific numbers and current details.

---

### Option 2: Stop after Layer 4 — `with_facts` ← **Recommended**

**Run:** `python pipeline.py --preset with_facts` (~218 API calls)

**What you get in `02_stories.md`:** Everything from Layer 3, plus for the top stories:
- Verified facts with individual `[SOURCE: domain/path]` tags already filled in
- Cautious claims flagged with recommended qualifying language
- Rejected claims listed ("do not use — opinion/prediction")
- Evidence quality summary: "18 verified claims | 2 primary sources | 0 independent"
- Format safety (roundup: safe / deep_dive: safe)
- Evidence gaps explicitly listed

**`03_dump.md`:** All of the above plus all verified claims with source URLs grouped by story.

**ChatGPT's job:** Use the structured facts to write a compelling script. The hard
verification work is already done — it just needs to make it engaging. The `[SOURCE:]`
tags are pre-populated for every claim.

**Why this is the sweet spot:**
- Our pipeline verified the facts (Layer 4)
- ChatGPT writes the creative layer (hook, narrative, transitions)
- The script comes out with accurate citations because source URLs are embedded in the data

---

### Option 3: Stop after Layer 6 — `with_editorial`

**Run:** `python pipeline.py --preset with_editorial` (~230 API calls)

**What you get:** Everything from Layer 4, plus an editorial brief that already specifies
which format to use, which stories were selected, and the target audience profile in detail.

**ChatGPT's job:** Just write the script to the brief. No selection decisions needed.

**When to use:** When you want the pipeline to make editorial decisions too. Less creative
freedom for ChatGPT — it follows the brief rather than making its own choices.

---

## The complete workflow

```
Step 1: Run the pipeline
   python pipeline.py --preset with_facts

Step 2: Export the handoff files
   python chatgpt_export.py

   (or with explicit run ID)
   python chatgpt_export.py --run-id run_2026_05_10_48h_auto

Step 3: Open the output folder
   output/chatgpt_handoffs/{run_id}/

Step 4: Open ChatGPT in Deep Research mode (recommended) or standard GPT-4o

Step 5: Paste 01_instructions.md into the ChatGPT text box
   Then paste 02_stories.md in the same message (or follow-up immediately)
   ChatGPT will confirm it has both before writing

Step 6: If ChatGPT needs more depth on any story
   Paste sections from 03_dump.md (or the whole file if using Deep Research)

Step 7: Review the script
   - Check [SOURCE:] tags are accurate
   - Check evidence gaps are handled with appropriate uncertainty
   - Review any Deep Research additions ChatGPT found independently

Step 8: Get the memory update JSON from ChatGPT
   ChatGPT outputs a memory_update JSON block at the end of the script.
   (Currently manual — future: parse and feed back into memory system)

Step 9: Run Layer 10 when the video is published
   python pipeline.py --run-id {run_id} --layers 10
   This updates memory so the next run's handoff avoids repeating this content.
```

---

## Why we don't run the full pipeline every time

Running Layers 7–9 (hook generation, script writing, verification) costs ~22 more API
calls and takes more time, but produces output that is often lower quality than
what ChatGPT gives you for free. The difference:

- Our pipeline produces a rigid script structure (it follows a template)
- ChatGPT produces a more natural, conversational script
- ChatGPT is significantly better at narrative judgment and pacing

The one reason to run the full pipeline (`full_auto`) is if you want completely
hands-off, automated output — for example, scheduling runs overnight. In that case
the script goes through Layer 9 verification before it reaches you.

---

## What the memory system does for ChatGPT handoffs

Every time we complete a video (after Layer 10 runs), the system records:
- Which stories were covered (`story_coverage_memory.jsonl`)
- Which title angles and hook types were used (`editorial_pattern_memory.jsonl`)
- Which angles are blocked (`blocked_title_angles`)

When you run `chatgpt_export.py`, these are read from `memory/memory_snapshot.json`
and included in `01_instructions.md` as the "CONTENT MEMORY — WHAT TO AVOID" section.
ChatGPT automatically knows not to repeat angles or stories from previous videos —
without you having to manage this manually.

---

## Files involved

| File | Purpose |
| --- | --- |
| `config/pipeline_config.yaml` | Controls which layers run and default preset |
| `config/chatgpt_prompts.yaml` | Controls the ChatGPT instructions (edit to change tone, format, etc.) |
| `pipeline.py` | Runs the pipeline |
| `chatgpt_export.py` | Generates the three handoff files |
| `output/chatgpt_handoffs/{run_id}/01_instructions.md` | Paste into ChatGPT text box (the prompt) |
| `output/chatgpt_handoffs/{run_id}/02_stories.md` | All stories with article text + verified facts + SOURCE tags |
| `output/chatgpt_handoffs/{run_id}/03_dump.md` | Full dump: every doc, every claim, every span, for deep research |
| `memory/memory_snapshot.json` | Cross-run memory (what to avoid in this video) |

---

## Customizing the ChatGPT instructions

Everything ChatGPT sees is controlled by `config/chatgpt_prompts.yaml`. You can edit:

- `channel.tone` — change the voice/style
- `channel.audience` — change who the script is written for
- `channel.language_rules` — add/remove specific things ChatGPT should avoid saying
- `script_requirements.target_duration_minutes` — make shorter or longer scripts
- `handoff_levels.after_layer_4.chatgpt_must` — add specific requirements

After editing the config, just re-run `chatgpt_export.py` — no code changes needed.
