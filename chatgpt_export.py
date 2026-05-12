"""
ChatGPT Handoff Exporter

Reads pipeline output and generates three files you use together in ChatGPT:

    01_instructions.md  — paste this in the ChatGPT text box first (the prompt)
    02_stories.md       — all stories with article text + verified facts
    03_dump.md          — everything collected (raw docs, claims, full entity data)

Usage:
    python chatgpt_export.py --run-id run_2026_05_10_48h_auto
    python chatgpt_export.py --run-id run_2026_05_10_48h_auto --level after_layer_4
    python chatgpt_export.py   # auto-discovers latest run

Levels (auto-detected from run output if not specified):
    after_layer_3   — story article text only (no verified facts)
    after_layer_4   — verified facts + article text (RECOMMENDED)
    after_layer_6   — editorial brief + verified facts + article text

Output:
    output/chatgpt_handoffs/{run_id}/01_instructions.md
    output/chatgpt_handoffs/{run_id}/02_stories.md
    output/chatgpt_handoffs/{run_id}/03_dump.md
"""

import sys
import json
import yaml
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config.paths import RUNS_DIR, MEMORY_DIR, OUTPUT_DIR, CONFIG_DIR

PROMPTS_CONFIG = CONFIG_DIR / "chatgpt_prompts.yaml"
HANDOFFS_DIR   = OUTPUT_DIR / "chatgpt_handoffs"


# ─────────────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────────────

def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(path: Path) -> list:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def _detect_level(run_dir: Path) -> str:
    if (run_dir / "layer_6").exists():
        return "after_layer_6"
    if (run_dir / "layer_4").exists():
        return "after_layer_4"
    return "after_layer_3"


def _build_doc_map(run_dir: Path) -> dict:
    """doc_id → full canonical_documents record (incl. clean_text_path)"""
    result = {}
    for rec in _load_jsonl(run_dir / "layer_2" / "canonical_documents.jsonl"):
        doc_id = rec.get("canonical_document_id", "")
        if doc_id:
            result[doc_id] = {
                "canonical_url":   rec.get("canonical_url", rec.get("original_url", "")),
                "clean_text_path": rec.get("clean_text_path", ""),
                "title":           rec.get("title", ""),
                "published_at":    rec.get("published_at", ""),
                "source_type":     rec.get("source_type", ""),
                "trust_tier":      rec.get("trust_tier", ""),
                "source_name":     rec.get("source_name", ""),
                "word_count":      rec.get("word_count", "?"),
            }
    return result


def _build_cluster_map(run_dir: Path) -> dict:
    """story_id → full cluster record"""
    data = _load_json(run_dir / "layer_3" / "story_clusters.json")
    if not data:
        return {}
    return {c["story_id"]: c for c in data.get("story_clusters", [])}


def _build_ranked_map(run_dir: Path) -> dict:
    """story_id → ranked_story record (score_breakdown, ranking_reasons)"""
    data = _load_json(run_dir / "layer_3" / "ranked_stories.json")
    if not data:
        return {}
    return {s["story_id"]: s for s in data.get("ranked_stories", [])}


def _url_short(url: str) -> str:
    """https://openai.com/index/foo → openai.com/index/foo"""
    return url.replace("https://", "").replace("http://", "").rstrip("/")


def _read_article_text(doc_meta: dict, max_words: int = 800) -> str:
    path_str = doc_meta.get("clean_text_path", "")
    if not path_str:
        return ""
    p = Path(path_str)
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8").strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


# ─────────────────────────────────────────────────────────────────────────────
# FILE 1 — Instructions
# ─────────────────────────────────────────────────────────────────────────────

