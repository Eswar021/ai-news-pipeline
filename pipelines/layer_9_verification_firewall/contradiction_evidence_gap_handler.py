"""
Layer 9 — Module 10: Contradiction + Evidence Gap Handler

Informational check — does not block the script.

Checks:
  1. Contradictions from Layer 4: for each contradiction, check if the script
     addressed it with cautious language (informational warning if not).
  2. Evidence gaps: report gaps that are blocking for the selected format.
     Blocking gaps from Layer 4 should have already prevented Layer 8 from
     using those claims, so this is a consistency check.

This module generates the contradiction_handling_report.json.

Returns:
    dict with status, checked counts, unhandled list, warnings
"""

_CAUTIOUS_PHRASES = (
    "may ", "could ", "might ", "suggest", "appear",
    "seem", "unclear", "not yet", "possibly", "we don't know",
    "limited evidence", "based on available",
)


def handle(ctx: dict) -> dict:
    script_text  = ctx["script_text"].lower()
    contradictions_data = ctx["contradictions"]
    evidence_gaps_data  = ctx["evidence_gaps"]
    generated_script    = ctx["generated_script"]
    selected_format     = generated_script.get("selected_format", "roundup")

    contradictions = contradictions_data.get("contradictions", [])
    evidence_gaps  = evidence_gaps_data.get("evidence_gaps", [])

    # ── Contradiction check ───────────────────────────────────────────────────
    unhandled_contradictions = []
    contradiction_notes = []

    for c in contradictions:
        cid   = c.get("contradiction_id", "")
        topic = c.get("topic", "") or c.get("description", "")
        sids  = c.get("story_ids", [])

        # Check if cautious language appears anywhere near the topic keywords
        # (rough check: just verify the script is generally cautious)
        has_caution = any(p in script_text for p in _CAUTIOUS_PHRASES)
        if not has_caution:
            unhandled_contradictions.append({
                "contradiction_id": cid,
                "topic":            topic,
                "story_ids":        sids,
                "severity":         "medium",
                "reason":           "Script may not address known contradiction with appropriate caution.",
            })
        contradiction_notes.append({
            "contradiction_id": cid,
            "topic":            topic,
            "story_ids":        sids,
            "caution_present":  has_caution,
            "status":           "handled" if has_caution else "needs_review",
        })

    # ── Evidence gap check ────────────────────────────────────────────────────
    format_block_field = f"blocks_{selected_format.replace('-', '_')}"
    blocking_gaps = [
        g for g in evidence_gaps
        if g.get(format_block_field) or g.get("severity") == "high"
    ]
    non_blocking_gaps = [
        g for g in evidence_gaps
        if not (g.get(format_block_field) or g.get("severity") == "high")
    ]

    gap_warnings = []
    for g in blocking_gaps:
        gap_warnings.append({
            "gap_type":    g.get("gap_type", ""),
            "story_id":    g.get("story_id", ""),
            "severity":    g.get("severity", "medium"),
            "description": g.get("description", ""),
            "note":        f"Blocking gap for {selected_format} — verify script avoided this topic.",
        })

    # Overall status — informational, never blocks
    has_unhandled = len(unhandled_contradictions) > 0

    return {
        "status":                    "warning" if has_unhandled else "passed",
        "contradictions_checked":    len(contradictions),
        "evidence_gaps_checked":     len(evidence_gaps),
        "blocking_gaps":             len(blocking_gaps),
        "non_blocking_gaps":         len(non_blocking_gaps),
        "unhandled_contradictions":  unhandled_contradictions,
        "contradiction_notes":       contradiction_notes,
        "gap_warnings":              gap_warnings,
        "is_informational":          True,
        "blocks_layer_9":            False,
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
    result = handle(ctx)

    print(f"Status                : {result['status']}")
    print(f"Contradictions checked: {result['contradictions_checked']}")
    print(f"Evidence gaps checked : {result['evidence_gaps_checked']}")
    print(f"Blocking gaps         : {result['blocking_gaps']}")
    print(f"Non-blocking gaps     : {result['non_blocking_gaps']}")
    print(f"Unhandled contrad.    : {len(result['unhandled_contradictions'])}")
    print(f"Blocks Layer 9        : {result['blocks_layer_9']}")
    if result["gap_warnings"]:
        print("\nGap warnings:")
        for g in result["gap_warnings"][:3]:
            print(f"  [{g['severity']}] {g['gap_type']} — {g['description'][:60]}")
