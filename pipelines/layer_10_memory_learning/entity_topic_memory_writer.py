"""
Layer 10 — Module 7: Entity + Topic Memory Writer

Appends one record per unique entity/topic to memory/entity_topic_memory.jsonl.

Dedup key: entity_or_topic + run_id — skips if already recorded for this run.
(On future runs this accumulates, and index builder counts coverage across runs.)

Each record tracks which video, which stories, and a trend_status derived from
how many videos have covered this entity/topic (computed from existing memory).
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _load_existing(path: Path) -> list:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _classify_type(name: str, entities: list, topics: list) -> str:
    if name in topics:
        return "topic"
    return "entity"


def _derive_trend_status(name: str, existing: list) -> str:
    # Count how many prior records reference this entity/topic
    count = sum(1 for r in existing if r.get("entity_or_topic") == name)
    if count == 0:
        return "first_seen"
    if count == 1:
        return "recurring"
    return "building"


def write(mc: dict, ctx: dict, eligibility: dict, memory_dir: Path) -> dict:
    if not eligibility["entity_topic_memory_allowed"]:
        return {"status": "skipped", "reason": eligibility["status"]}

    path     = memory_dir / "entity_topic_memory.jsonl"
    existing = _load_existing(path)
    run_id   = ctx["run_id"]
    video_id = mc["video_id"]
    now      = datetime.now(timezone.utc).isoformat()

    # Dedup: skip entity/topic already written for this run_id
    already_written = {r["entity_or_topic"] for r in existing if r.get("run_id") == run_id}

    # Story IDs per entity/topic — find which stories mention each
    etmap = {item["story_id"]: item for item in ctx["story_entity_topic_map"]}

    entities = mc["entities"]
    topics   = mc["topics"]
    all_items = [(e, "entity") for e in entities] + [(t, "topic") for t in topics]

    written = []
    skipped = []

    with open(path, "a", encoding="utf-8") as f:
        for name, mem_type in all_items:
            if name in already_written:
                skipped.append(name)
                continue

            # Find story_ids that reference this entity/topic
            story_ids_for_item = []
            for sid in mc["story_ids"]:
                entry = etmap.get(sid, {})
                ents  = entry.get("entities", {})
                flat_entities = []
                if isinstance(ents, dict):
                    for v in ents.values():
                        flat_entities.extend(v)
                ts = entry.get("topics", [])
                if name in flat_entities or name in ts:
                    story_ids_for_item.append(sid)

            trend_status = _derive_trend_status(name, existing)

            record = {
                "entity_or_topic": name,
                "memory_type":     mem_type,
                "run_id":          run_id,
                "coverage_update": {
                    "video_id":        video_id,
                    "story_ids":       story_ids_for_item,
                    "selected_format": mc["selected_format"],
                    "coverage_date":   mc["coverage_date"],
                },
                "trend_status": trend_status,
                "possible_future_formats": ["follow_up", "comparison", "evergreen"],
                "created_at": now,
            }
            f.write(json.dumps(record) + "\n")
            written.append(name)
            already_written.add(name)

    return {
        "status":  "written",
        "written": len(written),
        "skipped": len(skipped),
        "entities_written": [n for n, t in [(w, "") for w in written] if n in entities],
        "topics_written":   [n for n in written if n in topics],
    }


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
    print(f"Status  : {result['status']}")
    print(f"Written : {result['written']}  Skipped: {result['skipped']}")

    records = []
    with open(MEMORY_DIR / "entity_topic_memory.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"\nTotal records: {len(records)}")
    for r in records:
        print(f"  [{r['memory_type']:6}] {r['entity_or_topic']:30}  trend={r['trend_status']}  stories={len(r['coverage_update']['story_ids'])}")
