"""
Layer 8 — Module 7: Cautious Language Checker

Scans the assembled script for two things:
  1. Blocked phrases — hard violations that must never appear in the script
  2. Cautious claim language — cautious_claim_ids should use qualifying language
     (may, could, suggests, appears to, seems)

Returns:
    {passed, violations, warnings}

Individual test:
    python cautious_language_checker.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.layer_8_script_generation.brief_loader             import load as load_brief
from pipelines.layer_8_script_generation.evidence_context_builder import build as build_evidence
from pipelines.layer_8_script_generation.roundup_script_writer    import write as write_roundup

_QUALIFIERS = {"may", "could", "suggests", "appears to", "seems", "might",
               "possibly", "potentially", "indicate", "likely"}


def _context(text: str, phrase: str, window: int = 60) -> str:
    idx = text.lower().find(phrase.lower())
    if idx == -1:
        return ""
    start = max(0, idx - window)
    end   = min(len(text), idx + len(phrase) + window)
    return "..." + text[start:end] + "..."


def check(section_scripts: list, layer8_ctx: dict) -> dict:
    full_text        = " ".join(s.get("script_text", "") for s in section_scripts)
    blocked_phrases  = layer8_ctx["evidence_rules"].get("blocked_phrases", [])
    cautious_ids     = set(layer8_ctx["evidence_rules"].get("cautious_claim_ids", []))
    claim_text_map   = layer8_ctx["claim_text_map"]

    violations = []
    warnings   = []

    # Check 1: blocked phrases
    lower_full = full_text.lower()
    for phrase in blocked_phrases:
        if phrase.lower() in lower_full:
            violations.append({
                "type":    "blocked_phrase",
                "phrase":  phrase,
                "context": _context(full_text, phrase),
            })

    # Check 2: cautious claims — verify qualifying language near claim text
    for sec_script in section_scripts:
        sid       = sec_script["section_id"]
        used_ids  = set(sec_script.get("used_claim_ids", []))
        used_caut = used_ids & cautious_ids
        if not used_caut:
            continue

        script_lower = sec_script.get("script_text", "").lower()
        for cid in used_caut:
            has_qualifier = any(q in script_lower for q in _QUALIFIERS)
            if not has_qualifier:
                claim_preview = claim_text_map.get(cid, "")[:60]
                warnings.append({
                    "type":          "missing_qualifier",
                    "claim_id":      cid,
                    "section_id":    sid,
                    "claim_preview": claim_preview,
                    "note":          "Cautious claim used without qualifying language.",
                })

    passed = len(violations) == 0

    return {
        "passed":     passed,
        "violations": violations,
        "warnings":   warnings,
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
    result          = check(section_scripts, ctx)

    print(f"Passed    : {result['passed']}")
    print(f"Violations: {len(result['violations'])}")
    print(f"Warnings  : {len(result['warnings'])}")
    for v in result["violations"]:
        print(f"  [VIOLATION] {v['type']}: '{v['phrase']}' in: {v['context'][:80]}")
    for w in result["warnings"]:
        print(f"  [WARNING] {w['type']}: {w['claim_id']} ({w['section_id']})")
