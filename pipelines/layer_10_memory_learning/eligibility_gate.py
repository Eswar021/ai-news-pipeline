"""
Layer 10 — Module 2: Memory Update Eligibility Gate

Reads Layer 9 final_recommendation and determines what memory updates are allowed.

Approval gates:
  approved                → full durable memory update
  approved_with_warnings  → full durable memory update (with warning flags)
  requires_revision       → run audit log only; no video/claim/source memory
  blocked                 → risk patterns only

Returns:
  dict with per-memory-file update flags + eligibility status
"""


_DURABLE_STATUSES = {"approved", "approved_with_warnings"}


def gate(ctx: dict) -> dict:
    fpp    = ctx["final_publish_package"]
    status = fpp["approval"]["status"]
    ready  = fpp["memory_handoff"]["ready_for_layer_10"]

    if not ready:
        return {
            "status":                      "not_ready",
            "durable_memory_allowed":      False,
            "video_memory_allowed":        False,
            "claim_ledger_allowed":        False,
            "source_memory_allowed":       False,
            "editorial_pattern_allowed":   False,
            "story_coverage_allowed":      False,
            "entity_topic_memory_allowed": False,
            "followup_allowed":            False,
            "evidence_gap_watchlist_allowed": False,
            "risk_pattern_allowed":        False,
            "reason":                      "layer_9_not_ready_for_layer_10",
        }

    durable = status in _DURABLE_STATUSES

    return {
        "status":                        "eligible" if durable else "risk_patterns_only",
        "l9_approval_status":            status,
        "durable_memory_allowed":        durable,
        "video_memory_allowed":          durable,
        "claim_ledger_allowed":          durable,
        "source_memory_allowed":         durable,
        "editorial_pattern_allowed":     durable,
        "story_coverage_allowed":        durable,
        "entity_topic_memory_allowed":   durable,
        "followup_allowed":              durable,
        "evidence_gap_watchlist_allowed": True,   # always record gaps
        "risk_pattern_allowed":          True,    # always record risk patterns
        "has_warnings":                  status == "approved_with_warnings",
        "reason":                        status,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_10_memory_learning.context_loader import load

    run_id = "run_2026_05_10_48h_auto"
    base   = RUNS_DIR / run_id
    ctx    = load(base / "layer_9", base / "layer_8", base / "layer_7",
                  base / "layer_5", base / "layer_4", base / "layer_3")
    result = gate(ctx)
    for k, v in result.items():
        print(f"  {k}: {v}")
