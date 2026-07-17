from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt_bundle(version: str) -> dict[str, str]:
    prompt_dir = PROMPTS_DIR / version / "editorial_triage"
    paths = {
        "system": prompt_dir / "system.txt",
        "user_preamble": prompt_dir / "user_preamble.txt",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Editorial triage prompt files missing: {', '.join(missing)}")
    return {name: path.read_text(encoding="utf-8").strip() for name, path in paths.items()}
