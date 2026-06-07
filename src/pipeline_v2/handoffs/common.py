from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any


IST = timezone(timedelta(hours=5, minutes=30))
WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str:
    return WHITESPACE_RE.sub(" ", str(value or "")).strip()


def iso_now() -> str:
    return datetime.now(IST).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at: {path}")
    return data


def write_text_files(files: list[dict[str, str]], output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for file_info in files:
        filename = file_info["filename"]
        if "/" in filename or "\\" in filename:
            raise ValueError(f"Unsafe handoff filename: {filename}")
        path = output_dir / filename
        path.write_text(file_info["content"], encoding="utf-8")
        paths.append(str(path))
    return paths
