from __future__ import annotations

from pathlib import Path

from src.config.paths import PROMPTS_DIR


def load_system_prompt(module_name: str, version: str) -> str:
    path = PROMPTS_DIR / version / module_name / "system.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_prompt_bundle(module_name: str, version: str) -> dict[str, str]:
    return {
        "version": version,
        "system": load_system_prompt(module_name, version),
    }
