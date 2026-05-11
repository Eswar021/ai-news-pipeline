"""
Layer 10 — Module 14: Memory Index Builder

Reads all JSONL memory files and builds a searchable index at memory/memory_index.json.

Index structure:
  by_video_id:  { video_id → { story_ids, claim_ids, run_id } }
  by_story_id:  { story_id → { video_ids, followup_ids, gap_ids } }
  by_entity:    { entity → { video_ids, story_ids } }
  by_topic:     { topic → { video_ids, story_ids } }
  by_source:    { domain → { video_ids, claim_ids } }
  run_index:    { run_id → { video_id, story_count, claim_count, created_at } }
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
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
    now = datetime.now(timezone.utc).isoformat()

    video_records        = _load_jsonl(memory_dir / "video_memory.jsonl")
    story_records        = _load_jsonl(memory_dir / "story_coverage_memory.jsonl")
    claim_records        = _load_jsonl(memory_dir / "claim_ledger.jsonl")
    entity_topic_records = _load_jsonl(memory_dir / "entity_topic_memory.jsonl")
    source_records       = _load_jsonl(memory_dir / "source_memory.jsonl")
    followup_records     = _load_jsonl(memory_dir / "followups.jsonl")
    gap_records          = _load_jsonl(memory_dir / "evidence_gap_watchlist.jsonl")

    by_video_id: dict[str, dict] = {}
    by_story_id: dict[str, dict] = defaultdict(lambda: {"video_ids": [], "followup_ids": [], "gap_ids": []})
    by_entity:   dict[str, dict] = defaultdict(lambda: {"video_ids": [], "story_ids": []})
    by_topic:    dict[str, dict] = defaultdict(lambda: {"video_ids": [], "story_ids": []})
    by_source:   dict[str, dict] = defaultdict(lambda: {"video_ids": [], "claim_ids": []})
    run_index:   dict[str, dict] = {}

    # ── Video memory ───────────────────────────────────────────────────────────
    for v in video_records:
        vid = v["video_id"]
        by_video_id[vid] = {
            "run_id":      v.get("run_id", ""),
            "story_ids":   v.get("coverage", {}).get("story_ids", []),
            "claim_ids":   v.get("coverage", {}).get("used_claim_ids", []),
            "created_at":  v.get("timestamps", {}).get("created_at", ""),
        }
        run_index[v.get("run_id", "")] = {
            "video_id":    vid,
            "story_count": len(v.get("coverage", {}).get("story_ids", [])),
            "claim_count": len(v.get("coverage", {}).get("used_claim_ids", [])),
            "format":      v.get("selected_format", ""),
            "created_at":  v.get("timestamps", {}).get("created_at", ""),
        }

    # ── Story coverage ─────────────────────────────────────────────────────────
    for s in story_records:
        sid = s["story_id"]
        vid = s["video_id"]
        entry = by_story_id[sid]
        if vid not in entry["video_ids"]:
            entry["video_ids"].append(vid)

    # ── Claim ledger — only used for totals; no separate index needed ─────────

    # ── Entity/topic ───────────────────────────────────────────────────────────
    for et in entity_topic_records:
        name   = et["entity_or_topic"]
        mtype  = et.get("memory_type", "entity")
        vid    = et.get("coverage_update", {}).get("video_id", "")
        sids   = et.get("coverage_update", {}).get("story_ids", [])

        target = by_entity if mtype == "entity" else by_topic
        entry  = target[name]
        if vid and vid not in entry["video_ids"]:
            entry["video_ids"].append(vid)
        for sid in sids:
            if sid not in entry["story_ids"]:
                entry["story_ids"].append(sid)

    # ── Source memory ──────────────────────────────────────────────────────────
    for s in source_records:
        domain = s.get("domain", "")
        vid    = s.get("video_id", "")
        if domain and vid and vid not in by_source[domain]["video_ids"]:
            by_source[domain]["video_ids"].append(vid)
        for cid in s.get("usage", {}).get("claim_ids", []):
            if cid not in by_source[domain]["claim_ids"]:
                by_source[domain]["claim_ids"].append(cid)

    # ── Follow-ups ────────────────────────────────────────────────────────────
    for fu in followup_records:
        sid = fu.get("story_id", "")
        fid = fu.get("followup_id", "")
        if sid and fid and fid not in by_story_id[sid]["followup_ids"]:
            by_story_id[sid]["followup_ids"].append(fid)

    # ── Evidence gaps ─────────────────────────────────────────────────────────
    for g in gap_records:
        sid = g.get("story_id", "")
        gid = g.get("gap_id", "")
        if sid and gid and gid not in by_story_id[sid]["gap_ids"]:
            by_story_id[sid]["gap_ids"].append(gid)

    index = {
        "created_at":  now,
        "by_video_id": by_video_id,
        "by_story_id": dict(by_story_id),
        "by_entity":   dict(by_entity),
        "by_topic":    dict(by_topic),
        "by_source":   dict(by_source),
        "run_index":   run_index,
        "stats": {
            "total_videos":   len(by_video_id),
            "total_stories":  len(by_story_id),
            "total_entities": len(by_entity),
            "total_topics":   len(by_topic),
            "total_sources":  len(by_source),
            "total_runs":     len(run_index),
        },
    }

    out_path = memory_dir / "memory_index.json"
    out_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return {"status": "built", "path": str(out_path), "stats": index["stats"]}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import MEMORY_DIR

    result = build(MEMORY_DIR)
    print(f"Status : {result['status']}")
    print(f"Path   : {result['path']}")
    print(f"\nIndex stats:")
    for k, v in result["stats"].items():
        print(f"  {k:20}: {v}")

    # Spot-check
    idx = json.loads((MEMORY_DIR / "memory_index.json").read_text())
    print(f"\nby_entity keys: {list(idx['by_entity'].keys())}")
    print(f"by_topic  keys: {list(idx['by_topic'].keys())}")
    print(f"by_source keys: {list(idx['by_source'].keys())[:5]}")
    print(f"run_index keys: {list(idx['run_index'].keys())}")
