"""
Layer 8 — Module 11: Layer 8 Validation Gate

Validates Layer 8 output before handoff to Layer 9.

Hard failures (block Layer 9):
  1. script.md missing
  2. section_scripts.json missing
  3. total word count < 300
  4. cautious_language_report has violations (blocked phrases in script)

Soft warnings (pass with warning):
  5. word count outside 700-2000 range
  6. claim usage rate < 10% (script barely touches the evidence)
  7. no source URLs in youtube_metadata

Key functions:
    validate(run_id, layer8_dir) → report dict
    write_report(run_id, report, layer8_dir) → path
"""

import json
from pathlib import Path

_MIN_WORD_COUNT    = 300
_TARGET_WORD_LOW   = 700
_TARGET_WORD_HIGH  = 2000
_MIN_USAGE_RATE    = 0.10


def validate(run_id: str, layer8_dir: Path) -> dict:
    errors   = []
    warnings = []

    # ── Check 1 & 2: Required files ──────────────────────────────────────────
    script_md_path     = layer8_dir / "script.md"
    section_scripts_path = layer8_dir / "section_scripts.json"

    if not script_md_path.exists():
        return {
            "run_id":            run_id,
            "passed":            False,
            "status":            "failed",
            "failure_reason":    "script.md missing",
            "errors":            ["script.md not found in layer_8 output."],
            "warnings":          [],
            "ready_for_layer_9": False,
        }

    if not section_scripts_path.exists():
        errors.append("section_scripts.json missing from layer_8 output.")

    with open(layer8_dir / "generated_script.json") as f:
        gs = json.load(f)
    with open(layer8_dir / "claim_usage_report.json") as f:
        cur = json.load(f)
    with open(layer8_dir / "cautious_language_report.json") as f:
        clr = json.load(f)
    with open(layer8_dir / "youtube_metadata.json") as f:
        yt = json.load(f)

    # ── Check 3: Word count ───────────────────────────────────────────────────
    word_count = gs.get("total_word_count", 0)
    if word_count < _MIN_WORD_COUNT:
        errors.append(f"Script word count {word_count} is below minimum {_MIN_WORD_COUNT}.")

    # ── Check 4: Cautious language violations ────────────────────────────────
    violations = clr.get("violations", [])
    if violations:
        for v in violations:
            errors.append(
                f"Blocked phrase '{v.get('phrase', '?')}' found in script."
            )

    # ── Check 5 (soft): Word count range ─────────────────────────────────────
    if _MIN_WORD_COUNT <= word_count < _TARGET_WORD_LOW:
        warnings.append(
            f"Word count {word_count} is below target range "
            f"{_TARGET_WORD_LOW}-{_TARGET_WORD_HIGH}. Script may feel thin."
        )
    elif word_count > _TARGET_WORD_HIGH:
        warnings.append(
            f"Word count {word_count} exceeds target range. Script may run long."
        )

    # ── Check 6 (soft): Claim usage rate ─────────────────────────────────────
    usage_rate = cur.get("usage_rate", 0)
    if usage_rate < _MIN_USAGE_RATE:
        warnings.append(
            f"Claim usage rate {usage_rate:.1%} is below {_MIN_USAGE_RATE:.0%}. "
            "Script may not be grounded in the evidence packet."
        )

    # ── Check 7 (soft): Source URLs ──────────────────────────────────────────
    if yt.get("source_count", 0) == 0:
        warnings.append("No source URLs in youtube_metadata. Description will have no citations.")

    passed            = len(errors) == 0
    ready_for_layer_9 = passed

    return {
        "run_id":             run_id,
        "passed":             passed,
        "status":             "passed" if passed else "failed",
        "failure_reason":     errors[0] if errors else None,
        "errors":             errors,
        "warnings":           warnings,
        "ready_for_layer_9":  ready_for_layer_9,
        "checks_run":         7,
        "checks_passed":      7 - len(errors),
        "word_count":         word_count,
        "claim_usage_rate":   usage_rate,
        "source_count":       yt.get("source_count", 0),
        "cautious_passed":    clr.get("passed", False),
    }


def write_report(run_id: str, report: dict, layer8_dir: Path) -> Path:
    path = layer8_dir / "layer8_validation_report.json"
    with open(path, "w") as f:
        import json
        json.dump(report, f, indent=2)
    return path
