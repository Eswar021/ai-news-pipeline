"""
Layer 10 — Module 9: Editorial Pattern Memory Writer

Appends one record per run to memory/editorial_pattern_memory.jsonl.

Captures: format, hook_type, title angles used, blocked angles, thumbnail options,
viewer promise, episode theme — everything Layer 7 decided about framing.

Dedup key: video_id — skips if already recorded.
"""

import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path


def _load_existing_video_ids(path: Path) -> set:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            ids.add(json.loads(line).get("video_id", ""))
    return ids


def write(mc: dict, ctx: dict, eligibility: dict, memory_dir: Path) -> dict:
    if not eligibility["editorial_pattern_allowed"]:
        return {"status": "skipped", "reason": eligibility["status"]}

    path     = memory_dir / "editorial_pattern_memory.jsonl"
    existing = _load_existing_video_ids(path)
    video_id = mc["video_id"]

    if video_id in existing:
        return {"status": "skipped", "reason": "duplicate_video_id", "video_id": video_id}

    ttp = ctx["title_thumbnail_plan"]
    run_id = ctx["run_id"]
    now    = now_project_iso()

    # Approved title angles (safe ones)
    approved_title_angles = [
        {"title": a.get("title", ""), "angle_type": a.get("angle_type", "")}
        for a in ttp.get("recommended_title_angles", [])
        if a.get("accuracy_risk", "") in ("low", "medium")
    ]

    # Thumbnail text options
    thumbnail_texts = [
        t.get("text") or t.get("thumbnail_text") or str(t)
        for t in ttp.get("thumbnail_text_options", [])
    ]

    record = {
        "video_id":        video_id,
        "run_id":          run_id,
        "selected_format": mc["selected_format"],
        "hook": {
            "hook_type":      mc["hook_type"],
            "hook_direction": mc["hook_direction"][:200] if mc["hook_direction"] else "",
        },
        "titles": {
            "working_title":          mc["working_title"],
            "approved_title_angles":  approved_title_angles,
            "blocked_title_angles":   mc["blocked_title_angles"],
        },
        "thumbnail_text_options": thumbnail_texts,
        "editorial": {
            "episode_theme":  mc["episode_theme"],
            "viewer_promise": mc["viewer_promise"][:300] if mc["viewer_promise"] else "",
        },
        "future_guidance": {
            "avoid_same_hook_for_days":         30,
            "avoid_same_title_angle_for_days":  45,
            "allow_follow_up_with_new_evidence": True,
        },
        "created_at": now,
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return {"status": "written", "video_id": video_id}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR, MEMORY_DIR
    from pipelines.layer_10_memory_learning.context_loader import load
    from pipelines.layer_10_memory_learning.eligibility_gate import gate
    from pipelines.layer_10_memory_learning.memory_context_extractor import extract

    run_id = "run_2026_05_10_48h_auto"
    base   = RUNS_DIR / run_id
    ctx    = load(base / "layer_9", base / "layer_8", base / "layer_7",
                  base / "layer_5", base / "layer_4", base / "layer_3")
    elig   = gate(ctx)
    mc     = extract(ctx)
    result = write(mc, ctx, elig, MEMORY_DIR)
    print(f"Status   : {result['status']}")

    records = []
    with open(MEMORY_DIR / "editorial_pattern_memory.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    r = records[-1]
    print(f"\nWritten record:")
    print(f"  format         : {r['selected_format']}")
    print(f"  hook_type      : {r['hook']['hook_type']}")
    print(f"  working_title  : {r['titles']['working_title']}")
    print(f"  title_angles   : {len(r['titles']['approved_title_angles'])}")
    print(f"  blocked_angles : {r['titles']['blocked_title_angles']}")
    print(f"  thumbnails     : {len(r['thumbnail_text_options'])}")
    print(f"  episode_theme  : {r['editorial']['episode_theme'][:80]}")
