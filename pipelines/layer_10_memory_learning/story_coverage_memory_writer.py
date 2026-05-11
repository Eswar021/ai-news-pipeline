"""
Layer 10 — Module 5: Story Coverage Memory Writer

Appends one record per covered story to memory/story_coverage_memory.jsonl.

Dedup key: story_id + video_id — skips if already present.

For roundup format, coverage_type = "roundup_segment".
For deep_dive, coverage_type = "deep_dive".
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


def _coverage_type(selected_format: str) -> str:
    if selected_format == "deep_dive":
        return "deep_dive"
    if selected_format == "roundup":
        return "roundup_segment"
    return selected_format


def write(mc: dict, ctx: dict, eligibility: dict, memory_dir: Path) -> dict:
    if not eligibility["story_coverage_allowed"]:
        return {"status": "skipped", "reason": eligibility["status"]}

    path     = memory_dir / "story_coverage_memory.jsonl"
    existing = _load_existing(path)
    video_id = mc["video_id"]
    existing_keys = {(r["story_id"], r["video_id"]) for r in existing}

    # Entity/topic lookup per story
    etmap = {
        item["story_id"]: item
        for item in ctx["story_entity_topic_map"]
    }

    # Claim-by-section for linking which claims belong to each story
    by_section = ctx["claim_usage_report"].get("by_section", {})

    cov_type  = _coverage_type(mc["selected_format"])
    written   = []
    skipped   = []
    now       = datetime.now(timezone.utc).isoformat()

    with open(path, "a", encoding="utf-8") as f:
        for story_id in mc["story_ids"]:
            if (story_id, video_id) in existing_keys:
                skipped.append(story_id)
                continue

            entry   = etmap.get(story_id, {})
            ents    = entry.get("entities", {})
            topics  = entry.get("topics", [])
            companies = ents.get("companies", []) if isinstance(ents, dict) else []

            # Find claim_ids for this story from by_section (section key has story suffix)
            story_suffix = story_id.split("_")[-1] if "_" in story_id else ""
            story_claims = []
            for sec_key, claim_ids in by_section.items():
                if story_suffix and story_suffix in sec_key:
                    story_claims.extend(claim_ids)

            record = {
                "story_id":     story_id,
                "video_id":     video_id,
                "run_id":       ctx["run_id"],
                "coverage_type": cov_type,
                "coverage_status": "covered_in_prepared_video",
                "story": {
                    "entities":  companies,
                    "topics":    topics,
                    "event_type": entry.get("event_type", ""),
                },
                "claim_ids_used": story_claims,
                "future_handling": {
                    "skip_duplicate_for_days":    30,
                    "allow_follow_up_if_new_evidence": True,
                },
                "created_at": now,
            }
            f.write(json.dumps(record) + "\n")
            written.append(story_id)

    return {
        "status":  "written",
        "written": len(written),
        "skipped": len(skipped),
        "story_ids_written": written,
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

    # Read back and verify a couple records
    records = []
    with open(MEMORY_DIR / "story_coverage_memory.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"\nTotal records in file: {len(records)}")
    for r in records[:3]:
        print(f"  story_id: {r['story_id']}")
        print(f"    coverage_type: {r['coverage_type']}  entities: {r['story']['entities']}  topics: {r['story']['topics']}")
