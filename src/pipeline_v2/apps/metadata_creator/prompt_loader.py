from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt_bundle(module_name: str, version: str) -> dict[str, str]:
    prompt_dir = PROMPTS_DIR / version / module_name
    system_path = prompt_dir / "system.txt"
    user_preamble_path = prompt_dir / "user_preamble.txt"
    if not system_path.exists():
        raise FileNotFoundError(f"Metadata prompt file not found: {system_path}")
    if not user_preamble_path.exists():
        raise FileNotFoundError(f"Metadata prompt file not found: {user_preamble_path}")
    return {
        "system": system_path.read_text(encoding="utf-8").strip(),
        "user_preamble": user_preamble_path.read_text(encoding="utf-8").strip(),
    }
