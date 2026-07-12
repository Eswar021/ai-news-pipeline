from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


_WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
