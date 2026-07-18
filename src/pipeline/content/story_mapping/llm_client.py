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
    temperature: float = 0.15,
    base_url: str | None = None,
):
    provider = provider.lower().strip()
    if provider == "openai":
        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": _resolve_env(["OPENAI_API_KEY", "OPENAI_API_KEY_A_C_C"]),
        }
        if _model_supports_temperature(model):
            kwargs["temperature"] = temperature
        return ChatOpenAI(**kwargs)

    if provider == "lmstudio":
        kwargs = {
            "model": model,
            "api_key": os.getenv("LMSTUDIO_API_KEY", "lm-studio"),
            "base_url": base_url or os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
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

    raise ValueError(f"Unknown LLM provider: {provider}. Use 'openai', 'lmstudio', or 'gemini'.")


def _resolve_env(keys: list[str]) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    raise RuntimeError(f"Required environment variable missing. Tried: {', '.join(keys)}")


def _model_supports_temperature(model: str) -> bool:
    normalized = model.lower().strip()
    if normalized.startswith("gpt-5"):
        return False
    return True