def _load_run_manifest(run_id: str) -> dict:
    p = RUNS_DIR / run_id / "run_manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def build_instructions(run_id: str, level: str, cfg: dict, level_cfg: dict,
                       n_stories: int, n_with_facts: int) -> str:
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    script   = cfg["script_requirements"]
    manifest = _load_run_manifest(run_id)

    # Pull channel identity from run manifest (richer than config)
    ch_strategy  = manifest.get("channel_strategy", {})
    aud_strategy = manifest.get("audience_strategy", {})
    fmt_strategy = manifest.get("format_strategy", {})
    run_request  = manifest.get("run_request", {})

    channel_name    = ch_strategy.get("channel_name", cfg["channel"]["name"])
    content_promise = ch_strategy.get("content_promise", "")
    tone_style      = ch_strategy.get("tone", {})
    tone_avoid      = tone_style.get("avoid", [])
    tone_desc       = (
        f"{tone_style.get('style','').replace('_',' ')}, "
        f"{tone_style.get('energy','').replace('_',' ')} energy, "
        f"{tone_style.get('attitude','').replace('_',' ')}"
    ).strip(", ")

    aud_name        = aud_strategy.get("name", "AI developers and tech professionals")
    aud_expertise   = aud_strategy.get("explanation_depth", "medium")
    aud_jargon      = aud_strategy.get("jargon_allowed", "limited")
    aud_guidance    = aud_strategy.get("script_guidance", {})
    aud_wants       = cfg["channel"].get("audience_wants", [
        "Accurate, evidence-backed information",
        "Context on why developments matter to them practically",
        "Honest uncertainty — 'we don't know yet' is better than confident guessing",
    ])
    aud_hates       = cfg["channel"].get("audience_hates", [
        "Hype, vague superlatives, and claims without evidence",
        "Repeating what they already know",
        "Being talked down to — they know what an LLM is",
    ])

    fmt_eligible    = fmt_strategy.get("eligible_formats", ["roundup"])
    fmt_req         = fmt_strategy.get("format_requirements", {})
    primary_fmt     = fmt_eligible[0] if fmt_eligible else "roundup"
    fmt_details     = fmt_req.get(primary_fmt, {})
    target_mins     = fmt_details.get("target_duration_minutes", script["target_duration_minutes"][1])
    min_stories     = fmt_details.get("min_stories", script["stories_per_video"][0])
    max_stories     = fmt_details.get("max_stories", script["stories_per_video"][1])
    pacing          = fmt_details.get("pacing", "fast")
    lookback        = run_request.get("lookback_hours", 48)

    has_facts_note = (
        f"{n_with_facts} of these have verified, source-checked fact sheets (marked ✓ FACTS). "
        f"The remaining {n_stories - n_with_facts} have the original article text."
        if n_with_facts else
        f"All {n_stories} include the original article text. No fact-level verification was run."
    )

    # ── Avoid section from memory ─────────────────────────────────────────────
    avoid_block = ""
    snap_path   = MEMORY_DIR / "memory_snapshot.json"
    if snap_path.exists():
        snap    = json.loads(snap_path.read_text(encoding="utf-8"))
        avoid   = snap.get("avoid_repetition", {})
        covered = snap.get("covered_story_ids", [])
        angles  = [a for a in avoid.get("recent_title_angles", []) if a]
        hooks   = [h for h in avoid.get("recent_hook_types", []) if h]
        blocked = [b for b in avoid.get("blocked_title_angles", []) if b]
        av_lines = []
        if angles:
            av_lines.append("**Do NOT reuse these title angles from previous videos:**")
            av_lines.extend(f"- {a}" for a in angles)
            av_lines.append("")
        if hooks:
            av_lines.append("**Vary the hook — these hook types were used recently:**")
            av_lines.extend(f"- {h}" for h in hooks)
            av_lines.append("")
        if blocked:
            av_lines.append("**Permanently blocked angles — never use:**")
            av_lines.extend(f"- {b}" for b in blocked)
            av_lines.append("")
        if covered:
            av_lines.append(f"**Stories already covered in previous videos ({len(covered)}) — skip or cover only what is genuinely new:**")
            av_lines.extend(f"- `{sid}`" for sid in covered)
            av_lines.append("")
        if av_lines:
            avoid_block = "## CONTENT MEMORY — WHAT TO AVOID\n\n" + "\n".join(av_lines) + "---\n\n"

    # ── Audience wants/hates lines ────────────────────────────────────────────
    wants_lines = "\n".join(f"- {w}" for w in aud_wants) if aud_wants else "- Accurate, evidence-backed information\n- Context on why it matters to them practically"
    hates_lines = "\n".join(f"- {h}" for h in aud_hates) if aud_hates else "- Hype and vague claims\n- Repeating what they already know"
    tone_avoid_lines = "\n".join(f"- \"{t}\"" for t in tone_avoid) if tone_avoid else "- Panic, fake certainty, unsupported hype"

    return f"""# TASK BRIEF — YouTube Script for "{channel_name}"

> **How to use these three files:**
> 1. Paste this file (`01_instructions.md`) into the ChatGPT chat box
> 2. Paste or upload `02_stories.md` in the same message (this has all the story data)
> 3. `03_dump.md` is available if you need to go deeper on any story — paste it if needed

**Generated:** {now}  |  **Run:** `{run_id}`  |  **Data level:** {level_cfg['label']}

---

## WHO YOU ARE AND WHAT YOU'RE MAKING

You are a professional YouTube scriptwriter for **"{channel_name}"** — a tech news channel with a clear promise to its viewers:

> *"{content_promise}"*

You are writing a **{primary_fmt} video** covering the most important AI developments from the **last {lookback} hours**.

This script will be **read on camera** by the host. Every sentence must work spoken aloud. The host will also **show source URLs on screen** as visual overlays while reading — so every factual claim in the script must end with a `[SOURCE: domain/path]` tag so the video editor knows exactly which source graphic to show.

---

## ABOUT THE AUDIENCE

**Who watches this channel:** {aud_name}. Explanation depth: {aud_expertise}. Jargon: {aud_jargon}.

**What they want:**
{wants_lines}

**What they hate:**
{hates_lines}

**Key implication:** Do not explain what an LLM is. Do not explain what fine-tuning means. Do explain what a new model's capabilities mean in practice, what a product change means for developers, or why a research result matters to people building with AI.{"" if not aud_guidance.get("define_terms") else " Always define new product names and acronyms on first use."}{"" if not aud_guidance.get("include_business_impact") else " Always include the business/practical impact — who does this affect and how?"}

---

## THE DATA YOU HAVE

I ran an automated pipeline that collected AI news from the last {lookback} hours across official company blogs, research preprints, and tech news sources.

**`02_stories.md`** — **{n_stories} stories** with full article text. {has_facts_note}

**`03_dump.md`** — Raw dump: all {n_stories * 2}+ source documents, all extracted claims, entity maps, story timeline, cross-run memory.

### If you are using ChatGPT Deep Research mode:

You SHOULD actively browse the source URLs provided in `02_stories.md`. Here is why and how:

- **Verify the facts.** Our pipeline extracted claims automatically. Visit the source pages to confirm the facts are correct and current. If a page has been updated since we collected it, use the current version.
- **Find what we missed.** Read the full articles. Look for specific numbers, quotes, or context that would make the story more compelling on video. Our automated extraction may have missed the best detail.
- **Search for reactions.** For the top stories, search for independent coverage, analyst reactions, or developer responses. These add context our pipeline cannot capture. Clearly label any extra context you find as `[SOURCE: browsed — domain.com]`.
- **Check for conflicts.** If you find information that contradicts what's in `02_stories.md`, flag it explicitly in the script.

### If you are NOT in Deep Research mode:

Use the article text in `02_stories.md` as your source. Do not add facts from your training data — the goal is to report what actually happened this week, not what the models in these articles have done historically.

---

## VIDEO FORMAT REQUIREMENTS

**Type:** {primary_fmt.upper()}
**Target length:** {target_mins} minutes when read at normal speaking pace (~{target_mins * 150} words)
**Stories to cover:** {min_stories}–{max_stories} (select the most important and interesting, not just the highest scored)
**Pacing:** {pacing} — keep each story segment to 1–2 minutes maximum

**Structure:**
```
Hook (30 sec) → Story 1 → Transition → Story 2 → ... → Story N → Close (60 sec)
```

---

## LANGUAGE RULES — CRITICAL

This script will be SPOKEN, not read. Apply every rule below without exception.

**1. Short sentences.** Under 20 words per sentence. If someone listening while driving would lose track, rewrite it.

**2. No hollow openers.** Never start with "Welcome back", "Hey guys", "In this video I'll cover", "Today we're looking at". Start in the middle of the first story.

**3. Zero hype words.** These words are banned:
{tone_avoid_lines}
Replace with specific facts. Not "massive scale" — say "40 million trips per day". Not "game-changing" — say what specifically changed and for whom.

**4. Explain every proper noun on first use.** "Codex — OpenAI's coding agent" not just "Codex". "GPT-5.5-Cyber — a restricted version of GPT-5.5 for security teams" not just "GPT-5.5-Cyber". Your audience knows the major names but may not know every product variant.

**5. Active voice.** "OpenAI released Codex enterprise controls" not "enterprise controls were released by OpenAI".

**6. Honest uncertainty.** If a claim comes from only one source (usually the company itself), say "according to OpenAI" or "OpenAI claims". If our data has an evidence gap on a story, say "we don't have independent confirmation of this yet". Do not state company claims as established facts.

**7. Explain WHY it matters.** After every major fact, add one sentence: what does this mean for developers, for users, for the industry? Don't just describe — interpret. The audience can read the press release; they watch this channel for the analysis.

**8. Write for ears, not eyes.** Read every segment out loud before finalizing. If you stumble, rewrite it. Long parenthetical clauses, complex nested sentences, and lists of more than 3 items all sound bad when spoken.

---

## SOURCE CITATIONS — REQUIRED IN EVERY FACTUAL SENTENCE

The host shows source graphics on screen while speaking. You MUST add a citation tag after every sentence that states a specific fact.

**Format:** `[SOURCE: domain/path]`

**Examples:**
```
OpenAI this week published guidelines for deploying Codex in enterprise environments.
[SOURCE: openai.com/index/running-codex-safely]

The sandbox controls what Codex can write to, whether it can access the network, and which paths are protected.
[SOURCE: openai.com/index/running-codex-safely]

GPT-5.5-Cyber is available in limited preview to security teams protecting critical infrastructure.
[SOURCE: openai.com/index/gpt-5-5-with-trusted-access-for-cyber]
```

**Rules:**
- Use the shortest readable form: `openai.com/index/running-codex-safely` not the full https URL
- If several consecutive sentences come from the same source, cite only after the last one in that block
- Facts found via Deep Research browsing: `[SOURCE: browsed — domain.com]`
- Uncertain / unconfirmed claims: `[SOURCE: unverified — skip visual]`
- Company self-reported claims (no independent confirmation): `[SOURCE: openai.com — company claim]`

---

{avoid_block}## YOUR STEP-BY-STEP TASK

**Step 1 — Read all of `02_stories.md` before making any decisions.**
Get a complete picture of what happened this week before selecting stories.

**Step 2 — If in Deep Research mode: visit the source URLs for the top 6–10 stories.**
Read the actual articles. Find the best quote, the most specific number, the sharpest detail. Our automated data is a starting point — you can find better material in the full source pages.

**Step 3 — Select {min_stories}–{max_stories} stories.**
Choose stories that together tell a coherent picture of this week in AI. Prioritize:
- Stories with the highest importance scores AND interesting narrative angles
- Stories that have something concrete: a number, a product you can describe, a real-world example
- Stories with independent confirmation (multiple sources) over company-only announcements
- Stories your audience hasn't heard yet (check the "already covered" list above)

Do NOT include a story just because it has a high score. If it has nothing interesting to say on video, skip it.

**Step 4 — Decide story order.**
Lead with the story most likely to make someone stop scrolling. The first 30 seconds are everything.
Do NOT order by score. Order by what creates the most compelling opening and narrative flow.

**Step 5 — Write the hook first.**
The hook runs for exactly 30 seconds (~75 words). It must:
- Create a reason to keep watching without giving everything away
- Reference something concrete — a specific company, number, or event — not vague promises
- NOT start with "Welcome back" or any variant of it

**Step 6 — Write each story segment.**
Follow this structure for each story:
1. **Context** (1–2 sentences): What is this company / product / research area? Enough so the viewer knows why to care.
2. **What happened** (2–4 sentences): The news itself, stated with specific facts. Cite every fact.
3. **Why it matters** (1–2 sentences): One clear interpretation. What does this mean for developers, for users, for the next 6 months?
4. **What to watch** (optional, 1 sentence): If there's an open question or next step, name it.

**Step 7 — Write transitions.**
Each transition is one sentence that connects the previous story to the next. Do not say "Moving on" or "Next up". Find a thematic link.

**Step 8 — Write the close.**
End with one genuinely useful forward-looking observation — a question this week's news raises, or something specific to watch in the coming weeks. Then a subscribe CTA that sounds natural, not desperate. (~60 seconds total)

---

## OUTPUT FORMAT

Write the complete script using these exact section markers:

```
[HOOK]
...30-second hook. Specific, creates intrigue. Never "Welcome back"...

[STORY: Exact Story Title From 02_stories.md]
...1–2 minute segment...
...Each factual sentence followed by [SOURCE: domain/path]...
[B-ROLL: specific visual suggestion — what should be on screen here]

[TRANSITION]
One sentence connecting this story to the next.

[STORY: Next Story Title]
...

[CLOSE]
...Forward-looking observation. Natural subscribe CTA. ~60 seconds...
```

---

## AFTER THE SCRIPT — MEMORY UPDATE (REQUIRED)

After the script, output this JSON block. I use it to update our content memory so future videos don't repeat what you covered. Fill in every field based on the script you just wrote.

```json
{{
  "memory_update": {{
    "run_id": "{run_id}",
    "stories_covered": ["story_id from 02_stories.md for each story you included"],
    "title_candidate": "Your suggested video title (specific, no hype words)",
    "hook_type": "One short label for the hook type you used, e.g. curiosity_gap / surprising_stat / news_speed / consequence_first",
    "entities_covered": ["Company or model names you mentioned in the script"],
    "topics_covered": ["Topic categories, e.g. AI Safety / AI Coding Tools / Voice AI"],
    "sources_cited": ["All unique source URLs you cited in the script"],
    "open_questions": [
      "A specific question this week raised that we have no answer to yet"
    ],
    "suggested_followup_stories": [
      "A specific story or development worth watching in the next 1-2 weeks"
    ],
    "thumbnail_text_ideas": [
      "3-5 word phrase that could work on a thumbnail"
    ]
  }}
}}
```

---
*AI Signal Brief | {now} | Run: {run_id} | {level_cfg['label']}*
"""


