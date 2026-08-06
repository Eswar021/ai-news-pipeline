"""Format-agnostic LLM invocation for script generation.

The structured-output call, retry/backoff, content-filter fallback, and server
retry-delay parsing are shared by every script format. A format supplies its own
prompts + output models; this module runs the call and logs it.
"""
from __future__ import annotations

import re
import time
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError as PydanticValidationError

from .llm_logging import build_llm_call_log
from .utils import json_dumps


TASK_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        ("human", "{user_preamble}\n\nTask payload:\n{task_payload}"),
    ]
)


def invoke_runtime_chain(
    *,
    module_name: str,
    output_model,
    llm_runtime: dict[str, Any],
    prompt_bundle: dict[str, str],
    task_payload: str,
    metadata: dict[str, Any],
    llm_calls: list[dict[str, Any]],
):
    primary_config = llm_runtime["config"]
    fallback_runtime = llm_runtime.get("content_filter_fallback")
    primary_metadata = {
        **metadata,
        "route_attempt": "primary",
        "content_filter_fallback_configured": fallback_runtime is not None,
    }
    try:
        return _invoke_chain(
            module_name=module_name,
            output_model=output_model,
            llm=llm_runtime["llm"],
            prompt_bundle=prompt_bundle,
            task_payload=task_payload,
            script_cfg=primary_config,
            metadata=primary_metadata,
            llm_calls=llm_calls,
        )
    except Exception as exc:
        fallback_trigger = _fallback_trigger(exc)
        if fallback_runtime is None or fallback_trigger is None:
            raise

    fallback_config = fallback_runtime["config"]
    return _invoke_chain(
        module_name=module_name,
        output_model=output_model,
        llm=fallback_runtime["llm"],
        prompt_bundle=prompt_bundle,
        task_payload=task_payload,
        script_cfg=fallback_config,
        metadata={
            **metadata,
            "route_attempt": "content_filter_fallback",
            "fallback_trigger": fallback_trigger,
            "fallback_from_provider": primary_config.get("provider", ""),
            "fallback_from_model": primary_config.get("model", ""),
        },
        llm_calls=llm_calls,
    )


