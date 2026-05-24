from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from src.llm.logger import append_llm_call


load_dotenv()


def _resolve_env(keys: list[str]) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    raise RuntimeError(f"Required environment variable missing. Tried: {', '.join(keys)}")


class OpenAIJSONClient:
    def __init__(self, model: str, temperature: float = 0.15):
        self.model = model
        self.temperature = temperature
        self._client = OpenAI(api_key=_resolve_env(["OPENAI_API_KEY", "OPENAI_API_KEY_A_C_C"]))

    def generate_json(
        self,
        *,
        module_name: str,
        system_prompt: str,
        user_prompt: str,
        log_path: Path,
        metadata: dict | None = None,
    ) -> dict:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        started = time.time()
        response = self._client.chat.completions.create(
            **build_chat_create_kwargs(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
        )
        duration = time.time() - started

        response_text = response.choices[0].message.content or ""
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as exc:
            append_llm_call(
                log_path=log_path,
                module_name=module_name,
                model=self.model,
                messages=messages,
                response_text=response_text,
                parsed_output=None,
                metadata={**(metadata or {}), "parse_error": str(exc)},
                duration_seconds=duration,
                usage=_extract_usage(response),
            )
            raise ValueError(f"LLM response was not valid JSON for module {module_name}") from exc

        append_llm_call(
            log_path=log_path,
            module_name=module_name,
            model=self.model,
            messages=messages,
            response_text=response_text,
            parsed_output=parsed,
            metadata=metadata,
            duration_seconds=duration,
            usage=_extract_usage(response),
        )
        return parsed


def _extract_usage(response) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


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
    if _model_supports_temperature(model):
        kwargs["temperature"] = temperature
    if extra_kwargs:
        kwargs.update(extra_kwargs)
    return kwargs


def _model_supports_temperature(model: str) -> bool:
    normalized = model.lower().strip()
    if normalized.startswith("gpt-5"):
        return False
    return True
