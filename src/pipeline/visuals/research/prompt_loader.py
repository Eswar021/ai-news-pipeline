from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt_bundle(version: str) -> dict[str, str]:
    prompt_dir = PROMPTS_DIR / version / "story_visual_researcher"
    system_path = prompt_dir / "system.txt"
    user_path = prompt_dir / "user_preamble.txt"
    if not system_path.is_file() or not user_path.is_file():
        raise FileNotFoundError(f"Visual research prompt bundle is incomplete: {prompt_dir}")
    return {
        "system": system_path.read_text(encoding="utf-8").strip(),
        "user_preamble": user_path.read_text(encoding="utf-8").strip(),
    }
