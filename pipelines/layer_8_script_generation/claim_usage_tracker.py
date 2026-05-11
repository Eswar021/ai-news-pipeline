"""
Layer 8 — Module 6: Claim Usage Tracker

Compares safe_claim_ids from the evidence brief against the claim IDs
that were actually used across all section scripts. Reports usage rate
and identifies unused claims.

Returns:
    {used_claim_ids, unused_claim_ids, usage_rate,
     total_safe, total_used, by_section}

Individual test:
    python claim_usage_tracker.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_8_script_generation.brief_loader             import load as load_brief
from pipelines.layer_8_script_generation.evidence_context_builder import build as build_evidence
from pipelines.layer_8_script_generation.roundup_script_writer    import write as write_roundup


def track(section_scripts: list, layer8_ctx: dict) -> dict:
    safe_ids = set(layer8_ctx["evidence_rules"].get("safe_claim_ids", []))

    all_used  = set()
    by_section = {}
    for sec in section_scripts:
        sid  = sec["section_id"]
        used = set(sec.get("used_claim_ids", []))
        all_used.update(used)
        by_section[sid] = sorted(used)

    used_safe   = sorted(all_used & safe_ids)
    unused_safe = sorted(safe_ids - all_used)
    usage_rate  = round(len(used_safe) / len(safe_ids), 3) if safe_ids else 0.0

    return {
        "total_safe":      len(safe_ids),
        "total_used":      len(used_safe),
        "usage_rate":      usage_rate,
        "used_claim_ids":  used_safe,
        "unused_claim_ids": unused_safe,
        "by_section":      by_section,
    }


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_7/script_writer_brief.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name

    layer7_dir = RUNS_DIR / run_id / "layer_7"
    layer4_dir = RUNS_DIR / run_id / "layer_4"

    ctx             = load_brief(layer7_dir, layer4_dir)
    evidence        = build_evidence(ctx)
    section_scripts = write_roundup(ctx, evidence)
    report          = track(section_scripts, ctx)

    print(f"Total safe claims : {report['total_safe']}")
    print(f"Used in script    : {report['total_used']}")
    print(f"Usage rate        : {report['usage_rate']:.1%}")
    print(f"Unused claims     : {len(report['unused_claim_ids'])}")
    print()
    print("By section:")
    for sid, ids in report["by_section"].items():
        print(f"  {sid}: {len(ids)} claims used → {ids[:3]}")