# ─────────────────────────────────────────────────────────────────────────────
# FILE 2 — All Stories with Article Text + Facts
# ─────────────────────────────────────────────────────────────────────────────

def build_stories(run_id: str, level: str, run_dir: Path) -> tuple[str, int, int]:
    """Returns (document_text, n_stories, n_with_facts)"""

    cluster_map = _build_cluster_map(run_dir)
    ranked_map  = _build_ranked_map(run_dir)
    doc_map     = _build_doc_map(run_dir)

    ranked_data = _load_json(run_dir / "layer_3" / "ranked_stories.json")
    all_stories = ranked_data.get("ranked_stories", []) if ranked_data else []

    # Build fact sheet map (story_id → sheet) if L4 ran
    fact_sheet_map = {}
    if level in ("after_layer_4", "after_layer_6"):
        fs_data = _load_json(run_dir / "layer_4" / "story_fact_sheets.json")
        if fs_data:
            for sheet in fs_data.get("story_fact_sheets", []):
                fact_sheet_map[sheet["story_id"]] = sheet

    # Build verified claims map (story_id → [claim]) with source_urls
    claims_by_story: dict[str, list] = {}
    for claim in _load_jsonl(run_dir / "layer_4" / "verified_claims.jsonl"):
        sid = claim.get("story_id", "")
        claims_by_story.setdefault(sid, []).append(claim)

    n_with_facts = len(fact_sheet_map)
    lines = [
        f"# Story Data — {run_id}\n",
        f"*{len(all_stories)} stories total. "
        + (f"{n_with_facts} have verified fact sheets (marked ✓ FACTS). " if n_with_facts else "")
        + "All include the full article text.*\n",
        "---\n",
    ]

    for s in all_stories:
        sid    = s.get("story_id", "")
        title  = s.get("story_title", sid)
        stype  = s.get("story_type", "")
        score  = s.get("total_story_score", 0)
        bucket = s.get("ranking_bucket", "")
        rank   = s.get("rank", "?")

        cluster        = cluster_map.get(sid, {})
        ranked_rec     = ranked_map.get(sid, s)
        entities       = cluster.get("entities", {})
        cos            = entities.get("companies", [])
        mos            = entities.get("models", [])
        prods          = entities.get("products", [])
        topics         = entities.get("topics", [])

        members        = cluster.get("cluster_members", {})
        primary_doc_id = members.get("primary_document_id", "")
        all_doc_ids    = members.get("canonical_document_ids", [primary_doc_id])
        source_mix     = cluster.get("source_mix", {})
        source_str     = cluster.get("source_strength", {})
        story_identity = cluster.get("story_identity", {})
        ranking_reasons = ranked_rec.get("ranking_reasons", [])

        primary_meta   = doc_map.get(primary_doc_id, {})
        url            = primary_meta.get("canonical_url", "")
        published      = primary_meta.get("published_at", "")[:10]

        # Source independence summary
        official_count   = source_mix.get("official_source_count", 0)
        indep_count      = source_mix.get("independent_news_count", 0)
        research_count   = source_mix.get("research_source_count", 0)
        has_indep        = source_str.get("has_independent_confirmation", False)
        multi_tier       = source_str.get("multi_tier_coverage", False)
        indep_flag       = "✓ Multi-source" if has_indep else "⚠ Company-only (no independent confirmation)"

        has_facts  = sid in fact_sheet_map
        fact_badge = " ✓ FACTS" if has_facts else ""

        first_seen = story_identity.get("first_seen_at", "")[:10]
        last_seen  = story_identity.get("last_seen_at", "")[:10]

        lines.append(f"## Story {rank}: {title}{fact_badge}")
        meta = f"**Type:** {stype}  |  **Score:** {score}  |  **Priority:** {bucket}"
        if published:
            meta += f"  |  **Published:** {published}"
        lines.append(meta)
        if url:
            lines.append(f"**Primary source:** {url}")
        src_summary = (
            f"Official: {official_count}  |  Independent news: {indep_count}  |  "
            f"Research: {research_count}  — {indep_flag}"
        )
        lines.append(f"**Source coverage:** {src_summary}")
        if cos:
            lines.append(f"**Companies:** {', '.join(cos)}")
        if mos or prods:
            lines.append(f"**Models/Products:** {', '.join(mos + prods)}")
        if topics:
            lines.append(f"**Topics:** {', '.join(topics)}")
        if first_seen and last_seen and first_seen != last_seen:
            lines.append(f"**Timeline:** First seen {first_seen} → Last seen {last_seen}")
        if ranking_reasons:
            lines.append(f"**Why it ranked:** {', '.join(ranking_reasons)}")
        lines.append("")

        # Article text — show ALL cluster member docs
        for doc_id in all_doc_ids:
            meta  = doc_map.get(doc_id, {})
            text  = _read_article_text(meta, max_words=800)
            title_ = meta.get("title", doc_id)
            src_name = meta.get("source_name", "")
            tier  = meta.get("trust_tier", "")
            d_url = meta.get("canonical_url", "")
            label = f"**Article** ({src_name}, tier {tier})"
            if len(all_doc_ids) > 1:
                label = f"**Article {all_doc_ids.index(doc_id)+1}/{len(all_doc_ids)}: {title_}** ({src_name}, tier {tier})"
            if d_url:
                label += f" — {d_url}"
            lines.append(label)
            if text:
                lines.append(f"> {text.replace(chr(10), chr(10) + '> ')}")
            else:
                lines.append("*(Article text not available — refer to source URL)*")
            lines.append("")

        if has_facts:
            sheet     = fact_sheet_map[sid]
            safe_claims   = sheet.get("safe_facts", [])
            cautious_claims = sheet.get("cautious_facts", [])
            dnu_claims    = sheet.get("do_not_use", [])
            ev_summary    = sheet.get("evidence_summary", {})
            handoff_rec   = sheet.get("handoff_recommendation", {})

            # Evidence quality header
            ev_line = (
                f"{ev_summary.get('verified_claim_count', len(safe_claims))} verified claims  |  "
                f"{ev_summary.get('primary_source_count', official_count)} primary source(s)  |  "
                f"{ev_summary.get('independent_source_count', indep_count)} independent source(s)"
            )
            caution = handoff_rec.get("caution_level", "")
            needs_research = handoff_rec.get("needs_more_research", False)
            ev_line += f"  |  Caution level: {caution}"
            if needs_research:
                ev_line += "  |  **⚠ Needs more research before citing as definitive**"
            lines.append(f"**Evidence quality:** {ev_line}")
            lines.append("")

            if safe_claims:
                lines.append("**Verified facts — safe to state directly (include [SOURCE:] tag shown):**")
                for f in safe_claims:
                    claim_text = f.get("claim_text", "")
                    conf       = f.get("confidence", "")
                    imp        = f.get("importance", "")
                    # Find matching verified claim for source URL
                    matching   = next(
                        (c for c in claims_by_story.get(sid, [])
                         if c.get("claim_id") == f.get("claim_id")), {}
                    )
                    src_urls   = matching.get("source_urls", [])
                    src_tag    = f" [SOURCE: {_url_short(src_urls[0])}]" if src_urls else ""
                    lines.append(f"- [{conf}/{imp}] {claim_text}{src_tag}")
                lines.append("")

            if cautious_claims:
                lines.append("**Claims needing cautious language — use 'reportedly' or 'according to [source]':**")
                for f in cautious_claims:
                    qualifier = f.get("recommended_qualifier", "reportedly")
                    claim_text = f.get("claim_text", "")
                    matching   = next(
                        (c for c in claims_by_story.get(sid, [])
                         if c.get("claim_id") == f.get("claim_id")), {}
                    )
                    src_urls   = matching.get("source_urls", [])
                    src_tag    = f" [SOURCE: {_url_short(src_urls[0])} — company claim]" if src_urls else ""
                    lines.append(f"- {qualifier}: {claim_text}{src_tag}")
                lines.append("")

            if dnu_claims:
                lines.append(f"**Do NOT use ({len(dnu_claims)} claims rejected) — these failed verification:**")
                for f in dnu_claims:
                    lines.append(f"- ✗ {f.get('claim_text', '')}  *(reason: {f.get('rejection_reason', '')})*")
                lines.append("")

            # Evidence gaps from fact sheet (more story-specific than global gaps file)
            sheet_gaps = sheet.get("evidence_gaps", [])
            if sheet_gaps:
                lines.append("**Evidence gaps — flag these as unconfirmed if you mention them:**")
                for gap in sheet_gaps:
                    sev = gap.get("severity", "")
                    desc = gap.get("description", "")
                    lines.append(f"- [{sev}] {desc}")
                lines.append("")

        lines.append("---\n")

    doc = "\n".join(lines)
    return doc, len(all_stories), n_with_facts


