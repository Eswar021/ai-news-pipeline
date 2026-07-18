from __future__ import annotations

import re
from typing import Any


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(value: Any) -> str:
    text = clean_text(value).lower()
    if not text or text == "unknown":
        return ""
    text = re.sub(r"[^a-z0-9|_\- ]+", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:160]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def round_to_five(value: float) -> int:
    return int(round(value / 5.0) * 5)


def count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = clean_text(value) or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts
