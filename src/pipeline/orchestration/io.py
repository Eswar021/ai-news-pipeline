from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object at {resolved}")
    return value


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    resolved.write_text(f"{text}\n" if text else "", encoding="utf-8")
    return resolved


def write_handoff_files(files: list[dict[str, Any]], output_dir: str | Path) -> list[str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for item in files:
        filename = str(item.get("filename", "")).strip()
        if not filename or "/" in filename or "\\" in filename:
            raise ValueError(f"Unsafe handoff filename: {filename!r}")
        path = root / filename
        path.write_text(str(item.get("content", "")), encoding="utf-8")
        written.append(str(path))
    return written