def _invoke_chain(
    *,
    module_name: str,
    output_model,
    llm,
    prompt_bundle: dict[str, str],
    task_payload: str,
    script_cfg: dict[str, Any],
    metadata: dict[str, Any],
    llm_calls: list[dict[str, Any]],
):
    structured_config = dict(script_cfg.get("structured_output") or {})
    structured_options = _structured_output_options(structured_config)
    task_payload = _task_payload_for_structured_output(
        task_payload,
        output_model=output_model,
        method=structured_options["method"],
    )
    structured_llm = llm.with_structured_output(output_model, **structured_options)
    chain = TASK_PROMPT | structured_llm
    prompt_inputs = {
        "system_prompt": prompt_bundle["system"],
        "user_preamble": prompt_bundle["user_preamble"],
        "task_payload": task_payload,
    }
    rendered_messages = [
        {
            "role": "system" if message.type == "system" else "user",
            "content": str(message.content),
        }
        for message in TASK_PROMPT.format_messages(**prompt_inputs)
    ]
    started = time.time()
    retry_config = script_cfg.get("llm_retry", {})
    retry_enabled = bool(retry_config.get("enabled", True))
    max_transient_attempts = int(retry_config.get("max_attempts", 5)) if retry_enabled else 1
    max_structured_attempts = (
        int(retry_config.get("max_structured_output_attempts", 2)) if retry_enabled else 1
    )
    retry_errors: list[dict[str, Any]] = []
    attempt_count = 0
    transient_failure_count = 0
    structured_failure_count = 0
    while True:
        attempt_count += 1
        attempt_started = time.time()
        try:
            result = chain.invoke(prompt_inputs)
        except Exception as exc:
            status_code = _exception_status_code(exc)
            structured_failure = _is_structured_output_error(exc)
            retryable = _is_retryable_llm_error(exc, status_code=status_code)
            retry_entry = {
                "attempt": attempt_count,
                "status_code": status_code,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            if structured_failure:
                structured_failure_count += 1
                can_retry = retry_enabled and structured_failure_count < max_structured_attempts
            else:
                transient_failure_count += 1
                can_retry = retry_enabled and retryable and transient_failure_count < max_transient_attempts
            if not can_retry:
                retry_errors.append(retry_entry)
                call_metadata = {
                    **metadata,
                    "attempt_count": attempt_count,
                    "retry_count": max(0, attempt_count - 1),
                    "retry_errors": retry_errors,
                }
                llm_calls.append(
                        build_llm_call_log(
                        module_name=module_name,
                            provider=str(script_cfg.get("provider", "")),
                            model=str(script_cfg.get("model", "")),
                            messages=rendered_messages,
                        raw_response=None,
                        parsed_output=None,
                        metadata=call_metadata,
                        duration_seconds=time.time() - started,
                        parse_error=str(exc),
                    )
                )
                raise
            delay_seconds = _retry_delay_seconds(
                exc,
                attempt=attempt_count,
                retry_config=retry_config,
            )
            retry_entry["delay_seconds"] = round(delay_seconds, 3)
            retry_errors.append(retry_entry)
            time.sleep(delay_seconds)
            continue

        raw = result.get("raw") if isinstance(result, dict) else None
        parsed = result.get("parsed") if isinstance(result, dict) else result
        parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
        parsed_model = None
        if parsing_error is None and parsed is not None:
            try:
                parsed_model = parsed if isinstance(parsed, output_model) else output_model.model_validate(parsed)
            except PydanticValidationError as exc:
                parsing_error = exc

        call_metadata = {
            **metadata,
            "attempt_count": attempt_count,
            "retry_count": max(0, attempt_count - 1),
        }
        if retry_errors:
            call_metadata["retry_errors"] = list(retry_errors)

        if parsing_error is not None or parsed_model is None:
            structured_failure_count += 1
            parse_error_text = str(parsing_error or "missing parsed output")
            llm_calls.append(
                build_llm_call_log(
                    module_name=module_name,
                    provider=str(script_cfg.get("provider", "")),
                    model=str(script_cfg.get("model", "")),
                    messages=rendered_messages,
                    raw_response=raw,
                    parsed_output=None,
                    metadata=call_metadata,
                    duration_seconds=time.time() - attempt_started,
                    parse_error=parse_error_text,
                )
            )
            if retry_enabled and structured_failure_count < max_structured_attempts:
                retry_error = ValueError(parse_error_text)
                delay_seconds = _retry_delay_seconds(
                    retry_error,
                    attempt=structured_failure_count,
                    retry_config=retry_config,
                )
                retry_errors.append(
                    {
                        "attempt": attempt_count,
                        "status_code": None,
                        "error_type": "StructuredOutputError",
                        "error": parse_error_text,
                        "delay_seconds": round(delay_seconds, 3),
                    }
                )
                time.sleep(delay_seconds)
                continue
            error = ValueError(f"LLM structured output failed for {module_name}: {parse_error_text}")
            if isinstance(parsing_error, BaseException):
                raise error from parsing_error
            raise error

        parsed_output = parsed_model.model_dump(mode="json")
        llm_calls.append(
            build_llm_call_log(
                module_name=module_name,
                provider=str(script_cfg.get("provider", "")),
                model=str(script_cfg.get("model", "")),
                messages=rendered_messages,
                raw_response=raw,
                parsed_output=parsed_output,
                metadata=call_metadata,
                duration_seconds=time.time() - attempt_started,
            )
        )
        return parsed_model


def _structured_output_options(structured_config: dict[str, Any]) -> dict[str, Any]:
    method = str(structured_config.get("method") or "json_schema")
    options: dict[str, Any] = {
        "include_raw": True,
        "method": method,
    }
    if method != "json_mode":
        options["strict"] = bool(structured_config.get("strict", True))
    return options


def _task_payload_for_structured_output(
    task_payload: str,
    *,
    output_model,
    method: str,
) -> str:
    if method != "json_mode":
        return task_payload
    schema = json_dumps(output_model.model_json_schema())
    return (
        f"{task_payload}\n\n"
        "Return only one JSON object matching the following JSON Schema exactly. "
        "Use only enum values defined by the schema, use null only where allowed, "
        "and do not wrap the object in Markdown.\n"
        f"JSON Schema:\n{schema}"
    )


def _exception_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _is_retryable_llm_error(exc: Exception, *, status_code: int | None) -> bool:
    if status_code in {429, 500, 502, 503, 504}:
        return True
    if _is_transient_request_error(exc, status_code=status_code):
        return True
    return type(exc).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
        "ServiceUnavailableError",
    }


