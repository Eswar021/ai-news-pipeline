from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import Lock


IST = timezone(timedelta(hours=5, minutes=30))
_LOG_LOCK = Lock()


def append_llm_call(
    *,
    log_path: Path,
    module_name: str,
    model: str,
    messages: list[dict],
    response_text: str,
    parsed_output: dict | None,
    metadata: dict | None,
    duration_seconds: float,
    usage: dict | None = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(IST).isoformat(),
        "module": module_name,
        "model": model,
        "duration_seconds": round(duration_seconds, 3),
        "messages": messages,
        "response_text": response_text,
        "parsed_output": parsed_output,
        "usage": usage or {},
        "metadata": metadata or {},
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _LOG_LOCK:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