# ─────────────────────────────────────────────────────────────────────────────
# FILE 3 — Full Dump
# ─────────────────────────────────────────────────────────────────────────────

def build_dump(run_id: str, run_dir: Path) -> str:
    lines = [
        f"# Full Data Dump — {run_id}\n",
        "*Everything collected. Use this for deep research on any story — full article texts, all extracted claims with source URLs, and cross-run memory.*\n",
        "---\n",
    ]

    doc_map     = _build_doc_map(run_dir)
    cluster_map = _build_cluster_map(run_dir)

    # Build span map for source text excerpts
    spans_by_doc: dict[str, list] = {}
    for span in _load_jsonl(run_dir / "layer_2" / "source_spans.jsonl"):
        doc_id = span.get("canonical_document_id", "")
        spans_by_doc.setdefault(doc_id, []).append(span)

    # Build claims map for dump
    claims_by_story: dict[str, list] = {}
    for claim in _load_jsonl(run_dir / "layer_4" / "verified_claims.jsonl"):
        claims_by_story.setdefault(claim.get("story_id", ""), []).append(claim)

    # ── All documents grouped by story ──────────────────────────────────────
    # Build a doc_id → story_id reverse map
    doc_to_story: dict[str, str] = {}
    for sid, cluster in cluster_map.items():
        for doc_id in cluster.get("cluster_members", {}).get("canonical_document_ids", []):
            doc_to_story[doc_id] = sid

    all_docs = _load_jsonl(run_dir / "layer_2" / "canonical_documents.jsonl")
    # Group by story
    docs_by_story: dict[str, list] = {}
    unclustered = []
    for doc in all_docs:
        doc_id = doc.get("canonical_document_id", "")
        sid    = doc_to_story.get(doc_id)
        if sid:
            docs_by_story.setdefault(sid, []).append(doc)
        else:
            unclustered.append(doc)

    lines.append(f"## Source Documents by Story ({len(all_docs)} total)\n")

    # Emit in cluster order (ranked stories order)
    ranked_data = _load_json(run_dir / "layer_3" / "ranked_stories.json")
    story_order = [s["story_id"] for s in (ranked_data or {}).get("ranked_stories", [])]
    seen_stories = set()

    for sid in story_order:
        cluster = cluster_map.get(sid, {})
        story_title = cluster.get("story_identity", {}).get("canonical_story_title", sid)
        s_docs = docs_by_story.get(sid, [])
        seen_stories.add(sid)
        if not s_docs:
            continue
        source_str = cluster.get("source_strength", {})
        indep_flag = "✓ multi-source" if source_str.get("has_independent_confirmation") else "⚠ company-only"
        lines.append(f"### {story_title}  ({indep_flag}, {len(s_docs)} doc(s))\n")

        for doc in s_docs:
            doc_id   = doc.get("canonical_document_id", "")
            title    = doc.get("title", doc_id)
            url      = doc.get("canonical_url", doc.get("original_url", ""))
            src      = doc.get("source_name", "")
            tier     = doc.get("trust_tier", "")
            pub      = doc.get("published_at", "")[:10]
            words    = doc.get("word_count", "?")

            lines.append(f"#### {title}")
            lines.append(f"**Source:** {src} (tier {tier})  |  **Published:** {pub}  |  **Words:** {words}")
            if url:
                lines.append(f"**URL:** {url}")
            lines.append("")

            text = _read_article_text(doc_map.get(doc_id, {}), max_words=99999)
            if text:
                lines.append(f"> {text.replace(chr(10), chr(10) + '> ')}")
            else:
                lines.append("*(Article text not available)*")
            lines.append("")

            # Source spans — the exact paragraphs extracted for claim analysis
            doc_spans = spans_by_doc.get(doc_id, [])
            if doc_spans:
                lines.append(f"*Extracted spans ({len(doc_spans)} paragraphs used for fact extraction):*")
                for span in doc_spans:
                    span_text = span.get("text", "").strip()
                    if span_text:
                        lines.append(f"> _{span_text}_")
                lines.append("")

    # Remaining docs not linked to any story
    for doc in unclustered:
        doc_id = doc.get("canonical_document_id", "")
        title  = doc.get("title", doc_id)
        url    = doc.get("canonical_url", doc.get("original_url", ""))
        src    = doc.get("source_name", "")
        tier   = doc.get("trust_tier", "")
        lines.append(f"### [Unclustered] {title}")
        lines.append(f"**Source:** {src} (tier {tier})  |  **URL:** {url}")
        text = _read_article_text(doc_map.get(doc_id, {}), max_words=99999)
        if text:
            lines.append(f"> {text.replace(chr(10), chr(10) + '> ')}")
        lines.append("")

    lines.append("---\n")

    # ── All verified claims with source URLs ─────────────────────────────────
    if claims_by_story:
        total_claims = sum(len(v) for v in claims_by_story.values())
        lines.append(f"## All Verified Claims ({total_claims} claims, grouped by story)\n")
        for sid in story_order:
            story_claims = claims_by_story.get(sid, [])
            if not story_claims:
                continue
            cluster = cluster_map.get(sid, {})
            story_title = cluster.get("story_identity", {}).get("canonical_story_title", sid)
            lines.append(f"### {story_title}\n")
            for c in story_claims:
                ctype   = c.get("claim_type", "")
                conf    = c.get("confidence", "")
                imp     = c.get("claim_importance", "")
                text    = c.get("claim_text", "")
                urls    = c.get("source_urls", [])
                usable  = c.get("usable_in_script", True)
                src_tag = f" [SOURCE: {_url_short(urls[0])}]" if urls else ""
                flag    = "" if usable else " ✗BLOCKED"
                lines.append(f"- [{ctype}/{conf}/{imp}]{flag} {text}{src_tag}")
            lines.append("")
        lines.append("---\n")

    # ── Evidence gaps ────────────────────────────────────────────────────────
    gaps_data = _load_json(run_dir / "layer_4" / "evidence_gaps.json")
    if gaps_data:
        gaps = gaps_data.get("evidence_gaps", [])
        lines.append(f"## Evidence Gaps ({len(gaps)} gaps)\n")
        for gap in gaps:
            lines.append(
                f"- [{gap.get('severity','')}] **{gap.get('story_id','')}** — "
                f"{gap.get('gap_type','')} — {gap.get('description','')}"
            )
        lines.append("")
        lines.append("---\n")

    # ── Entity & topic map ───────────────────────────────────────────────────
    if cluster_map:
        lines.append(f"## Entity & Topic Map ({len(cluster_map)} stories)\n")
        for sid in story_order:
            cluster  = cluster_map.get(sid, {})
            entities = cluster.get("entities", {})
            cos   = entities.get("companies", [])
            mos   = entities.get("models", [])
            prods = entities.get("products", [])
            ppl   = entities.get("people", [])
            tops  = entities.get("topics", [])
            title = cluster.get("story_identity", {}).get("canonical_story_title", sid)
            parts = []
            if cos:   parts.append(f"companies: {', '.join(cos)}")
            if mos:   parts.append(f"models: {', '.join(mos)}")
            if prods: parts.append(f"products: {', '.join(prods)}")
            if ppl:   parts.append(f"people: {', '.join(ppl)}")
            if tops:  parts.append(f"topics: {', '.join(tops)}")
            lines.append(f"- **{title}** — {' | '.join(parts)}")
        lines.append("")
        lines.append("---\n")

    # ── Story timeline ───────────────────────────────────────────────────────
    timeline = _load_json(run_dir / "layer_3" / "story_timeline.json")
    if timeline:
        lines.append("## Story Timeline\n")
        lines.append(f"```json\n{json.dumps(timeline, indent=2)[:4000]}\n```\n")
        lines.append("---\n")

    # ── Memory snapshot (cross-run context) ──────────────────────────────────
    snap_path = MEMORY_DIR / "memory_snapshot.json"
    if snap_path.exists():
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        lines.append("## Cross-Run Memory Snapshot\n")
        lines.append(f"```json\n{json.dumps(snap, indent=2)}\n```\n")
        lines.append("---\n")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main export
