from __future__ import annotations

from pathlib import Path

from ...shared.prompt_loader import load_prompt_bundle as _load_prompt_bundle

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt_bundle(module_name: str, version: str) -> dict[str, str]:
    return _load_prompt_bundle(PROMPTS_DIR, module_name, version)
