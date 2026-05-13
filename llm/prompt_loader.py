"""
Manifest-backed prompt loader for active LLM modules.

Runtime never reads prompt authoring config directly. Layer 0 snapshots the
resolved prompt registry into run_manifest.json, and active modules load from
that snapshot only.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from config.paths import PROMPTS_DIR
from pipelines.runtime_manifest import get_prompt_runtime_snapshot, load_manifest


def _normalize_entry(module_name: str, snapshot: dict) -> dict:
    modules = snapshot.get("modules", {})
    entry = modules.get(module_name)
    if not isinstance(entry, dict):
        raise KeyError(
            f"run_manifest.json resolved_config.prompts.modules is missing entry for '{module_name}'."
        )
    version = entry.get("version")
    module_dir = entry.get("module_dir")
    system_file = entry.get("system_file")
    if not version or not module_dir or not system_file:
        raise KeyError(
            f"Prompt config for '{module_name}' is incomplete; "
            "required fields: version, module_dir, system_file."
        )
    return dict(entry)


@lru_cache(maxsize=128)
def _read_prompt_text(version: str, module_dir: str, filename: str) -> str:
    path = PROMPTS_DIR / version / module_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_prompt_bundle(
    module_name: str,
    *,
    run_id: str | None = None,
    manifest: dict | None = None,
) -> dict:
    manifest = manifest or load_manifest(run_id=run_id)
    snapshot = get_prompt_runtime_snapshot(manifest)
    entry = _normalize_entry(module_name, snapshot)

    version = entry["version"]
    module_dir = entry["module_dir"]
    system_text = _read_prompt_text(version, module_dir, entry["system_file"])

    user_preamble = None
    if entry.get("user_preamble_file"):
        user_preamble = _read_prompt_text(version, module_dir, entry["user_preamble_file"])

    return {
        "version": version,
        "module_dir": module_dir,
        "system": system_text,
        "user_preamble": user_preamble,
    }
