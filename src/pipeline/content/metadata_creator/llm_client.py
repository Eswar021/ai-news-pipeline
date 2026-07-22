from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


load_dotenv()


def make_llm(
    *,
    provider: str,
    model: str,
    temperature: float = 0.4,
    base_url: str | None = None,
    max_retries: int = 0,
    provider_options: dict[str, Any] | None = None,
):
    provider = provider.lower().strip()
    options = dict(provider_options or {})
    request_timeout_seconds = float(options.pop("request_timeout_seconds", 300.0))
    if provider == "openai":
        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": _resolve_env(["OPENAI_API_KEY", "OPENAI_API_KEY_A_C_C"]),
            "max_retries": max_retries,
            "timeout": request_timeout_seconds,
        }
        if _model_supports_temperature(model):
            kwargs["temperature"] = temperature
        return ChatOpenAI(**kwargs)

    if provider == "lmstudio":
        kwargs = {
            "model": model,
            "api_key": os.getenv("LMSTUDIO_API_KEY", "lm-studio"),
            "base_url": base_url or os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
            "max_retries": max_retries,
            "timeout": request_timeout_seconds,
        }
        if _model_supports_temperature(model):
            kwargs["temperature"] = temperature
        return ChatOpenAI(**kwargs)

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
            unknown = ", ".join(sorted(options))
            raise ValueError(f"Unknown Moonshot provider option(s): {unknown}")

        kwargs = {
            "model": model,
            "api_key": _resolve_env(["MOONSHOT_API_KEY", "KIMI_API_KEY"]),
            "base_url": base_url or os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
            "max_retries": max_retries,
            "timeout": request_timeout_seconds,
        }
        if not omit_temperature:
            kwargs["temperature"] = temperature
        if thinking:
            kwargs["extra_body"] = {"thinking": {"type": thinking}}
        return ChatOpenAI(**kwargs)

    if provider == "deepseek":
        thinking = options.pop("thinking", "disabled")
        omit_temperature = bool(options.pop("omit_temperature", thinking == "enabled"))
        reasoning_effort = options.pop("reasoning_effort", None)
        if options:
            unknown = ", ".join(sorted(options))
            raise ValueError(f"Unknown DeepSeek provider option(s): {unknown}")

        kwargs = {
            "model": model,
            "api_key": _resolve_env(["DEEPSEEK_API_KEY"]),
            "base_url": base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "max_retries": max_retries,
            "timeout": request_timeout_seconds,
            "extra_body": {"thinking": {"type": thinking}},
        }
        if not omit_temperature:
            kwargs["temperature"] = temperature
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        return ChatOpenAI(**kwargs)

    raise ValueError(
        "Unknown LLM provider: "
        f"{provider}. Use 'openai', 'lmstudio', 'gemini', 'moonshot', or 'deepseek'."
    )


def _resolve_env(keys: list[str]) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    raise RuntimeError(f"Required environment variable missing. Tried: {', '.join(keys)}")


def _model_supports_temperature(model: str) -> bool:
    return not model.lower().strip().startswith("gpt-5")
