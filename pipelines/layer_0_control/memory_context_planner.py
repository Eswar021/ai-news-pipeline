"""
Module: memory_context_planner
Layer: 0 — Channel Strategy + Run Control
Purpose: Define which memory stores are loaded at which pipeline stages and with what windows.
         Memory is not passed wholesale — it is loaded selectively by Layer 5 and Layer 9.
"""

from pathlib import Path


def plan_memory_context(
    run_mode: str,
    memory_windows: dict,
    memory_dir: Path,
) -> dict:
    """
    Returns the memory policy and paths for this run.

    Design decisions encoded here:
    - Full previous scripts are NOT passed to the script writer (avoids copying past voice)
    - Entity memory is loaded on-demand in Layer 3, not upfront (avoids flooding context)
    - Similarity check happens at two points: before story selection (L5) and after script (L9)
    - Memory is updated only after Layer 9 verifies and approves the script

    Returns:
        dict with: memory_policy, memory_windows, memory_paths
    """
    return {
        "memory_policy": {
            "load_thesis_memory": True,
            "load_published_video_memory": True,
            "load_claim_ledger": True,
            "load_entity_memory_on_demand": True,
            "load_full_previous_scripts": False,
            "check_similarity_before_selection": True,
            "check_similarity_after_script": True,
            "update_memory_after_verification": True,
        },
        "memory_windows": memory_windows,
        "memory_paths": {
            "video_memory":               str(memory_dir / "video_memory.jsonl"),
            "story_coverage_memory":      str(memory_dir / "story_coverage_memory.jsonl"),
            "claim_ledger":               str(memory_dir / "claim_ledger.jsonl"),
            "entity_topic_memory":        str(memory_dir / "entity_topic_memory.jsonl"),
            "source_memory":              str(memory_dir / "source_memory.jsonl"),
            "editorial_pattern_memory":   str(memory_dir / "editorial_pattern_memory.jsonl"),
            "followups":                  str(memory_dir / "followups.jsonl"),
            "evidence_gap_watchlist":     str(memory_dir / "evidence_gap_watchlist.jsonl"),
            "rejected_claim_patterns":    str(memory_dir / "rejected_claim_patterns.jsonl"),
            "performance_memory":         str(memory_dir / "performance_memory.jsonl"),
            "learning_signals":           str(memory_dir / "learning_signals.jsonl"),
            "memory_index":               str(memory_dir / "memory_index.json"),
            "memory_snapshot":            str(memory_dir / "memory_snapshot.json"),
        },
    }
