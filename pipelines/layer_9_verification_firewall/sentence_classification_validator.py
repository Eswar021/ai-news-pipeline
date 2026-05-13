"""
Layer 9 — Module 3: Sentence Classification Validator

Validates and reclassifies sentence types from Layer 8 for verification purposes.

Layer 8 sentence_mapper used: claim, closing, cta
Layer 9 needs: factual (needs support), transitional/hook/cta (no support needed)

Classification rules:
  - section 'intro_hook': hook → no claim support needed (preview sentences)
  - type 'cta' or section 'cta': no support needed
  - type 'closing': no support needed
  - type 'editorial_analysis': no claim support needed, but validated separately
  - sentences starting with transition phrases: transition → no support needed
  - all other 'claim' sentences: factual → claim support required

Returns:
    list of sentence classification records
"""

import re

_TRANSITION_STARTS = (
    "let's", "next,", "next up", "moving on", "now,", "now let", "up next",
    "stay tuned", "subscribe", "follow", "comment", "share", "like",
    "before we", "in summary", "to wrap", "that covers", "those are",
    "with that", "as we wrap", "as always",
)

_HOOK_SECTIONS = {"intro_hook"}
_CTA_SECTIONS  = {"cta"}


def _is_transition(text: str) -> bool:
    lower = text.lower().strip()
    return any(lower.startswith(p) for p in _TRANSITION_STARTS)


def _classify(sentence_rec: dict) -> dict:
    stype   = sentence_rec.get("sentence_type", "claim")
    section = sentence_rec.get("section_key", "")
    text    = sentence_rec.get("sentence_text", "")
    lower   = text.lower().strip()

    # CTA / closing — never need claim support
    if stype in ("cta", "closing") or section in _CTA_SECTIONS:
        return {
            **sentence_rec,
            "verified_sentence_type": "cta_no_source_needed",
            "requires_claim_support": False,
            "classification_note":    f"original_type={stype}",
        }

    if stype == "editorial_analysis":
        return {
            **sentence_rec,
            "verified_sentence_type": "editorial_analysis",
            "requires_claim_support": False,
            "classification_note":    "layer8_marked_editorial_analysis",
        }

    # Hook (intro_hook section)
    if section in _HOOK_SECTIONS:
        return {
            **sentence_rec,
            "verified_sentence_type": "hook_no_source_needed",
            "requires_claim_support": False,
            "classification_note":    "intro_hook_section",
        }

    # Transition detection
    if _is_transition(text):
        return {
            **sentence_rec,
            "verified_sentence_type": "transition_no_source_needed",
            "requires_claim_support": False,
            "classification_note":    "transition_pattern_detected",
        }

    # Pure question / rhetorical hook
    if lower.endswith("?") and len(text.split()) < 15:
        return {
            **sentence_rec,
            "verified_sentence_type": "rhetorical_hook",
            "requires_claim_support": False,
            "classification_note":    "short_question",
        }

    # Default: factual sentence requiring claim support
    return {
        **sentence_rec,
        "verified_sentence_type": "factual_claim",
        "requires_claim_support": True,
        "classification_note":    f"original_type={stype}",
    }


def classify(ctx: dict) -> list:
    return [_classify(s) for s in ctx["sentence_list"]]


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_9_verification_firewall.context_loader import load

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")

    results = classify(ctx)
    from collections import Counter
    type_counts = Counter(r["verified_sentence_type"] for r in results)
    needs_support = sum(1 for r in results if r["requires_claim_support"])
    print(f"Total sentences      : {len(results)}")
    print(f"Needs claim support  : {needs_support}")
    print(f"Type breakdown       : {dict(type_counts)}")

    print("\nSample factual sentences:")
    for r in results:
        if r["requires_claim_support"]:
            print(f"  [{r['section_key']}] {r['sentence_text'][:80]}")
            print(f"    claim_ids: {r.get('claim_ids', [])}")
