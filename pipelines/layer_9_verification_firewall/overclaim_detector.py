"""
Layer 9 — Module 7: Overclaim + Unsupported Claim Detector

Pattern-based detector (no LLM) that scans all script sentences for:
  - blocked phrases from Layer 7 brief
  - hardcoded risky patterns (superlatives, false certainty, unsupported predictions)

This is a complement to the LLM-based sentence_support_verifier.
The two modules catch different classes of issues.

Overclaim types:
  blocked_phrase           — exact blocked phrase match
  unsupported_superlative  — "best ever", "biggest of the decade", etc.
  false_certainty          — "proves", "guarantees", "definitely proves"
  unsupported_prediction   — "will replace", "will transform" (unqualified)
  unsupported_ranking      — "number one", "top AI", "#1"

Returns:
    dict with overclaim records and summary
"""

import re

_BLOCKED_HARDCODED = [
    "will replace developers",
    "guaranteed to",
    "proves the end of",
    "destroys",
    "biggest of the decade",
    "best ever",
    "greatest ai",
    "without question",
    "clearly shows",
    "definitively proves",
    "ai has taken over",
    "end of human coding",
    "end of programmers",
]

_SUPERLATIVE_PATTERNS = [
    r"\bbiggest\b.*\bever\b",
    r"\bbest\b.*\bever\b",
    r"\bmost\s+powerful\b.*\bever\b",
    r"\bfirst\s+ever\b",
    r"\bmost\s+important\b.*\bever\b",
    r"\bof\s+the\s+decade\b",
    r"\bof\s+the\s+century\b",
    r"\bmost\s+revolutionary\b",
    r"\bchanges?\s+everything\b",
]

_FALSE_CERTAINTY_PATTERNS = [
    r"\bproves?\s+that\b",
    r"\bguarantees?\s+that\b",
    r"\bwithout\s+question\b",
    r"\bdefinitively\s+shows?\b",
    r"\bclearly\s+shows?\b",
    r"\bundeniably\b",
    r"\bno\s+doubt\b",
]

_PREDICTION_TARGETS = [
    r"\bwill\s+replace\b",
    r"\bwill\s+transform\b",
    r"\bwill\s+eliminate\b",
    r"\bwill\s+disrupt\b",
    r"\bwill\s+end\b",
]
_CAUTIOUS_QUALIFIERS = ("may ", "could ", "might ", "suggest", "appear", "seem")

_RANKING_PATTERNS = [
    r"\bnumber\s+one\b",
    r"\btop\s+ai\b",
    r"\b#1\b",
    r"\bmost\s+advanced\b.*\bever\b",
]


def _match_patterns(text: str, patterns: list) -> list:
    lower = text.lower()
    matches = []
    for p in patterns:
        m = re.search(p, lower)
        if m:
            matches.append(m.group())
    return matches


def _check_sentence(sent: dict, extra_blocked: list) -> list:
    text  = sent.get("sentence_text", "")
    sid   = sent.get("sentence_id", "")
    sk    = sent.get("section_key", "")
    lower = text.lower()

    issues = []

    # Blocked phrases
    all_blocked = _BLOCKED_HARDCODED + extra_blocked
    for phrase in all_blocked:
        if phrase.lower() in lower:
            issues.append({
                "sentence_id":    sid,
                "section_key":    sk,
                "sentence_text":  text,
                "overclaim_type": "blocked_phrase",
                "matched_text":   phrase,
                "severity":       "critical",
                "reason":         f"Blocked phrase detected: '{phrase}'",
            })

    # Superlatives
    for match in _match_patterns(text, _SUPERLATIVE_PATTERNS):
        issues.append({
            "sentence_id":    sid,
            "section_key":    sk,
            "sentence_text":  text,
            "overclaim_type": "unsupported_superlative",
            "matched_text":   match,
            "severity":       "high",
            "reason":         f"Unsupported superlative: '{match}'",
        })

    # False certainty
    for match in _match_patterns(text, _FALSE_CERTAINTY_PATTERNS):
        issues.append({
            "sentence_id":    sid,
            "section_key":    sk,
            "sentence_text":  text,
            "overclaim_type": "false_certainty",
            "matched_text":   match,
            "severity":       "high",
            "reason":         f"False certainty pattern: '{match}'",
        })

    # Unqualified predictions — only flag if no cautious qualifier in sentence
    if not any(q in lower for q in _CAUTIOUS_QUALIFIERS):
        for match in _match_patterns(text, _PREDICTION_TARGETS):
            issues.append({
                "sentence_id":    sid,
                "section_key":    sk,
                "sentence_text":  text,
                "overclaim_type": "unsupported_prediction",
                "matched_text":   match,
                "severity":       "medium",
                "reason":         f"Unqualified future prediction: '{match}'",
            })

    # Rankings
    for match in _match_patterns(text, _RANKING_PATTERNS):
        issues.append({
            "sentence_id":    sid,
            "section_key":    sk,
            "sentence_text":  text,
            "overclaim_type": "unsupported_ranking",
            "matched_text":   match,
            "severity":       "medium",
            "reason":         f"Unsupported ranking: '{match}'",
        })

    return issues


def detect(classified: list, ctx: dict) -> dict:
    # Get extra blocked phrases from Layer 7 brief
    brief = ctx.get("script_writer_brief", {})
    writer_instructions = brief.get("writer_instructions", {})
    extra_blocked = writer_instructions.get("blocked_phrases", [])

    all_issues = []
    for sent in classified:
        issues = _check_sentence(sent, extra_blocked)
        all_issues.extend(issues)

    critical = [i for i in all_issues if i["severity"] == "critical"]
    high     = [i for i in all_issues if i["severity"] == "high"]
    medium   = [i for i in all_issues if i["severity"] == "medium"]

    return {
        "overclaims":        all_issues,
        "overclaim_count":   len(all_issues),
        "critical_count":    len(critical),
        "high_count":        len(high),
        "medium_count":      len(medium),
        "has_critical":      len(critical) > 0,
        "passed":            len(critical) == 0 and len(high) == 0,
        "extra_blocked_used": extra_blocked,
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
    result = detect(classified, ctx)

    print(f"Overclaims found : {result['overclaim_count']}")
    print(f"Critical         : {result['critical_count']}")
    print(f"High             : {result['high_count']}")
    print(f"Medium           : {result['medium_count']}")
    print(f"Passed           : {result['passed']}")
    for oc in result["overclaims"]:
        print(f"  [{oc['overclaim_type']}] [{oc['section_key']}] matched='{oc['matched_text']}'")
        print(f"    {oc['sentence_text'][:80]}")