def _is_transient_request_error(exc: Exception, *, status_code: int | None) -> bool:
    """A 400 whose message claims the provider could not parse a well-formed body.

    DeepSeek intermittently returns ``400 Failed to parse the request body as JSON``
    for requests that are provably valid JSON — a server-side hiccup, not a real
    client error (we reproduced the exact same request succeeding on retry). Treat
    it as transient so the retry loop (and the fallback) can recover instead of
    killing a run after ~17 minutes of upstream work.
    """
    if status_code != 400:
        return False
    text = str(exc).casefold()
    return "parse the request body" in text or "request body as json" in text


def _is_content_filter_error(exc: Exception) -> bool:
    status_code = _exception_status_code(exc)
    text = str(exc).casefold().replace("_", " ")
    markers = ("content filter", "high risk", "highrisk")
    return status_code in {400, 403} and any(marker in text for marker in markers)


def _fallback_trigger(exc: Exception) -> str | None:
    """Which fallback (if any) a primary-route failure should route to.

    Both the content filter and a persistent transient body-parse 400 mean the
    primary provider can't complete this call; the configured fallback (gpt-4o-mini)
    finishes it rather than failing the run.
    """
    if _is_content_filter_error(exc):
        return "content_filter"
    if _is_transient_request_error(exc, status_code=_exception_status_code(exc)):
        return "provider_request_error"
    return None


def _is_structured_output_error(exc: Exception) -> bool:
    return isinstance(exc, PydanticValidationError) or type(exc).__name__ in {
        "OutputParserException",
        "ValidationError",
    }


def _retry_delay_seconds(
    exc: Exception,
    *,
    attempt: int,
    retry_config: dict[str, Any],
) -> float:
    initial_delay = float(retry_config.get("initial_delay_seconds", 1.0))
    maximum_delay = float(retry_config.get("max_delay_seconds", 30.0))
    exponential_delay = initial_delay * (2 ** max(0, attempt - 1))
    server_delay = _server_retry_delay_seconds(exc)
    if server_delay is not None:
        exponential_delay = max(exponential_delay, server_delay + 0.25)
    return min(maximum_delay, exponential_delay)


def _server_retry_delay_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    for key, milliseconds in (
        ("retry-after-ms", True),
        ("retry-after", False),
        ("x-ratelimit-reset-tokens", False),
        ("x-ratelimit-reset-requests", False),
    ):
        value = headers.get(key) if hasattr(headers, "get") else None
        parsed = _parse_retry_delay(value, milliseconds=milliseconds)
        if parsed is not None:
            return parsed
    match = re.search(
        r"try again in\s+([0-9]+(?:\.[0-9]+)?)\s*(ms|milliseconds?|s|seconds?)",
        str(exc),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1))
    return value / 1000 if match.group(2).lower().startswith("m") else value


def _parse_retry_delay(value: Any, *, milliseconds: bool) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if milliseconds:
        try:
            return float(text) / 1000
        except ValueError:
            return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(ms|s)?", text)
    if not match:
        return None
    delay = float(match.group(1))
    return delay / 1000 if match.group(2) == "ms" else delay
