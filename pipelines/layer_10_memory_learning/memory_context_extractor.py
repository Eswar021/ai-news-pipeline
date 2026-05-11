"""
Layer 10 — Module 3: Memory Context Extractor

Extracts normalized memory-worthy information from the loaded context.

Returns a memory_context dict:
  video_id, selected_format, story_ids
  working_title, approved_titles, thumbnail_options
  entities (flat deduped list), topics (flat deduped list)
  used_claim_ids, sources (list of {url, domain, claim_id})
  hook_type, hook_direction, blocked_title_angles
  episode_theme, viewer_promise
"""

from datetime import date


def extract(ctx: dict) -> dict:
    run_id = ctx["run_id"]
    svb    = ctx["selected_video_brief"]
    vp     = ctx["video_plan"]
    ttp    = ctx["title_thumbnail_plan"]
    swb    = ctx["script_writer_brief"]
    vym    = ctx["verified_youtube_metadata"]
    cur    = ctx["claim_usage_report"]

    # ── Video identity ─────────────────────────────────────────────────────────
    video_id        = f"video_candidate_{run_id}"
    selected_format = svb.get("selected_format", "roundup")
    story_ids       = svb.get("selected_story_ids", [])
    selected_video_id = vp.get("selected_video_id", video_id)

    # ── Title + thumbnail ──────────────────────────────────────────────────────
    working_title    = vym.get("recommended_title", "")
    approved_titles  = vym.get("approved_titles", [])
    thumbnail_options = vym.get("approved_thumbnails", [])

    # Blocked angles from title_thumbnail_plan
    blocked_title_angles = [
        a.get("angle") or a.get("title", "")
        for a in ttp.get("blocked_title_angles", [])
    ]

    # ── Hook + editorial direction ─────────────────────────────────────────────
    hook_instruction = swb.get("hook_instruction", {})
    hook_type        = hook_instruction.get("hook_type", "unknown")
    hook_direction   = hook_instruction.get("direction", "")
    viewer_strategy  = swb.get("viewer_strategy", {})
    viewer_promise   = viewer_strategy.get("viewer_promise", "") if isinstance(viewer_strategy, dict) else ""

    content_dir   = svb.get("content_direction", {})
    episode_theme = content_dir.get("episode_theme", "")

    # ── Entities + topics (flattened across all selected stories) ─────────────
    etmap = {
        item["story_id"]: item
        for item in ctx["story_entity_topic_map"]
    }

    companies_set, models_set, products_set, topics_set = set(), set(), set(), set()

    for sid in story_ids:
        entry = etmap.get(sid)
        if not entry:
            continue
        ents = entry.get("entities", {})
        if isinstance(ents, dict):
            companies_set.update(e for e in ents.get("companies", []) if e)
            models_set.update(e for e in ents.get("models", []) if e)
            products_set.update(e for e in ents.get("products", []) if e)
        for t in entry.get("topics", []):
            if t:
                topics_set.add(t)

    # Entities = companies + models + products (distinct sets, ordered)
    entities = sorted(companies_set) + sorted(m for m in models_set if m not in companies_set) + \
               sorted(p for p in products_set if p not in companies_set and p not in models_set)
    topics   = sorted(topics_set)

    # ── Claims + sources ───────────────────────────────────────────────────────
    used_claim_ids = cur.get("used_claim_ids", [])
    sources        = vym.get("source_list", [])

    return {
        "video_id":             video_id,
        "selected_video_id":    selected_video_id,
        "selected_format":      selected_format,
        "story_ids":            story_ids,
        "working_title":        working_title,
        "approved_titles":      approved_titles,
        "thumbnail_options":    thumbnail_options,
        "blocked_title_angles": blocked_title_angles,
        "hook_type":            hook_type,
        "hook_direction":       hook_direction,
        "episode_theme":        episode_theme,
        "viewer_promise":       viewer_promise,
        "entities":             entities,
        "topics":               topics,
        "used_claim_ids":       used_claim_ids,
        "sources":              sources,
        "coverage_date":        str(date.today()),
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_10_memory_learning.context_loader import load

    run_id = "run_2026_05_10_48h_auto"
    base   = RUNS_DIR / run_id
    ctx    = load(base / "layer_9", base / "layer_8", base / "layer_7",
                  base / "layer_5", base / "layer_4", base / "layer_3")

    from pipelines.layer_10_memory_learning.memory_context_extractor import extract
    mc = extract(ctx)
    print(f"video_id        : {mc['video_id']}")
    print(f"format          : {mc['selected_format']}")
    print(f"story_ids       : {len(mc['story_ids'])} stories")
    print(f"working_title   : {mc['working_title']}")
    print(f"hook_type       : {mc['hook_type']}")
    print(f"entities        : {mc['entities']}")
    print(f"topics          : {mc['topics']}")
    print(f"used_claim_ids  : {len(mc['used_claim_ids'])}")
    print(f"sources         : {len(mc['sources'])}")
    print(f"blocked angles  : {mc['blocked_title_angles']}")
