"""The single LLM client for the whole pipeline.

Consolidated from five drifted per-module copies of `make_llm` (which is why
DeepSeek worked in some modules and not others). Supports openai, deepseek, gemini,
lmstudio, and moonshot — so any module can use any provider from config alone.

Behavior is preserved across the old copies with one rule: callers that manage their
own retries/timeout (the runtime-wrapped modules) pass ``max_retries`` and/or
``provider_options`` and thereby opt into an explicit retry count + request timeout;
callers that pass neither keep langchain's defaults — exactly how the lighter modules
(story_mapping, editorial_triage, editorial_selection) behaved before consolidation.
"""
from __future__ import annotations

import os
from typing import Any, Literal

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

load_dotenv()

# The single source of truth for supported providers — used by make_llm AND by every
# module's config contract, so provider support can never drift between them again.
LLMProvider = Literal["openai", "gemini", "lmstudio", "moonshot", "deepseek"]


def make_llm(
    *,
    provider: str,
    model: str,
    temperature: float = 0.4,
    base_url: str | None = None,
    max_retries: int | None = None,
    provider_options: dict[str, Any] | None = None,
):
    provider = provider.lower().strip()
    options = dict(provider_options or {})
    request_timeout_seconds = float(options.pop("request_timeout_seconds", 300.0))
    # A caller opts into explicit retry/timeout by passing either signal; otherwise we
    # leave langchain's defaults untouched (the lean modules' original behavior).
    opted_in = max_retries is not None or provider_options is not None
    effective_retries = max_retries if max_retries is not None else 0

    def tuned(kwargs: dict[str, Any]) -> dict[str, Any]:
        if opted_in:
            kwargs["max_retries"] = effective_retries
            kwargs["timeout"] = request_timeout_seconds
        return kwargs

    if provider == "openai":
        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": _resolve_env(["OPENAI_API_KEY", "OPENAI_API_KEY_A_C_C"]),
        }
        if _model_supports_temperature(model):
            kwargs["temperature"] = temperature
        return ChatOpenAI(**tuned(kwargs))

    if provider == "lmstudio":
        kwargs = {
            "model": model,
            "api_key": os.getenv("LMSTUDIO_API_KEY", "lm-studio"),
            "base_url": base_url or os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
        }
        if _model_supports_temperature(model):
            kwargs["temperature"] = temperature
        return ChatOpenAI(**tuned(kwargs))

    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=model,
            api_key=_resolve_env(["GOOGLE_API_KEY", "GEMINI_API_KEY"]),
            temperature=temperature,
        )

    if provider == "moonshot":
        thinking = options.pop("thinking", None)
        omit_temperature = bool(options.pop("omit_temperature", False))
        if options:
            raise ValueError(f"Unknown Moonshot provider option(s): {', '.join(sorted(options))}")
        kwargs = {
            "model": model,
            "api_key": _resolve_env(["MOONSHOT_API_KEY", "KIMI_API_KEY"]),
            "base_url": base_url or os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
        }
        if not omit_temperature:
            kwargs["temperature"] = temperature
        if thinking:
            kwargs["extra_body"] = {"thinking": {"type": thinking}}
        return ChatOpenAI(**tuned(kwargs))

    if provider == "deepseek":
        thinking = options.pop("thinking", "disabled")
        omit_temperature = bool(options.pop("omit_temperature", thinking == "enabled"))
        reasoning_effort = options.pop("reasoning_effort", None)
        if options:
            raise ValueError(f"Unknown DeepSeek provider option(s): {', '.join(sorted(options))}")
        kwargs = {
            "model": model,
            "api_key": _resolve_env(["DEEPSEEK_API_KEY"]),
            "base_url": base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "extra_body": {"thinking": {"type": thinking}},
        }
        if not omit_temperature:
            kwargs["temperature"] = temperature
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        return ChatOpenAI(**tuned(kwargs))

    raise ValueError(
        f"Unknown LLM provider: {provider}. "
        "Use 'openai', 'deepseek', 'gemini', 'lmstudio', or 'moonshot'."
    )


def _resolve_env(keys: list[str]) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    raise RuntimeError(f"Required environment variable missing. Tried: {', '.join(keys)}")


def _model_supports_temperature(model: str) -> bool:
    return not model.lower().strip().startswith("gpt-5")
