"""
Layer 9 — Module 9: Rejected Claim Leakage Detector

Hard firewall check: ensures that rejected/do-not-use claims did not leak
into the final script, title, description, or tags.

Checks:
  1. Sentence claim_ids — any rejected claim_id in a sentence's claim_ids
  2. Script text — key phrases from rejected claim texts appear in script
  3. YouTube title/description — rejected phrases in metadata
  4. Layer 7 blocked phrases — from script_writer_brief.writer_instructions

Severity: critical for any leak found.

Returns:
    dict with status, leaks list, and summary
"""

import re


def _key_phrases(text: str, min_words: int = 3) -> list:
    """Extract overlapping word windows of size min_words from text."""
    words = text.lower().split()
    phrases = []
    for i in range(len(words) - min_words + 1):
        phrase = " ".join(words[i:i + min_words])
        # Skip generic filler phrases
        if not any(stop in phrase for stop in ("we are", "i am", "is a ", "are a ", "in the ", "of the ")):
            phrases.append(phrase)
    return phrases


def detect(coverage_results: dict, support_results: list, ctx: dict) -> dict:
    script_text    = ctx["script_text"].lower()
    rejected_claims = ctx["rejected_claims"]
    rejected_ids    = ctx["rejected_claim_ids"]
    youtube_meta    = ctx["youtube_metadata"]
    brief           = ctx.get("script_writer_brief", {})

    leaks = []

    # ── Check 1: sentence claim_ids ──────────────────────────────────────────
    for r in coverage_results["results"]:
        used_rejected = [cid for cid in r.get("claim_ids", []) if cid in rejected_ids]
        if used_rejected:
            leaks.append({
                "leak_type":       "rejected_claim_id_in_sentence",
                "sentence_id":     r["sentence_id"],
                "section_key":     r.get("section_key", ""),
                "rejected_ids":    used_rejected,
                "matched_text":    r.get("sentence_text", "")[:100],
                "location":        "script_sentence",
                "severity":        "critical",
                "recommended_action": "remove_or_rewrite_sentence",
            })

    # ── Check 2: rejected claim text phrases in script ────────────────────────
    for rc in rejected_claims:
        claim_text = rc.get("claim_text", "")
        phrases = _key_phrases(claim_text, min_words=4)
        for phrase in phrases:
            if phrase in script_text:
                leaks.append({
                    "leak_type":       "rejected_claim_text_in_script",
                    "claim_id":        rc["claim_id"],
                    "matched_text":    phrase,
                    "location":        "script_body",
                    "severity":        "critical",
                    "recommended_action": "rewrite_section_avoiding_rejected_claim",
                })
                break  # one match per claim is enough

    # ── Check 3: blocked phrases in metadata ─────────────────────────────────
    writer_instructions = brief.get("writer_instructions", {})
    blocked_phrases = writer_instructions.get("blocked_phrases", [])

    # Build searchable metadata corpus
    titles = youtube_meta.get("titles", [])
    if isinstance(titles, list):
        title_texts = " ".join(t.get("title", "") if isinstance(t, dict) else str(t) for t in titles)
    else:
        title_texts = str(titles)
    description = youtube_meta.get("description", "") or ""
    tags_list = youtube_meta.get("tags", []) or []
    tags_text = " ".join(tags_list)
    meta_corpus = (title_texts + " " + description + " " + tags_text).lower()

    for phrase in blocked_phrases:
        if phrase.lower() in meta_corpus:
            leaks.append({
                "leak_type":       "blocked_phrase_in_metadata",
                "matched_text":    phrase,
                "location":        "youtube_metadata",
                "severity":        "critical",
                "recommended_action": "remove_phrase_from_metadata",
            })

    # ── Check 4: blocked phrases in script ───────────────────────────────────
    for phrase in blocked_phrases:
        if phrase.lower() in script_text:
            leaks.append({
                "leak_type":       "blocked_phrase_in_script",
                "matched_text":    phrase,
                "location":        "script_body",
                "severity":        "critical",
                "recommended_action": "rewrite_sentence_removing_blocked_phrase",
            })

    passed = len(leaks) == 0

    return {
        "passed":               passed,
        "status":               "passed" if passed else "failed",
        "leaks":                leaks,
        "leak_count":           len(leaks),
        "rejected_claims_checked": len(rejected_claims),
        "blocked_phrases_checked": len(blocked_phrases),
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_9_verification_firewall.context_loader import load
    from pipelines.layer_9_verification_firewall.sentence_classification_validator import classify
    from pipelines.layer_9_verification_firewall.sentence_claim_coverage_checker import check as check_coverage

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")
    classified = classify(ctx)
    coverage = check_coverage(classified, ctx)
    result = detect(coverage, [], ctx)

    print(f"Status           : {result['status']}")
    print(f"Rejected checked : {result['rejected_claims_checked']}")
    print(f"Blocked phrases  : {result['blocked_phrases_checked']}")
    print(f"Leaks found      : {result['leak_count']}")
    for leak in result["leaks"]:
        print(f"  [{leak['severity']}] {leak['leak_type']} — '{leak['matched_text'][:60]}'")
