"""
Rebuild compact published-memory artifacts after publish-state or analytics changes.
"""

from __future__ import annotations

from pathlib import Path

from pipelines.layer_10_memory_learning.learning_signal_builder import build as build_signals
from pipelines.layer_10_memory_learning.memory_index_builder import build as build_index
from pipelines.layer_10_memory_learning.memory_snapshot_builder import build as build_snapshot


def rebuild_published_memory_artifacts(memory_dir: Path) -> dict:
    signal_result = build_signals(mc={}, ctx={"run_id": "memory_rebuild"}, memory_dir=memory_dir)
    index_result = build_index(memory_dir)
    snapshot_result = build_snapshot(memory_dir)
    return {
        "status": "rebuilt",
        "learning_signals": signal_result,
        "memory_index": index_result,
        "memory_snapshot": snapshot_result,
    }
