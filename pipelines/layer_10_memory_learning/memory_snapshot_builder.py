"""
Layer 10 — Module 15: Memory Snapshot Builder

Builds a compact memory_snapshot.json from current memory state.
This snapshot is consumed by future Layer 5 and Layer 7 runs to:
  - avoid repeating topics/angles
  - check story novelty
  - find open follow-ups
  - prioritize high-value sources

Output: memory/memory_snapshot.json (overwritten on each run)
"""

import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _load_jsonl(path: Path) -> list:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def build(memory_dir: Path) -> dict:
    now = datetime.now(timezone.utc)

    video_records        = _load_jsonl(memory_dir / "video_memory.jsonl")
    story_records        = _load_jsonl(memory_dir / "story_coverage_memory.jsonl")
    editorial_records    = _load_jsonl(memory_dir / "editorial_pattern_memory.jsonl")
    entity_topic_records = _load_jsonl(memory_dir / "entity_topic_memory.jsonl")
    source_records       = _load_jsonl(memory_dir / "source_memory.jsonl")
    followup_records     = _load_jsonl(memory_dir / "followups.jsonl")

    # ── Recent coverage (last 30 days) ────────────────────────────────────────
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    recent_videos = [
        v for v in video_records
        if v.get("timestamps", {}).get("created_at", "") >= cutoff_30d
    ]

    top_entities = Counter(
        e for v in recent_videos
        for e in v.get("coverage", {}).get("entities", [])
    ).most_common(5)

    top_topics = Counter(
        t for v in recent_videos
        for t in v.get("coverage", {}).get("topics", [])
    ).most_common(5)

    # ── Avoid repetition ──────────────────────────────────────────────────────
    recent_title_angles = [
        ep.get("titles", {}).get("working_title", "")
        for ep in editorial_records
        if ep.get("created_at", "") >= cutoff_30d
    ]
    recent_hook_types = list({
        ep.get("hook", {}).get("hook_type", "")
        for ep in editorial_records
        if ep.get("created_at", "") >= cutoff_30d
    })
    blocked_title_angles = list({
        angle
        for ep in editorial_records
        for angle in ep.get("titles", {}).get("blocked_title_angles", [])
    })

    avoid_angle_topics = []
    for et in entity_topic_records:
        if et.get("memory_type") == "topic":
            avoid_until = (now + timedelta(days=30)).strftime("%Y-%m-%d")
            avoid_angle_topics.append({
                "topic":       et["entity_or_topic"],
                "avoid_until": avoid_until,
                "unless":      "new major evidence or follow-up story",
            })

    # ── Open follow-ups ───────────────────────────────────────────────────────
    open_followups = [
        {
            "followup_id": fu.get("followup_id", ""),
            "story_id":    fu.get("story_id", ""),
            "gap_type":    fu.get("gap_type", ""),
            "priority":    fu.get("priority", "medium"),
            "watch_for":   fu.get("watch_for", [])[:3],
        }
        for fu in followup_records
        if fu.get("status") == "open"
    ]

    # ── Source guidance ───────────────────────────────────────────────────────
    tier1 = sorted({r["domain"] for r in source_records if r.get("trust_tier") == 1})
    tier2 = sorted({r["domain"] for r in source_records if r.get("trust_tier") == 2})
    tier3 = sorted({r["domain"] for r in source_records if r.get("trust_tier") == 3})

    # ── Covered story IDs ─────────────────────────────────────────────────────
    covered_story_ids = list({r["story_id"] for r in story_records})

    snapshot = {
        "snapshot_created_at": now.isoformat(),
        "stats": {
            "total_videos_in_memory": len(video_records),
            "total_stories_covered":  len(story_records),
            "open_followups":         len(open_followups),
        },
        "recent_coverage": {
            "last_30_days": {
                "videos_prepared": len(recent_videos),
                "top_entities":    [e for e, _ in top_entities],
                "top_topics":      [t for t, _ in top_topics],
            }
        },
        "covered_story_ids": covered_story_ids,
        "avoid_repetition": {
            "recent_title_angles":    recent_title_angles,
            "recent_hook_types":      recent_hook_types,
            "blocked_title_angles":   blocked_title_angles,
            "avoid_same_angle_topics": avoid_angle_topics,
        },
        "open_followups": open_followups,
        "source_guidance": {
            "high_priority_sources":  tier1,
            "medium_priority_sources": tier2,
            "trend_signal_sources":   tier3,
        },
        "layer_guidance": {
            "for_layer5": {
                "check_novelty_against":    "story_coverage_memory.jsonl",
                "use_followups_from":       "followups.jsonl",
                "avoid_recent_angles":      True,
                "covered_story_ids_path":   "memory/memory_index.json",
            },
            "for_layer7": {
                "avoid_recent_hook_types":      recent_hook_types,
                "avoid_recent_title_angles":    recent_title_angles,
                "check_blocked_title_angles":   blocked_title_angles,
            },
        },
    }

    out_path = memory_dir / "memory_snapshot.json"
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return {"status": "built", "path": str(out_path)}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import MEMORY_DIR

    result = build(MEMORY_DIR)
    print(f"Status : {result['status']}")

    snap = json.loads((MEMORY_DIR / "memory_snapshot.json").read_text())
    print(f"\nSnapshot created: {snap['snapshot_created_at']}")
    print(f"Stats: {snap['stats']}")
    print(f"\nTop entities: {snap['recent_coverage']['last_30_days']['top_entities']}")
    print(f"Top topics  : {snap['recent_coverage']['last_30_days']['top_topics']}")
    print(f"\nRecent title angles: {snap['avoid_repetition']['recent_title_angles']}")
    print(f"Recent hook types  : {snap['avoid_repetition']['recent_hook_types']}")
    print(f"Blocked angles     : {snap['avoid_repetition']['blocked_title_angles']}")
    print(f"\nOpen follow-ups    : {len(snap['open_followups'])}")
    print(f"Tier-1 sources     : {snap['source_guidance']['high_priority_sources']}")
    print(f"Covered stories    : {len(snap['covered_story_ids'])}")
