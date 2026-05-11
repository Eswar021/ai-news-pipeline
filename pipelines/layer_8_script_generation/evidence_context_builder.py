"""
Layer 8 — Module 2: Evidence Context Builder

Builds per-section evidence bundles from layer8_ctx.
Each bundle contains the claim texts and source URLs the script writer
needs to write that section accurately.

Returns:
    evidence_ctx: {section_id: {required, optional, cautious}} where each
    entry is a list of {claim_id, claim_text, source_url}

Individual test:
    python evidence_context_builder.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_8_script_generation.brief_loader import load as load_brief

_MAX_OPTIONAL = 5


def _bundle(claim_ids: list, claim_text_map: dict, claim_source_map: dict) -> list:
    return [
        {
            "claim_id":   cid,
            "claim_text": claim_text_map.get(cid, ""),
            "source_url": claim_source_map.get(cid, ""),
        }
        for cid in claim_ids
    ]


def build(layer8_ctx: dict) -> dict:
    claim_text_map   = layer8_ctx["claim_text_map"]
    claim_source_map = layer8_ctx["claim_source_map"]

    evidence_ctx = {}
    for sec in layer8_ctx["sections"]:
        sid = sec["section_id"]
        evidence_ctx[sid] = {
            "required": _bundle(sec.get("required_claim_ids", []),
                                claim_text_map, claim_source_map),
            "optional": _bundle(sec.get("optional_claim_ids", [])[:_MAX_OPTIONAL],
                                claim_text_map, claim_source_map),
            "cautious": _bundle(sec.get("cautious_claim_ids", []),
                                claim_text_map, claim_source_map),
        }

    return evidence_ctx


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_7/script_writer_brief.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name

    layer7_dir = RUNS_DIR / run_id / "layer_7"
    layer4_dir = RUNS_DIR / run_id / "layer_4"

    ctx          = load_brief(layer7_dir, layer4_dir)
    evidence_ctx = build(ctx)

    print(f"Sections built    : {len(evidence_ctx)}")
    print()
    for sid, ev in evidence_ctx.items():
        req = ev["required"]
        opt = ev["optional"]
        cau = ev["cautious"]
        print(f"  {sid} | req={len(req)} opt={len(opt)} cautious={len(cau)}")
        for r in req:
            url_preview = r['source_url'][:50] if r['source_url'] else "no-url"
            print(f"    [REQ] {r['claim_id']} | {r['claim_text'][:60]} | {url_preview}")
