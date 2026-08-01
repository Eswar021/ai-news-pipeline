from __future__ import annotations

from pathlib import Path


def load_prompt_bundle(prompts_dir: Path, module_name: str, version: str) -> dict[str, str]:
    """Load a {system, user_preamble} prompt bundle from a format's prompts dir.

    Format-agnostic: the caller passes its own prompts directory, so each format
    keeps its prompts local while sharing the loader.
    """
    prompt_dir = Path(prompts_dir) / version / module_name
    system_path = prompt_dir / "system.txt"
    user_preamble_path = prompt_dir / "user_preamble.txt"
    if not system_path.exists():
        raise FileNotFoundError(f"Script prompt file not found: {system_path}")
    if not user_preamble_path.exists():
        raise FileNotFoundError(f"Script prompt file not found: {user_preamble_path}")
    return {
        "system": system_path.read_text(encoding="utf-8").strip(),
        "user_preamble": user_preamble_path.read_text(encoding="utf-8").strip(),
    }
