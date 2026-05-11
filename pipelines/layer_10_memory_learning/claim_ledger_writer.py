"""
Layer 10 — Module 6: Claim Ledger Writer

Appends one record per used verified claim to memory/claim_ledger.jsonl.

Dedup key: claim_id + video_id — skips if already present.

Records verified claims that appeared in the approved script, preserving
confidence and caution requirements for future reuse.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _load_existing_keys(path: Path) -> set:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            r = json.loads(line)
            keys.add((r["claim_id"], r["video_id"]))
    return keys


def write(mc: dict, ctx: dict, eligibility: dict, memory_dir: Path) -> dict:
    if not eligibility["claim_ledger_allowed"]:
        return {"status": "skipped", "reason": eligibility["status"]}

    path          = memory_dir / "claim_ledger.jsonl"
    existing_keys = _load_existing_keys(path)
    claim_map     = ctx["claim_map"]
    video_id      = mc["video_id"]
    run_id        = ctx["run_id"]
    now           = datetime.now(timezone.utc).isoformat()

    written  = []
    skipped  = []
    missing  = []

    with open(path, "a", encoding="utf-8") as f:
        for claim_id in mc["used_claim_ids"]:
            if (claim_id, video_id) in existing_keys:
                skipped.append(claim_id)
                continue

            claim = claim_map.get(claim_id)
            if not claim:
                missing.append(claim_id)
                continue

            requires_caution = claim.get("requires_cautious_language", False)
            qualifier        = claim.get("recommended_qualifier", "")

            record = {
                "claim_id":   claim_id,
                "run_id":     run_id,
                "video_id":   video_id,
                "story_id":   claim.get("story_id", ""),
                "claim": {
                    "claim_text":    claim.get("claim_text", ""),
                    "claim_type":    claim.get("claim_type", ""),
                    "confidence":    claim.get("confidence", ""),
                    "support_level": claim.get("support_level", ""),
                },
                "source_span_ids":  claim.get("source_span_ids", []),
                "source_urls":      claim.get("source_urls", []),
                "memory_policy": {
                    "eligible_for_future_reuse":  True,
                    "avoid_repeating_verbatim":   True,
                    "must_preserve_caution":      requires_caution,
                    "required_qualifiers":        [qualifier] if requires_caution and qualifier else [],
                },
                "created_at": now,
            }
            f.write(json.dumps(record) + "\n")
            written.append(claim_id)

    return {
        "status":          "written",
        "written":         len(written),
        "skipped":         len(skipped),
        "missing_in_map":  len(missing),
        "missing_ids":     missing,
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
    print(f"Written : {result['written']}  Skipped: {result['skipped']}  Missing: {result['missing_in_map']}")

    # Verify a few records
    records = []
    with open(MEMORY_DIR / "claim_ledger.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"\nTotal records: {len(records)}")
    for r in records[:3]:
        print(f"  {r['claim_id']}: '{r['claim']['claim_text'][:70]}...'")
        print(f"    confidence={r['claim']['confidence']}  caution={r['memory_policy']['must_preserve_caution']}  spans={len(r['source_span_ids'])}")
