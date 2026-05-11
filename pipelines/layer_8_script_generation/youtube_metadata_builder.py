"""
Layer 8 — Module 9: YouTube Metadata Builder

Builds YouTube-ready metadata from the assembled script and Layer 8 context:
  - chapters: timestamp list based on cumulative section durations
  - description: top title + viewer promise + chapter timestamps + source credits
  - source_list: unique canonical URLs for claims used in script
  - tags: derived from episode theme + key topics in claim texts

Returns:
    {chapters, description, source_list, tags,
     chapter_count, source_count}

Individual test:
    python youtube_metadata_builder.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_8_script_generation.brief_loader             import load as load_brief
from pipelines.layer_8_script_generation.evidence_context_builder import build as build_evidence
from pipelines.layer_8_script_generation.roundup_script_writer    import write as write_roundup

_CHAPTER_LABEL_MAP = {
    "intro_hook":    "Intro",
    "hook":          "Hook",
    "story_1":       "Story 1",
    "story_2":       "Story 2",
    "story_3":       "Story 3",
    "story_4":       "Story 4",
    "story_5":       "Story 5",
    "story_6":       "Story 6",
    "story_7":       "Story 7",
    "story_8":       "Story 8",
    "final_takeaway": "Takeaway",
    "cta":           "Wrap Up",
}

_AI_TAGS = [
    "AI", "artificial intelligence", "machine learning", "LLM",
    "OpenAI", "Anthropic", "Claude", "ChatGPT", "GPT",
    "AI news", "weekly AI", "AI roundup",
]


def _format_timestamp(total_seconds: int) -> str:
    m = total_seconds // 60
    s = total_seconds % 60
    return f"{m}:{s:02d}"


def _build_chapters(section_scripts: list) -> list:
    chapters  = []
    cumul_sec = 0
    for sec in section_scripts:
        key   = sec["section_key"]
        label = _CHAPTER_LABEL_MAP.get(key, key.replace("_", " ").title())
        chapters.append({
            "section_id":  sec["section_id"],
            "section_key": key,
            "label":       label,
            "start_seconds": cumul_sec,
            "timestamp":   _format_timestamp(cumul_sec),
        })
        cumul_sec += sec["target_seconds"]
    return chapters


def _build_source_list(section_scripts: list, layer8_ctx: dict) -> list:
    claim_source_map = layer8_ctx["claim_source_map"]
    all_used_ids     = set()
    for sec in section_scripts:
        all_used_ids.update(sec.get("used_claim_ids", []))

    seen_urls = set()
    sources   = []
    for cid in sorted(all_used_ids):
        url = claim_source_map.get(cid)
        if url and url not in seen_urls:
            seen_urls.add(url)
            # Extract a readable domain label
            domain = re.sub(r"https?://(www\.)?", "", url).split("/")[0]
            sources.append({"url": url, "domain": domain, "claim_id": cid})

    return sources


def _build_tags(layer8_ctx: dict, section_scripts: list) -> list:
    brief      = layer8_ctx["brief"]
    vi         = brief.get("video_identity", {})
    fmt        = vi.get("selected_format", "roundup")

    tags = list(_AI_TAGS)
    if fmt == "roundup":
        tags += ["AI weekly", "AI updates", "tech news"]
    elif fmt == "deep_dive":
        tags += ["AI deep dive", "AI analysis", "AI breakdown"]

    # Pull keywords from claim texts of used required claims
    claim_text_map = layer8_ctx["claim_text_map"]
    keywords = set()
    for sec in layer8_ctx["sections"]:
        for cid in sec.get("required_claim_ids", []):
            text = claim_text_map.get(cid, "")
            for word in re.findall(r'\b[A-Z][a-zA-Z]{3,}\b', text):
                keywords.add(word)

    tags += sorted(keywords)[:10]
    return list(dict.fromkeys(tags))  # deduplicate preserving order


def _build_description(layer8_ctx: dict, chapters: list, source_list: list) -> str:
    title_rec  = layer8_ctx.get("title_recommendation", {})
    top_title  = title_rec.get("top_title", "AI Weekly Roundup")
    viewer_str = layer8_ctx.get("viewer_strategy", {})
    promise    = viewer_str.get("refined_viewer_promise", "")

    lines = [top_title, "", promise, "", "📌 Chapters:"]
    for ch in chapters:
        lines.append(f"{ch['timestamp']} {ch['label']}")

    lines += ["", "📚 Sources:"]
    for src in source_list[:10]:
        lines.append(f"- {src['url']}")

    lines += [
        "",
        "─────────────────────────────────",
        "AI Signal Brief publishes evidence-first AI news analysis.",
        "No hype. Just verified facts and what they mean for you.",
    ]

    return "\n".join(lines)


def build(section_scripts: list, layer8_ctx: dict) -> dict:
    chapters    = _build_chapters(section_scripts)
    source_list = _build_source_list(section_scripts, layer8_ctx)
    tags        = _build_tags(layer8_ctx, section_scripts)
    description = _build_description(layer8_ctx, chapters, source_list)

    return {
        "chapters":      chapters,
        "chapter_count": len(chapters),
        "description":   description,
        "source_list":   source_list,
        "source_count":  len(source_list),
        "tags":          tags,
    }


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_7/script_writer_brief.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name

    layer7_dir = RUNS_DIR / run_id / "layer_7"
    layer4_dir = RUNS_DIR / run_id / "layer_4"

    ctx             = load_brief(layer7_dir, layer4_dir)
    evidence        = build_evidence(ctx)
    section_scripts = write_roundup(ctx, evidence)
    result          = build(section_scripts, ctx)

    print(f"Chapters     : {result['chapter_count']}")
    print(f"Sources      : {result['source_count']}")
    print(f"Tags         : {len(result['tags'])}")
    print()
    print("Chapters:")
    for ch in result["chapters"]:
        print(f"  {ch['timestamp']:>5s}  {ch['label']}")
    print()
    print("Sources:")
    for src in result["source_list"]:
        print(f"  {src['url']}")
    print()
    print("Description preview:")
    print(result["description"][:500])
