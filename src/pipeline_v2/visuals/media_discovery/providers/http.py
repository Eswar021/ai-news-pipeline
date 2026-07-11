from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def get_json(
    url: str,
    *,
    timeout_seconds: int,
    user_agent: str,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"User-Agent": user_agent, "Accept": "application/json"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object from {url}")
    return payload


def download_file(
    url: str,
    *,
    output_path: Path,
    timeout_seconds: int,
    max_bytes: int,
    user_agent: str,
) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": user_agent})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    content_type = ""
    try:
        with urlopen(request, timeout=timeout_seconds) as response, output_path.open("wb") as handle:
            content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
            declared_size = int(response.headers.get("Content-Length", "0") or 0)
            if declared_size > max_bytes:
                raise ValueError(f"Remote asset is {declared_size} bytes, over the {max_bytes} byte limit")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Downloaded asset exceeded the {max_bytes} byte limit")
                handle.write(chunk)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    if total == 0:
        output_path.unlink(missing_ok=True)
        raise ValueError("Downloaded asset is empty")
    return total, content_type
