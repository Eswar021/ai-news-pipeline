"""
Layer 9 — Module 4: Sentence-to-Claim Coverage Checker

For each sentence that requires claim support, checks:
  - at least one claim_id is present
  - all claim_ids exist in verified claims
  - no claim_id is a rejected/do_not_use claim

Coverage statuses:
  covered        — has valid verified claim_ids
  analysis_only  — no claim_ids but in analysis/takeaway section (warning)
  uncovered      — no claim_ids in a factual section (high severity)
  rejected_claim — uses a rejected claim_id (critical)
  invalid_id     — claim_id not found in verified or rejected maps (medium)

Returns:
    dict with results list and summary stats
"""

_ANALYSIS_SECTIONS = {"final_takeaway", "outro"}


def check(classified_sentences: list, ctx: dict) -> dict:
    claim_map        = ctx["claim_map"]
    rejected_ids     = ctx["rejected_claim_ids"]

    results   = []
    uncovered = []
    rejected  = []
    invalid   = []

    for sent in classified_sentences:
        sid     = sent["sentence_id"]
        section = sent.get("section_key", "")
        text    = sent.get("sentence_text", "")
        cids    = sent.get("claim_ids", [])

        if not sent.get("requires_claim_support"):
            results.append({
                "sentence_id":      sid,
                "section_key":      section,
                "sentence_text":    text,
                "coverage_status":  "no_support_required",
                "claim_ids":        cids,
                "severity":         "info",
                "reason":           sent.get("verified_sentence_type", ""),
            })
            continue

        # Rejected claim check (hard)
        used_rejected = [cid for cid in cids if cid in rejected_ids]
        if used_rejected:
            rec = {
                "sentence_id":      sid,
                "section_key":      section,
                "sentence_text":    text,
                "coverage_status":  "rejected_claim",
                "claim_ids":        cids,
                "rejected_ids":     used_rejected,
                "severity":         "critical",
                "reason":           f"Uses rejected claim(s): {used_rejected}",
            }
            results.append(rec)
            rejected.append(rec)
            continue

        # No claim_ids at all
        if not cids:
            if section in _ANALYSIS_SECTIONS:
                rec = {
                    "sentence_id":      sid,
                    "section_key":      section,
                    "sentence_text":    text,
                    "coverage_status":  "analysis_only",
                    "claim_ids":        [],
                    "severity":         "warning",
                    "reason":           "Analysis/takeaway sentence with no claim mapping.",
                }
            else:
                rec = {
                    "sentence_id":      sid,
                    "section_key":      section,
                    "sentence_text":    text,
                    "coverage_status":  "uncovered",
                    "claim_ids":        [],
                    "severity":         "high",
                    "reason":           "Factual sentence has no claim_ids.",
                }
                uncovered.append(rec)
            results.append(rec)
            continue

        # Check all claim_ids are valid
        bad_ids = [cid for cid in cids if cid not in claim_map and cid not in rejected_ids]
        if bad_ids:
            rec = {
                "sentence_id":      sid,
                "section_key":      section,
                "sentence_text":    text,
                "coverage_status":  "invalid_id",
                "claim_ids":        cids,
                "invalid_ids":      bad_ids,
                "severity":         "medium",
                "reason":           f"Claim ID(s) not found: {bad_ids}",
            }
            results.append(rec)
            invalid.append(rec)
            continue

        # All good
        results.append({
            "sentence_id":      sid,
            "section_key":      section,
            "sentence_text":    text,
            "coverage_status":  "covered",
            "claim_ids":        cids,
            "severity":         "info",
            "reason":           "",
        })

    covered_count  = sum(1 for r in results if r["coverage_status"] == "covered")
    analysis_count = sum(1 for r in results if r["coverage_status"] == "analysis_only")
    no_support_count = sum(1 for r in results if r["coverage_status"] == "no_support_required")

    return {
        "results":          results,
        "total":            len(results),
        "covered":          covered_count,
        "uncovered":        len(uncovered),
        "analysis_only":    analysis_count,
        "no_support_req":   no_support_count,
        "rejected_used":    len(rejected),
        "invalid_ids":      len(invalid),
        "uncovered_list":   uncovered,
        "rejected_list":    rejected,
        "passed":           len(uncovered) == 0 and len(rejected) == 0,
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
    result = check(classified, ctx)

    print(f"Total sentences  : {result['total']}")
    print(f"Covered          : {result['covered']}")
    print(f"Analysis only    : {result['analysis_only']}")
    print(f"No support req   : {result['no_support_req']}")
    print(f"Uncovered        : {result['uncovered']}")
    print(f"Rejected used    : {result['rejected_used']}")
    print(f"Invalid IDs      : {result['invalid_ids']}")
    print(f"Passed           : {result['passed']}")
    if result["uncovered_list"]:
        print("\nUncovered sentences:")
        for r in result["uncovered_list"]:
            print(f"  [{r['section_key']}] {r['sentence_text'][:80]}")
