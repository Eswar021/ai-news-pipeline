"""
Layer 9 — Module 1: Verification Context Loader

Loads all inputs from Layers 2, 4, 7, 8 and builds lookup indexes
used by every downstream verification module.

Returns ctx dict with:
  sentence_map        — sent_id → sentence record
  sentence_list       — ordered list of sentence records
  claim_map           — claim_id → verified claim record
  rejected_claim_map  — claim_id → rejected claim record
  span_map            — span_id → source span record
  cautious_claim_ids  — set of claim_ids requiring cautious language
  safe_claim_ids      — set of usable, non-cautious claim_ids
  rejected_claim_ids  — set of rejected claim_ids
  section_plan        — Layer 7 section_plan sections list
  title_thumbnail     — Layer 7 title_thumbnail_plan dict
  generated_script    — Layer 8 generated_script.json dict
  youtube_metadata    — Layer 8 youtube_metadata.json dict
  script_text         — full script plain text
  contradictions      — Layer 4 contradictions dict
  evidence_gaps       — Layer 4 evidence_gaps dict

Usage:
    from pipelines.layer_9_verification_firewall.context_loader import load
    ctx = load(layer8_dir, layer7_dir, layer4_dir, layer2_dir)
"""

import json
from pathlib import Path


def _load_jsonl(path: Path) -> list:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load(layer8_dir: Path, layer7_dir: Path, layer4_dir: Path, layer2_dir: Path) -> dict:
    # ── Layer 8 ──────────────────────────────────────────────────────────────
    sentence_list = _load_jsonl(layer8_dir / "sentence_claim_map.jsonl")
    sentence_source_list = _load_jsonl(layer8_dir / "sentence_source_map.jsonl")
    generated_script = json.loads((layer8_dir / "generated_script.json").read_text())
    youtube_metadata = json.loads((layer8_dir / "youtube_metadata.json").read_text())
    section_scripts = json.loads((layer8_dir / "section_scripts.json").read_text())
    script_text = (layer8_dir / "script.txt").read_text(encoding="utf-8")

    # merge sentence_source_map into sentence records
    source_map_by_id = {r["sentence_id"]: r for r in sentence_source_list}
    for rec in sentence_list:
        sid = rec["sentence_id"]
        srec = source_map_by_id.get(sid, {})
        rec["source_urls"] = srec.get("source_urls", [])

    sentence_map = {r["sentence_id"]: r for r in sentence_list}

    # ── Layer 7 ──────────────────────────────────────────────────────────────
    section_plan = json.loads((layer7_dir / "section_plan.json").read_text())
    title_thumbnail = json.loads((layer7_dir / "title_thumbnail_plan.json").read_text())
    script_writer_brief = json.loads((layer7_dir / "script_writer_brief.json").read_text())

    # ── Layer 4 ──────────────────────────────────────────────────────────────
    verified_claims = _load_jsonl(layer4_dir / "verified_claims.jsonl")
    rejected_claims = _load_jsonl(layer4_dir / "rejected_claims.jsonl")
    contradictions = json.loads((layer4_dir / "contradictions.json").read_text())
    evidence_gaps = json.loads((layer4_dir / "evidence_gaps.json").read_text())

    claim_map = {c["claim_id"]: c for c in verified_claims}
    rejected_claim_map = {c["claim_id"]: c for c in rejected_claims}

    cautious_claim_ids = {
        c["claim_id"] for c in verified_claims if c.get("requires_cautious_language")
    }
    safe_claim_ids = {
        c["claim_id"] for c in verified_claims
        if c.get("usable_in_script") and not c.get("requires_cautious_language")
    }
    rejected_claim_ids = {c["claim_id"] for c in rejected_claims}

    # ── Layer 2 ──────────────────────────────────────────────────────────────
    source_spans = _load_jsonl(layer2_dir / "source_spans.jsonl")
    span_map = {s["span_id"]: s for s in source_spans}

    return {
        "run_id":               script_writer_brief.get("run_id", generated_script.get("run_id", "")),
        "sentence_list":        sentence_list,
        "sentence_map":         sentence_map,
        "claim_map":            claim_map,
        "rejected_claim_map":   rejected_claim_map,
        "span_map":             span_map,
        "cautious_claim_ids":   cautious_claim_ids,
        "safe_claim_ids":       safe_claim_ids,
        "rejected_claim_ids":   rejected_claim_ids,
        "section_plan":         section_plan,
        "title_thumbnail":      title_thumbnail,
        "script_writer_brief":  script_writer_brief,
        "generated_script":     generated_script,
        "youtube_metadata":     youtube_metadata,
        "section_scripts":      section_scripts,
        "script_text":          script_text,
        "contradictions":       contradictions,
        "evidence_gaps":        evidence_gaps,
        "verified_claims":      verified_claims,
        "rejected_claims":      rejected_claims,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")

    print(f"sentences       : {len(ctx['sentence_list'])}")
    print(f"sentence_map    : {len(ctx['sentence_map'])}")
    print(f"verified claims : {len(ctx['claim_map'])}")
    print(f"rejected claims : {len(ctx['rejected_claim_map'])}")
    print(f"source spans    : {len(ctx['span_map'])}")
    print(f"cautious claims : {len(ctx['cautious_claim_ids'])}")
    print(f"safe claims     : {len(ctx['safe_claim_ids'])}")
    print(f"rejected ids    : {len(ctx['rejected_claim_ids'])}")
    print(f"section plan    : {ctx['section_plan']['section_count']} sections")
    print(f"script format   : {ctx['generated_script']['selected_format']}")
    print(f"word count      : {ctx['generated_script']['total_word_count']}")
    print(f"script text len : {len(ctx['script_text'])} chars")
