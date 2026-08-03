"""Thin wrapper: load topic_research prompts via the shared loader."""
from __future__ import annotations

from pathlib import Path

from ..script_generation.shared.prompt_loader import load_prompt_bundle as _shared_load

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt_bundle(module_name: str, version: str) -> dict[str, str]:
    return _shared_load(_PROMPTS_DIR, module_name, version)
