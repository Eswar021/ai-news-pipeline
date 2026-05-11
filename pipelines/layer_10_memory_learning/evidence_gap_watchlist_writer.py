"""
Layer 10 — Module 11: Evidence Gap + Watchlist Memory Writer

Persists all evidence gaps (regardless of severity) to memory/evidence_gap_watchlist.jsonl.
Future Layer 1 collection can use query_hints to look for missing evidence.

Dedup key: story_id + gap_type + run_id.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


_QUERY_HINTS_BY_TYPE = {
    "missing_independent_confirmation": [
        "independent analysis",
        "third-party review",
        "corroborating report",
    ],
    "missing_quantitative_evidence": [
        "benchmark results",
        "performance numbers",
        "quantitative study",
    ],
    "missing_long_term_impact": [
        "real-world impact study",
        "follow-up research",
        "long-term outcome",
    ],
    "missing_official_statement": [
        "official statement",
        "press release",
        "official announcement",
    ],
    "partial_evidence": [
        "complete source",
        "full report",
        "detailed coverage",
    ],
    "benchmark_without_research": [
        "independent benchmark",
        "peer-reviewed evaluation",
        "external research validation",
    ],
}

_DEFAULT_QUERY_HINTS = ["follow-up coverage", "additional evidence", "corroborating source"]


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


def write(mc: dict, ctx: dict, memory_dir: Path) -> dict:
    # evidence_gap_watchlist_allowed is always True per eligibility gate
    path          = memory_dir / "evidence_gap_watchlist.jsonl"
    existing_keys = _load_existing_keys(path)
    run_id        = ctx["run_id"]
    video_id      = mc["video_id"]
    gaps          = ctx["evidence_gaps"]
    now           = datetime.now(timezone.utc).isoformat()

    written = []
    skipped = []

    with open(path, "a", encoding="utf-8") as f:
        for i, gap in enumerate(gaps):
            story_id = gap.get("story_id", "")
            gap_type = gap.get("gap_type", "")

            key = (story_id, gap_type, run_id)
            if key in existing_keys:
                skipped.append(key)
                continue

            gap_id      = f"gap_{story_id.split('_')[-1]}_{i:02d}_{run_id[-6:]}"
            query_hints = _QUERY_HINTS_BY_TYPE.get(gap_type, _DEFAULT_QUERY_HINTS)

            record = {
                "gap_id":           gap_id,
                "run_id":           run_id,
                "story_id":         story_id,
                "related_video_id": video_id,
                "gap": {
                    "gap_type":    gap_type,
                    "severity":    gap.get("severity", "low"),
                    "description": gap.get("description", ""),
                    "blocks_roundup":   gap.get("blocks_roundup", False),
                    "blocks_deep_dive": gap.get("blocks_deep_dive", False),
                },
                "future_collection_guidance": {
                    "query_hints": query_hints,
                },
                "status":     "open",
                "created_at": now,
            }
            f.write(json.dumps(record) + "\n")
            written.append(gap_id)
            existing_keys.add(key)

    return {
        "status":  "written",
        "written": len(written),
        "skipped": len(skipped),
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
    result = write(mc, ctx, MEMORY_DIR)
    print(f"Status  : {result['status']}")
    print(f"Written : {result['written']}  Skipped: {result['skipped']}")

    records = []
    with open(MEMORY_DIR / "evidence_gap_watchlist.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"\nTotal records: {len(records)}")
    for r in records:
        print(f"  [{r['gap']['severity']:6}] {r['gap']['gap_type']:40}  story={r['story_id'].split('_')[-1]}")
