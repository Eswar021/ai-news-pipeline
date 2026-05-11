"""
Layer 9 — Module 2: Script Structure Validator

Validates that the generated script follows the Layer 7 section plan:
  - format matches
  - all planned sections are present
  - sections are in the correct order
  - estimated duration is within target range

Returns:
    dict with status, checks, warnings, errors
"""

_TARGET_DURATION_TOLERANCE = 0.30  # ±30% of target is a soft warning


def validate(ctx: dict) -> dict:
    errors = []
    warnings = []
    checks = {}

    gs = ctx["generated_script"]
    sp = ctx["section_plan"]
    brief = ctx["script_writer_brief"]
    section_scripts = ctx["section_scripts"]

    # ── Format check ─────────────────────────────────────────────────────────
    gen_fmt = gs.get("selected_format", "")
    plan_fmt = brief.get("video_identity", {}).get("selected_format", "")
    if gen_fmt == plan_fmt:
        checks["format_match"] = "passed"
    else:
        errors.append(f"Format mismatch: script is '{gen_fmt}', plan expects '{plan_fmt}'.")
        checks["format_match"] = "failed"

    # ── Section presence and order ────────────────────────────────────────────
    planned_keys = [s["section_key"] for s in sp.get("sections", [])]
    generated_sections = section_scripts.get("sections", [])
    generated_keys = [s["section_key"] for s in generated_sections]

    missing = [k for k in planned_keys if k not in generated_keys]
    extra   = [k for k in generated_keys if k not in planned_keys]

    if missing:
        errors.append(f"Missing sections from plan: {missing}")
        checks["sections_present"] = "failed"
    else:
        checks["sections_present"] = "passed"

    if extra:
        warnings.append(f"Extra sections not in plan: {extra}")

    # Section order — check planned order is preserved (ignoring extras)
    plan_order = [k for k in planned_keys if k in generated_keys]
    gen_order  = [k for k in generated_keys if k in planned_keys]
    if plan_order != gen_order:
        warnings.append(f"Section order differs from plan. Expected {plan_order}, got {gen_order}.")
        checks["section_order"] = "warning"
    else:
        checks["section_order"] = "passed"

    # ── Duration check ────────────────────────────────────────────────────────
    target_secs = brief.get("video_identity", {}).get("target_duration_seconds", 0)
    actual_secs = gs.get("estimated_seconds", 0)
    if target_secs and actual_secs:
        low  = target_secs * (1 - _TARGET_DURATION_TOLERANCE)
        high = target_secs * (1 + _TARGET_DURATION_TOLERANCE)
        if actual_secs < low:
            warnings.append(
                f"Estimated duration {actual_secs}s is below target {target_secs}s "
                f"(lower bound {low:.0f}s)."
            )
            checks["duration"] = "warning_short"
        elif actual_secs > high:
            warnings.append(
                f"Estimated duration {actual_secs}s exceeds target {target_secs}s "
                f"(upper bound {high:.0f}s)."
            )
            checks["duration"] = "warning_long"
        else:
            checks["duration"] = "passed"
    else:
        checks["duration"] = "skipped"

    # ── Section count ─────────────────────────────────────────────────────────
    plan_count = sp.get("section_count", 0)
    gen_count  = section_scripts.get("section_count", 0)
    if plan_count != gen_count:
        warnings.append(f"Section count mismatch: plan={plan_count}, generated={gen_count}.")
        checks["section_count"] = "warning"
    else:
        checks["section_count"] = "passed"

    passed = len(errors) == 0

    return {
        "passed":             passed,
        "status":             "passed" if passed else "failed",
        "errors":             errors,
        "warnings":           warnings,
        "checks":             checks,
        "selected_format":    gen_fmt,
        "planned_sections":   planned_keys,
        "generated_sections": generated_keys,
        "target_duration_s":  target_secs,
        "actual_duration_s":  actual_secs,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_9_verification_firewall.context_loader import load

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")

    result = validate(ctx)
    print(f"Status   : {result['status']}")
    print(f"Format   : {result['selected_format']}")
    print(f"Checks   : {result['checks']}")
    print(f"Sections : {result['planned_sections']}")
    print(f"Duration : {result['actual_duration_s']}s / {result['target_duration_s']}s target")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  ERROR: {e}")
    if result["warnings"]:
        for w in result["warnings"]:
            print(f"  WARN : {w}")
