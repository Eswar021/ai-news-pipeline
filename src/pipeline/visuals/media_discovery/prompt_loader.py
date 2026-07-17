from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_system_prompt(version: str, module_name: str = "media_candidate_verifier") -> str:
    path = PROMPTS_DIR / version / module_name / "system.txt"
    if not path.exists():
        raise FileNotFoundError(f"Media verifier prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()
