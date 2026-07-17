from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


load_dotenv()


def make_llm(*, model: str, temperature: float = 0.0):
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": _resolve_env(["OPENAI_API_KEY", "OPENAI_API_KEY_A_C_C"]),
    }
    if not model.lower().strip().startswith("gpt-5"):
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


def _resolve_env(keys: list[str]) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    raise RuntimeError(f"Required environment variable missing. Tried: {', '.join(keys)}")
