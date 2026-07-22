from __future__ import annotations

import json
from typing import Any


def build_llm_call_log(
    *,
    model: str,
    prompt_summary: str,
    raw_response: Any,
    parsed_output: dict | None,
    metadata: dict,
    duration_seconds: float,
    parse_error: str = "",
    module_name: str = "media_candidate_verifier",
) -> dict:
    call_metadata = dict(metadata)
    if parse_error:
        call_metadata["parse_error"] = parse_error
    call_log = {
        "module_name": module_name,
        "provider": "openai",
        "model": model,
        "messages": [{"role": "user", "content": prompt_summary}],
        "response_text": _raw_response_text(raw_response),
        "parsed_output": parsed_output,
        "metadata": call_metadata,
        "duration_seconds": round(duration_seconds, 3),
        "usage": _extract_usage(raw_response),
    }
    return call_log


def _raw_response_text(raw: Any) -> str:
    if raw is None:
        return ""
    content = getattr(raw, "content", "")
    if isinstance(content, str):
        return content
    if content:
        return json.dumps(content, ensure_ascii=False)
    tool_calls = getattr(raw, "tool_calls", None)
    return json.dumps(tool_calls, ensure_ascii=False) if tool_calls else ""


def _extract_usage(raw: Any) -> dict:
    if raw is None:
        return {}
    usage = getattr(raw, "usage_metadata", None)
    if isinstance(usage, dict):
        return {
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
    metadata = getattr(raw, "response_metadata", None)
    token_usage = metadata.get("token_usage", {}) if isinstance(metadata, dict) else {}
    return {
        "prompt_tokens": token_usage.get("prompt_tokens"),
        "completion_tokens": token_usage.get("completion_tokens"),
        "total_tokens": token_usage.get("total_tokens"),
    }
