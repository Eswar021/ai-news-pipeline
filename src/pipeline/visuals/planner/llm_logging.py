from __future__ import annotations

import json
from typing import Any


def build_llm_call_log(
    *,
    module_name: str,
    provider: str,
    model: str,
    rendered_prompt: str,
    raw_response: Any,
    parsed_output: dict | None,
    metadata: dict | None,
    duration_seconds: float,
    parse_error: str = "",
) -> dict:
    log_metadata = dict(metadata or {})
    if parse_error:
        log_metadata["parse_error"] = parse_error
    return {
        "module_name": module_name,
        "provider": provider,
        "model": model,
        "messages": [{"role": "user", "content": rendered_prompt}],
        "response_text": raw_response_text(raw_response),
        "parsed_output": parsed_output,
        "metadata": log_metadata,
        "duration_seconds": round(duration_seconds, 3),
        "usage": extract_usage(raw_response),
    }


def raw_response_text(raw: Any) -> str:
    if raw is None:
        return ""
    content = getattr(raw, "content", "")
    if isinstance(content, str):
        return content
    if content:
        return json.dumps(content, ensure_ascii=False)
    tool_calls = getattr(raw, "tool_calls", None)
    if tool_calls:
        return json.dumps(tool_calls, ensure_ascii=False)
    return ""


def extract_usage(raw: Any) -> dict:
    if raw is None:
        return {}
    usage_metadata = getattr(raw, "usage_metadata", None)
    if isinstance(usage_metadata, dict) and usage_metadata:
        return {
            "prompt_tokens": usage_metadata.get("input_tokens"),
            "completion_tokens": usage_metadata.get("output_tokens"),
            "total_tokens": usage_metadata.get("total_tokens"),
        }
    response_metadata = getattr(raw, "response_metadata", None)
    if not isinstance(response_metadata, dict):
        return {}
    token_usage = response_metadata.get("token_usage") or response_metadata.get("usage") or {}
    if not isinstance(token_usage, dict):
        return {}
    return {
        "prompt_tokens": token_usage.get("prompt_tokens") or token_usage.get("input_tokens"),
        "completion_tokens": token_usage.get("completion_tokens") or token_usage.get("output_tokens"),
        "total_tokens": token_usage.get("total_tokens"),
    }

