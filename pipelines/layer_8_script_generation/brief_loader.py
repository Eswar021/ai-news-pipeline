"""
Layer 8 — Module 1: Brief Loader

Loads script_writer_brief.json (Layer 7 output) and verified_claims.jsonl
(Layer 4 output) to build the layer8_ctx dict used by all downstream modules.

Returns:
    layer8_ctx dict with:
        run_id, brief, sections, evidence_rules, hook_instruction,
        viewer_strategy, video_identity, claim_text_map, claim_source_map,
        retention_beats, pacing_avoid, title_recommendation, cta_instructions

Individual test:
    python brief_loader.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def load(layer7_dir: Path, layer4_dir: Path) -> dict:
    with open(layer7_dir / "script_writer_brief.json") as f:
        brief = json.load(f)

    claim_text_map   = {}
    claim_source_map = {}
    with open(layer4_dir / "verified_claims.jsonl") as f:
        for line in f:
            c = json.loads(line.strip())
            cid = c["claim_id"]
            claim_text_map[cid] = c.get("claim_text", "")
            urls = c.get("source_urls", [])
            if urls:
                claim_source_map[cid] = urls[0]

    return {
        "run_id":               brief["run_id"],
        "brief_id":             brief["brief_id"],
        "brief":                brief,
        "sections":             brief["sections"],
        "evidence_rules":       brief["evidence_rules"],
        "hook_instruction":     brief["hook_instruction"],
        "viewer_strategy":      brief["viewer_strategy"],
        "video_identity":       brief["video_identity"],
        "retention_beats":      brief.get("retention_beats", []),
        "pacing_avoid":         brief.get("pacing_avoid", []),
        "title_recommendation": brief.get("title_recommendation", {}),
        "cta_instructions":     brief.get("cta_instructions", {}),
        "claim_text_map":       claim_text_map,
        "claim_source_map":     claim_source_map,
    }


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_7/script_writer_brief.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name

    layer7_dir = RUNS_DIR / run_id / "layer_7"
    layer4_dir = RUNS_DIR / run_id / "layer_4"

    ctx = load(layer7_dir, layer4_dir)

    print(f"Run ID            : {ctx['run_id']}")
    print(f"Brief ID          : {ctx['brief_id']}")
    print(f"Format            : {ctx['video_identity']['selected_format']}")
    print(f"Duration          : {ctx['video_identity']['target_duration_seconds']}s "
          f"({ctx['video_identity']['target_duration_minutes']} min)")
    print(f"Sections          : {len(ctx['sections'])}")
    print(f"Claim text map    : {len(ctx['claim_text_map'])} claims")
    print(f"Claim source map  : {len(ctx['claim_source_map'])} claims with URLs")
    print(f"Safe IDs          : {len(ctx['evidence_rules']['safe_claim_ids'])}")
    print(f"DNU IDs           : {len(ctx['evidence_rules']['do_not_use_claim_ids'])}")
    print(f"Blocked phrases   : {len(ctx['evidence_rules']['blocked_phrases'])}")
    print(f"Hook type         : {ctx['hook_instruction']['hook_type']}")
    print(f"Top title         : {ctx['title_recommendation'].get('top_title', '')[:70]}")
    print()
    print("Sections:")
    for s in ctx["sections"]:
        print(f"  {s['section_id']} | {s['section_key']:20s} | {s['target_duration_seconds']:3d}s "
              f"| req={len(s['required_claim_ids'])} opt={len(s['optional_claim_ids'])}")