# ─────────────────────────────────────────────────────────────────────────────

def export(run_id: str, level: str = None) -> dict:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        print(f"[export] Run directory not found: {run_dir}")
        sys.exit(1)

    if not level:
        level = _detect_level(run_dir)
        print(f"[export] Auto-detected level: {level}")

    cfg = yaml.safe_load(PROMPTS_CONFIG.read_text(encoding="utf-8"))

    if level not in cfg["handoff_levels"]:
        available = list(cfg["handoff_levels"].keys())
        print(f"[export] Unknown level '{level}'. Available: {available}")
        sys.exit(1)

    level_cfg = cfg["handoff_levels"][level]

    print(f"[export] Building handoff files...")
    print(f"  Run   : {run_id}")
    print(f"  Level : {level} — {level_cfg['label']}")

    out_dir = HANDOFFS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # File 2 first so we know counts for File 1's header
    print(f"  Building 02_stories.md ...")
    stories_doc, n_stories, n_with_facts = build_stories(run_id, level, run_dir)
    stories_path = out_dir / "02_stories.md"
    stories_path.write_text(stories_doc, encoding="utf-8")

    # File 1 — instructions
    print(f"  Building 01_instructions.md ...")
    instructions_doc = build_instructions(run_id, level, cfg, level_cfg, n_stories, n_with_facts)
    instructions_path = out_dir / "01_instructions.md"
    instructions_path.write_text(instructions_doc, encoding="utf-8")

    # File 3 — full dump
    print(f"  Building 03_dump.md ...")
    dump_doc  = build_dump(run_id, run_dir)
    dump_path = out_dir / "03_dump.md"
    dump_path.write_text(dump_doc, encoding="utf-8")

    def wc(doc): return f"{len(doc.split()):,} words ({len(doc):,} chars)"

    print(f"\n[export] Done — {out_dir}")
    print(f"  01_instructions.md : {wc(instructions_doc)}")
    print(f"  02_stories.md      : {wc(stories_doc)}  ({n_stories} stories, {n_with_facts} with facts)")
    print(f"  03_dump.md         : {wc(dump_doc)}")
    print(f"\nHow to use:")
    print(f"  1. Open 01_instructions.md → paste entire contents into ChatGPT")
    print(f"  2. Paste 02_stories.md in the same or next message")
    print(f"  3. Use 03_dump.md if ChatGPT needs more depth on any story")

    return {
        "instructions": str(instructions_path),
        "stories":      str(stories_path),
        "dump":         str(dump_path),
        "n_stories":    n_stories,
        "n_with_facts": n_with_facts,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate ChatGPT handoff files")
    parser.add_argument("--run-id", dest="run_id")
    parser.add_argument(
        "--level",
        choices=["after_layer_3", "after_layer_4", "after_layer_6"],
        help="Handoff level (auto-detected if omitted)",
    )
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/layer_3/ranked_stories.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            run_id = rp.parents[1].name
            break
        if not run_id:
            print("[export] No run found. Provide --run-id or run the pipeline first.")
            sys.exit(1)
        print(f"[export] Auto-discovered run: {run_id}")

    export(run_id, args.level)


if __name__ == "__main__":
    main()
