"""
Layer 8 — Module 5: Sentence Mapper

Splits each section's script_text into sentences, classifies each sentence,
and maps evidence sentences to claim_ids and source_urls.

Sentence types:
    hook        — question or exclamation near section start
    transition  — starts with a transition phrase
    cta         — contains subscribe/comment/like/let me know
    claim       — evidence-bearing statement (default for content sections)
    closing     — final sentence of takeaway or cta sections

Claim mapping strategy:
    Evidence sentences in a section are mapped to that section's used_claim_ids.
    This is section-level (not sentence-level) — accurate enough for Layer 9.

Returns:
    {
        "sentence_claim_map": list of {sentence_id, section_id, sentence_type,
                                       sentence_text, claim_ids}
        "sentence_source_map": list of {sentence_id, section_id, sentence_type,
                                        sentence_text, source_urls}
    }

Individual test:
    python sentence_mapper.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_8_script_generation.brief_loader             import load as load_brief
from pipelines.layer_8_script_generation.evidence_context_builder import build as build_evidence
from pipelines.layer_8_script_generation.roundup_script_writer    import write as write_roundup

_TRANSITION_STARTERS = {
    "but", "however", "next", "now", "meanwhile", "additionally",
    "also", "moving on", "switching to", "on that note", "that said",
    "with that", "let's", "so", "and that", "turning to",
}

_CTA_SIGNALS = {
    "comment", "subscribe", "like", "let me know", "tell me",
    "drop", "below", "notification", "bell", "hit that",
}


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in raw if s.strip()]


def _classify(sentence: str, section_role: str, idx: int, total: int) -> str:
    lower = sentence.lower()

    if any(sig in lower for sig in _CTA_SIGNALS):
        return "cta"

    if section_role in ("cta",):
        return "cta"

    if section_role in ("final_takeaway", "takeaway") and idx == total - 1:
        return "closing"

    if sentence.endswith("?") or (idx == 0 and section_role in ("intro_hook", "hook")):
        return "hook"

    first_word = lower.split()[0] if lower.split() else ""
    first_two  = " ".join(lower.split()[:2]) if len(lower.split()) >= 2 else first_word
    if first_word in _TRANSITION_STARTERS or first_two in _TRANSITION_STARTERS:
        return "transition"

    return "claim"


def build(section_scripts: list, layer8_ctx: dict) -> dict:
    claim_source_map = layer8_ctx["claim_source_map"]

    sentence_claim_map  = []
    sentence_source_map = []
    sent_counter        = 0

    for sec_script in section_scripts:
        sid      = sec_script["section_id"]
        role     = sec_script.get("segment_role", sec_script["section_key"])
        used_ids = sec_script.get("used_claim_ids", [])
        source_urls = list({
            claim_source_map[cid] for cid in used_ids
            if cid in claim_source_map and claim_source_map[cid]
        })

        sentences = _split_sentences(sec_script.get("script_text", ""))
        total     = len(sentences)

        for i, sent in enumerate(sentences):
            sent_id   = f"sent_{sent_counter:04d}"
            sent_type = _classify(sent, role, i, total)

            # Only evidence sentences get claim/source mapping
            mapped_ids  = used_ids  if sent_type == "claim" else []
            mapped_urls = source_urls if sent_type == "claim" else []

            sentence_claim_map.append({
                "sentence_id":   sent_id,
                "section_id":    sid,
                "section_key":   sec_script["section_key"],
                "sentence_type": sent_type,
                "sentence_text": sent,
                "claim_ids":     mapped_ids,
            })
            sentence_source_map.append({
                "sentence_id":   sent_id,
                "section_id":    sid,
                "section_key":   sec_script["section_key"],
                "sentence_type": sent_type,
                "sentence_text": sent,
                "source_urls":   mapped_urls,
            })
            sent_counter += 1

    return {
        "sentence_claim_map":  sentence_claim_map,
        "sentence_source_map": sentence_source_map,
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
    result          = build(section_scripts, ctx)

    scm = result["sentence_claim_map"]
    ssm = result["sentence_source_map"]
    print(f"Total sentences   : {len(scm)}")

    by_type = {}
    for s in scm:
        by_type.setdefault(s["sentence_type"], 0)
        by_type[s["sentence_type"]] += 1
    print("By type:")
    for t, n in sorted(by_type.items()):
        print(f"  {t:15s}: {n}")

    print()
    print("Sample claim sentences:")
    for s in scm:
        if s["sentence_type"] == "claim" and s["claim_ids"]:
            print(f"  [{s['sentence_id']}] ({s['section_key']}) {s['sentence_text'][:80]}")
            print(f"    claims: {s['claim_ids'][:2]}")
            break

    print()
    print("Sample source mapping:")
    for s in ssm:
        if s["sentence_type"] == "claim" and s["source_urls"]:
            print(f"  [{s['sentence_id']}] ({s['section_key']}) {s['sentence_text'][:70]}")
            print(f"    urls: {s['source_urls'][:1]}")
            break
