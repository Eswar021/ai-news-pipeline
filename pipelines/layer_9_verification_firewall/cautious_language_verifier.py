"""
Layer 9 — Module 8: Cautious Language Verifier

Checks that sentences using cautious claims preserve cautious wording.

A "cautious claim" is one where requires_cautious_language = True in
verified_claims.jsonl. The script must use hedging language (may, could,
suggests, appears to, etc.) whenever it draws from such claims.

Also checks the opposite direction: sentences containing explicit certainty
markers ("will", "definitely", "proves") paired with cautious claim IDs.

Required qualifiers: may, could, suggests, appears, seems, might, possibly,
                     potentially, indicate, likely, based on available
Certainty markers:   will definitely, definitively proves, clearly shows,
                     without question

Returns:
    dict with status, checks list, issues list
"""

_REQUIRED_QUALIFIERS = (
    "may ", "could ", "might ", "suggest", "appear",
    "seem", "possibly", "potentially", "indicat", "likely",
    "based on available", "not yet", "unclear",
)

_CERTAINTY_MARKERS = (
    "will definitely", "definitively proves", "clearly shows",
    "without question", "undeniably", "proven that", "guarantees that",
)


def verify(classified: list, ctx: dict) -> dict:
    cautious_ids = ctx["cautious_claim_ids"]
    claim_map    = ctx["claim_map"]

    issues  = []
    checked = []

    for sent in classified:
        sid   = sent["sentence_id"]
        cids  = sent.get("claim_ids", [])
        text  = sent.get("sentence_text", "")
        lower = text.lower()

        cautious_cids = [cid for cid in cids if cid in cautious_ids]
        if not cautious_cids:
            continue

        # Sentence uses a cautious claim — check for cautious language
        has_qualifier = any(q in lower for q in _REQUIRED_QUALIFIERS)
        has_certainty = any(m in lower for m in _CERTAINTY_MARKERS)

        if has_certainty:
            issue = {
                "sentence_id":        sid,
                "section_key":        sent.get("section_key", ""),
                "sentence_text":      text,
                "cautious_claim_ids": cautious_cids,
                "status":             "failed",
                "severity":           "high",
                "reason":             "Cautious claim used with certainty marker.",
                "recommended_fix":    f"Replace certainty language with qualifiers like 'may' or 'could'.",
            }
            issues.append(issue)
            checked.append({**issue})
        elif not has_qualifier:
            issue = {
                "sentence_id":        sid,
                "section_key":        sent.get("section_key", ""),
                "sentence_text":      text,
                "cautious_claim_ids": cautious_cids,
                "status":             "warning",
                "severity":           "medium",
                "reason":             "Cautious claim has no qualifier word.",
                "recommended_fix":    "Add 'may', 'could', or 'suggests' to soften the claim.",
            }
            issues.append(issue)
            checked.append({**issue})
        else:
            checked.append({
                "sentence_id":        sid,
                "section_key":        sent.get("section_key", ""),
                "sentence_text":      text,
                "cautious_claim_ids": cautious_cids,
                "status":             "passed",
                "severity":           "info",
                "reason":             "Qualifier detected.",
                "recommended_fix":    None,
            })

    hard_failures = [c for c in checked if c["status"] == "failed"]
    warnings      = [c for c in checked if c["status"] == "warning"]

    return {
        "passed":               len(hard_failures) == 0,
        "cautious_claim_count": len(cautious_ids),
        "sentences_checked":    len(checked),
        "failures":             len(hard_failures),
        "warnings":             len(warnings),
        "issues":               issues,
        "checks":               checked,
        "status":               "passed" if len(hard_failures) == 0 else "failed",
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_9_verification_firewall.context_loader import load
    from pipelines.layer_9_verification_firewall.sentence_classification_validator import classify

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")
    classified = classify(ctx)
    result = verify(classified, ctx)

    print(f"Cautious claims  : {result['cautious_claim_count']}")
    print(f"Sentences checked: {result['sentences_checked']}")
    print(f"Failures         : {result['failures']}")
    print(f"Warnings         : {result['warnings']}")
    print(f"Status           : {result['status']}")
    for iss in result["issues"]:
        print(f"  [{iss['severity']}] [{iss['section_key']}] {iss['sentence_text'][:70]}")
