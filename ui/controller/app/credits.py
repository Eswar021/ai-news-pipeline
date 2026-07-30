"""Provider credit/balance lookups for the run desk.

Only providers that expose an API-key-accessible balance are queried live
(DeepSeek, Moonshot/Kimi). Gemini has no such endpoint (it bills through Google
Cloud), so it is reported as unavailable with a dashboard link. Keys are read
from the project .env; results are cached briefly so refreshing the desk does not
hammer the provider APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Callable
import urllib.error
import urllib.request


_DASHBOARDS = {
    "deepseek": "https://platform.deepseek.com/usage",
    "moonshot": "https://platform.moonshot.ai/console/account",
    "gemini": "https://console.cloud.google.com/billing",
}


def _read_env(project_root: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    path = project_root / ".env"
    if not path.is_file():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _get_json(url: str, api_key: str, timeout: float = 6.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed provider hosts
        return json.loads(response.read().decode("utf-8"))


def _reason(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return "network unreachable"
    return f"{type(exc).__name__}"


class CreditsReader:
    def __init__(
        self,
        project_root: Path,
        *,
        ttl_seconds: float = 60.0,
        fetch: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.project_root = project_root
        self.ttl = ttl_seconds
        self._fetch_override = fetch
        self._cache: dict[str, Any] | None = None
        self._fetched_at = 0.0

    def _fetch(self, url: str, api_key: str) -> dict[str, Any]:
        # Resolve at call time so tests can monkeypatch the module-level fetcher.
        return (self._fetch_override or _get_json)(url, api_key)

    def credits(self, *, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._cache is not None and (now - self._fetched_at) < self.ttl:
            return self._cache
        env = _read_env(self.project_root)
        providers = [
            self._deepseek(env),
            self._moonshot(env),
            self._unavailable("gemini", "Gemini", env.get("GEMINI_TTS_API_KEY"), "Billed via Google Cloud; no balance API."),
        ]
        result = {
            "providers": [provider for provider in providers if provider],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._cache = result
        self._fetched_at = now
        return result

    def _deepseek(self, env: dict[str, str]) -> dict[str, Any] | None:
        api_key = env.get("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        base = (env.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        root = base.split("/v1")[0]  # balance lives at the API root, not under /v1
        try:
            data = self._fetch(f"{root}/user/balance", api_key)
            info = (data.get("balance_infos") or [{}])[0]
            return {
                "key": "deepseek",
                "label": "DeepSeek",
                "status": "ok",
                "balance": float(info.get("total_balance") or 0),
                "currency": info.get("currency") or "USD",
                "available": bool(data.get("is_available")),
                "dashboard": _DASHBOARDS["deepseek"],
            }
        except Exception as exc:  # noqa: BLE001 - any failure degrades to a link
            return {"key": "deepseek", "label": "DeepSeek", "status": "error", "reason": _reason(exc), "dashboard": _DASHBOARDS["deepseek"]}

    def _moonshot(self, env: dict[str, str]) -> dict[str, Any] | None:
        api_key = env.get("MOONSHOT_API_KEY")
        if not api_key:
            return None
        base = (env.get("MOONSHOT_BASE_URL") or "https://api.moonshot.ai/v1").rstrip("/")
        try:
            data = self._fetch(f"{base}/users/me/balance", api_key)
            balance = (data.get("data") or {})
            return {
                "key": "moonshot",
                "label": "Kimi (Moonshot)",
                "status": "ok",
                "balance": float(balance.get("available_balance") or 0),
                "currency": "USD" if "moonshot.ai" in base else "CNY",
                "available": bool(data.get("status", True)),
                "dashboard": _DASHBOARDS["moonshot"],
            }
        except Exception as exc:  # noqa: BLE001
            return {"key": "moonshot", "label": "Kimi (Moonshot)", "status": "error", "reason": _reason(exc), "dashboard": _DASHBOARDS["moonshot"]}

    def _unavailable(self, key: str, label: str, present: str | None, reason: str) -> dict[str, Any] | None:
        if not present:
            return None
        return {"key": key, "label": label, "status": "unavailable", "reason": reason, "dashboard": _DASHBOARDS.get(key, "")}
