"""
Layer 10 — Module 10: Follow-up Opportunity Tracker

Creates follow-up records from evidence gaps in Layer 4.

A follow-up is created when:
  - gap severity is 'medium' or 'high'
  - gap story_id is in the selected story_ids for this run

Dedup key: story_id + gap_type + run_id — skips if already present.

Output: memory/followups.jsonl
"""

import json
from datetime import datetime, timezone
from pathlib import Path


_PRIORITY_MAP = {
    "high":   "high",
    "medium": "medium",
    "low":    "low",
}

_WATCH_FOR_BY_GAP_TYPE = {
    "missing_independent_confirmation": [
        "independent news confirmation",
        "third-party analysis",
        "official follow-up announcement",
    ],
    "missing_quantitative_evidence": [
        "benchmark results",
        "quantitative user data",
        "independent performance measurement",
    ],
    "missing_long_term_impact": [
        "follow-up study",
        "real-world adoption evidence",
        "long-term outcome report",
    ],
    "missing_official_statement": [
        "official statement or press release",
        "confirmed announcement",
    ],
    "partial_evidence": [
        "fuller source with more detail",
        "corroborating evidence from second source",
    ],
}

_DEFAULT_WATCH_FOR = ["follow-up announcement", "independent confirmation", "new evidence"]


def _load_existing_keys(path: Path) -> set:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            r = json.loads(line)
            keys.add((r.get("story_id", ""), r.get("gap_type", ""), r.get("run_id", "")))
    return keys


def write(mc: dict, ctx: dict, eligibility: dict, memory_dir: Path) -> dict:
    if not eligibility["followup_allowed"]:
        return {"status": "skipped", "reason": eligibility["status"]}

    path          = memory_dir / "followups.jsonl"
    existing_keys = _load_existing_keys(path)
    run_id        = ctx["run_id"]
    video_id      = mc["video_id"]
    story_ids_set = set(mc["story_ids"])
    gaps          = ctx["evidence_gaps"]
    now           = datetime.now(timezone.utc).isoformat()

    written = []
    skipped = []

    with open(path, "a", encoding="utf-8") as f:
        for gap in gaps:
            story_id  = gap.get("story_id", "")
            gap_type  = gap.get("gap_type", "")
            severity  = gap.get("severity", "low")

            # Only create follow-ups for selected stories with medium+ gaps
            if story_id not in story_ids_set or severity == "low":
                skipped.append(f"{story_id}:{gap_type}")
                continue

            key = (story_id, gap_type, run_id)
            if key in existing_keys:
                skipped.append(f"{story_id}:{gap_type}")
                continue

            followup_id = f"followup_{story_id.split('_')[-1]}_{gap_type[:20]}_{run_id[-6:]}"
            watch_for   = _WATCH_FOR_BY_GAP_TYPE.get(gap_type, _DEFAULT_WATCH_FOR)
            priority    = _PRIORITY_MAP.get(severity, "medium")

            record = {
                "followup_id":       followup_id,
                "run_id":            run_id,
                "story_id":          story_id,
                "related_video_id":  video_id,
                "gap_type":          gap_type,
                "followup_reason":   gap.get("description", gap_type),
                "followup_type":     "evidence_gap_monitoring",
                "watch_for":         watch_for,
                "possible_future_angle": f"Follow-up: {gap.get('description', gap_type)}",
                "priority":          priority,
                "status":            "open",
                "created_at":        now,
            }
            f.write(json.dumps(record) + "\n")
            written.append(followup_id)
            existing_keys.add(key)

    return {
        "status":   "written",
        "written":  len(written),
        "skipped":  len(skipped),
        "followup_ids": written,
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
    with open(MEMORY_DIR / "followups.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"\nTotal followup records: {len(records)}")
    for r in records:
        print(f"  [{r['priority']:6}] {r['story_id'].split('_')[-1]:10}  gap={r['gap_type']}")
        print(f"    reason: {r['followup_reason'][:80]}")
