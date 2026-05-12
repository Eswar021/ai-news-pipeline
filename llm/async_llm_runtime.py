"""
Shared async LLM runtime for active pipeline modules.

This module is the single runtime surface for:
  - manifest-backed model/profile resolution
  - AsyncOpenAI client creation
  - structured per-call logging in output/llm_logs/

Active async layers should call this helper instead of constructing their own
AsyncOpenAI clients directly.
"""

from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from openai import AsyncOpenAI

from config.paths import ENV_FILE, LLM_LOGS, ensure_all_dirs
from config.time_utils import now_project_file_stamp, now_project_iso
from pipelines.runtime_manifest import get_llm_profile


def _load_env() -> None:
    load_dotenv(ENV_FILE)


def _safe_label(value: str | None, fallback: str) -> str:
    text = (value or "").strip() or fallback
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text)[:80]


def _log_dir_for_run(run_id: str | None) -> Path:
    ensure_all_dirs()
    log_dir = LLM_LOGS / _safe_label(run_id, "adhoc")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _now_iso() -> str:
    return now_project_iso()


def _usage_dict(resp) -> dict | None:
    usage = getattr(resp, "usage", None)
    if not usage:
        return None

    data = {}
    for attr in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "reasoning_tokens",
        "cached_tokens",
    ):
        value = getattr(usage, attr, None)
        if value is not None:
            data[attr] = value
    return data or None


def _choice_finish_reasons(resp) -> list[str]:
    reasons = []
    for choice in getattr(resp, "choices", []) or []:
        reason = getattr(choice, "finish_reason", None)
        if reason:
            reasons.append(reason)
    return reasons


def _write_log(
    *,
    run_id: str | None,
    module_name: str,
    request_name: str | None,
    payload: dict,
) -> str:
    timestamp = now_project_file_stamp()
    module_part = _safe_label(module_name, "module")
    request_part = _safe_label(request_name, "request")
    filename = f"{timestamp}_{module_part}_{request_part}_{uuid4().hex[:8]}.json"
    path = _log_dir_for_run(run_id) / filename
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _api_key() -> str:
    _load_env()
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_A_C_C")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured in .env")
    return api_key


@lru_cache(maxsize=1)
def get_async_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=_api_key())


def resolve_openai_profile(
    module_name: str,
    *,
    run_id: str | None = None,
    manifest: dict | None = None,
) -> dict:
    profile = get_llm_profile(module_name, run_id=run_id, manifest=manifest)
    provider = profile.get("provider", "openai")
    if provider != "openai":
        raise ValueError(
            f"{module_name} currently supports only provider='openai' in the async runtime, "
            f"got provider='{provider}'."
        )
    return dict(profile)


def build_chat_create_kwargs(
    *,
    model: str,
    messages: list[dict],
    temperature: float,
    response_format: dict | None = None,
    extra_kwargs: dict | None = None,
) -> dict:
    kwargs: dict = {
        "model": model,
        "messages": messages,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    if "nano" not in model.lower():
        kwargs["temperature"] = temperature
    if extra_kwargs:
        kwargs.update(extra_kwargs)
    return kwargs


async def execute_chat_request(
    *,
    module_name: str,
    run_id: str | None,
    messages: list[dict],
    request_name: str | None = None,
    metadata: dict | None = None,
    manifest: dict | None = None,
    response_format: dict | None = None,
    parse_json: bool = False,
    extra_kwargs: dict | None = None,
) -> object:
    profile = resolve_openai_profile(module_name, run_id=run_id, manifest=manifest)
    client = get_async_openai_client()
    model = profile["model"]
    temperature = profile["temperature"]
    create_kwargs = build_chat_create_kwargs(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format=response_format or ({"type": "json_object"} if parse_json else None),
        extra_kwargs=extra_kwargs,
    )

    started_at = _now_iso()
    start_time = time.perf_counter()
    raw_text = ""
    response_payload = None
    error_payload = None

    try:
        resp = await client.chat.completions.create(**create_kwargs)
        duration = round(time.perf_counter() - start_time, 3)
        raw_text = ((resp.choices[0].message.content) or "").strip()

        if parse_json:
            try:
                response_payload = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                error_payload = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "raw_response_excerpt": raw_text[:1000],
                }
                raise
        else:
            response_payload = raw_text

        log_payload = {
            "timestamp": started_at,
            "completed_at": _now_iso(),
            "run_id": run_id,
            "module": module_name,
            "request_name": request_name,
            "provider": "openai",
            "profile": profile,
            "request": {
                "messages": messages,
                "response_format": response_format or ({"type": "json_object"} if parse_json else None),
                "extra_kwargs": extra_kwargs or {},
            },
            "response": {
                "raw_text": raw_text,
                "parsed_json": response_payload if parse_json else None,
                "finish_reasons": _choice_finish_reasons(resp),
                "usage": _usage_dict(resp),
                "duration_seconds": duration,
                "system_fingerprint": getattr(resp, "system_fingerprint", None),
            },
            "status": "ok",
            "metadata": metadata or {},
        }
        log_path = _write_log(
            run_id=run_id,
            module_name=module_name,
            request_name=request_name,
            payload=log_payload,
        )
        if isinstance(response_payload, dict):
            response_payload.setdefault("_llm_log_path", log_path)
        return response_payload
    except Exception as exc:
        duration = round(time.perf_counter() - start_time, 3)
        log_payload = {
            "timestamp": started_at,
            "completed_at": _now_iso(),
            "run_id": run_id,
            "module": module_name,
            "request_name": request_name,
            "provider": "openai",
            "profile": profile,
            "request": {
                "messages": messages,
                "response_format": response_format or ({"type": "json_object"} if parse_json else None),
                "extra_kwargs": extra_kwargs or {},
            },
            "response": {
                "raw_text": raw_text,
                "parsed_json": response_payload if parse_json else None,
                "duration_seconds": duration,
            },
            "status": "error",
            "error": error_payload or {
                "type": type(exc).__name__,
                "message": str(exc),
            },
            "metadata": metadata or {},
        }
        try:
            _write_log(
                run_id=run_id,
                module_name=module_name,
                request_name=request_name,
                payload=log_payload,
            )
        except Exception:
            pass
        raise
