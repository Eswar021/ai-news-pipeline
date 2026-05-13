"""
Layer 5 — Evidence Safety Gate

Converts Layer 4 evidence density/fact-sheet safety into compact per-story,
per-format safety records for editorial selection.
"""

from __future__ import annotations


def gate(candidate: dict, allowed_formats: list[str]) -> dict:
    blocking_gaps = candidate.get("blocking_gaps", [])

    format_status = {}
    any_safe = False
    for fmt in allowed_formats:
        safe_flag = candidate.get(f"safe_for_{fmt}", False)
        blocking_gap = next((gap for gap in blocking_gaps if gap.get(f"blocks_{fmt}")), None)
        if blocking_gap:
            format_status[fmt] = {
                "status": "blocked",
                "reason": f"Blocking evidence gap: {blocking_gap['gap_type']}.",
            }
        elif safe_flag:
            format_status[fmt] = {
                "status": "safe",
                "reason": f"Layer 4 marked this story safe for {fmt}.",
            }
            any_safe = True
        else:
            format_status[fmt] = {
                "status": "blocked",
                "reason": f"Layer 4 did not clear this story for {fmt}.",
            }

    return {
        "story_id": candidate["story_id"],
        "overall_status": "safe" if any_safe else "blocked",
        "overall_reason": "" if any_safe else "No allowed format passed the evidence gate.",
        "formats": format_status,
    }


def gate_all(candidates: list[dict], allowed_formats: list[str]) -> list[dict]:
    return [gate(candidate, allowed_formats) for candidate in candidates]
