"""
Layer 10 — Module 12: Rejected Claim / Risk Pattern Memory Writer

Stores rejected claims as risk patterns (NOT as facts).

Two sources:
  1. Layer 4 rejected_claims.jsonl — claims that failed verification
  2. Layer 9 overclaim_report.json — patterns detected in the script

Dedup key: claim_id + run_id for Layer 4 claims;
           sentence_id + run_id for Layer 9 overclaims.

Output: memory/rejected_claim_patterns.jsonl
"""

import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path


def _load_existing_keys(path: Path) -> set:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            r = json.loads(line)
            keys.add((r.get("source_id", ""), r.get("run_id", "")))
    return keys


def _load_overclaim_report(layer9_dir: Path) -> list:
    path = layer9_dir / "overclaim_report.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("overclaims", [])


def write(mc: dict, ctx: dict, eligibility: dict, memory_dir: Path) -> dict:
    # risk_pattern_allowed is always True
    path          = memory_dir / "rejected_claim_patterns.jsonl"
    existing_keys = _load_existing_keys(path)
    run_id        = ctx["run_id"]
    now           = now_project_iso()

    written = []

    with open(path, "a", encoding="utf-8") as f:

        # Source 1: Layer 4 rejected claims
        for claim in ctx["rejected_claims"]:
            claim_id = claim.get("claim_id", "")
            key      = (claim_id, run_id)
            if key in existing_keys:
                continue

            record = {
                "risk_pattern_id": f"risk_l4_{claim_id}_{run_id[-6:]}",
                "source_id":       claim_id,
                "run_id":          run_id,
                "source":          "layer4_rejected_claim",
                "story_id":        claim.get("story_id", ""),
                "pattern": {
                    "risk_type":     claim.get("rejection_reason", "rejected"),
                    "blocked_text":  claim.get("claim_text", ""),
                    "reason":        claim.get("rejection_reason", ""),
                    "required_action": claim.get("required_action", "do_not_use"),
                },
                "future_guidance": {
                    "block_in_scripts":    True,
                    "block_in_titles":     False,
                    "block_in_thumbnails": False,
                    "safe_alternative":    "",
                },
                "created_at": now,
            }
            f.write(json.dumps(record) + "\n")
            written.append(claim_id)
            existing_keys.add(key)

        # Source 2: Layer 9 overclaims (if any)
        overclaims = _load_overclaim_report(ctx["layer9_dir"])
        for oc in overclaims:
            oc_id = oc.get("sentence_id") or oc.get("overclaim_id", "")
            key   = (oc_id, run_id)
            if key in existing_keys:
                continue

            record = {
                "risk_pattern_id": f"risk_l9_oc_{oc_id}_{run_id[-6:]}",
                "source_id":       oc_id,
                "run_id":          run_id,
                "source":          "layer9_overclaim",
                "story_id":        "",
                "pattern": {
                    "risk_type":    oc.get("overclaim_type", "overclaim"),
                    "blocked_text": oc.get("matched_text", "") or oc.get("sentence_text", ""),
                    "reason":       oc.get("reason", ""),
                },
                "future_guidance": {
                    "block_in_scripts":    True,
                    "block_in_titles":     oc.get("severity") == "critical",
                    "block_in_thumbnails": oc.get("severity") == "critical",
                    "safe_alternative":    oc.get("suggested_replacement", ""),
                },
                "created_at": now,
            }
            f.write(json.dumps(record) + "\n")
            written.append(oc_id)
            existing_keys.add(key)

    return {
        "status":  "written",
        "written": len(written),
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
    print(f"Written : {result['written']}")

    records = []
    with open(MEMORY_DIR / "rejected_claim_patterns.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"\nTotal records: {len(records)}")
    for r in records:
        print(f"  [{r['source']:25}] {r['pattern']['risk_type']:35}")
        print(f"    text: {r['pattern']['blocked_text'][:70]}")
