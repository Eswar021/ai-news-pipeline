"""Format-agnostic LLM runtime construction.

Resolve per-role LLM config (defaults + `llm_roles` overrides) into ready-to-call
runtimes (with optional content-filter fallback). A format passes its own role
tuple; the machinery is shared.
"""
from __future__ import annotations

from typing import Any

from .llm_client import make_llm


def resolved_llm_configs(config: dict[str, Any], roles: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    default_config = {
        "provider": config["provider"],
        "model": config["model"],
        "temperature": float(config["temperature"]),
        "base_url": config.get("base_url"),
        "provider_options": dict(config.get("provider_options") or {}),
        "structured_output": dict(config.get("structured_output") or {}),
        "llm_retry": dict(config.get("llm_retry") or {}),
        "content_filter_fallback": None,
    }
    overrides = dict(config.get("llm_roles") or {})
    resolved: dict[str, dict[str, Any]] = {}
    for role in roles:
        override = dict(overrides.get(role) or {})
        if not override:
            resolved[role] = {
                key: dict(value) if isinstance(value, dict) else value
                for key, value in default_config.items()
            }
            continue
        resolved[role] = {
            "provider": override["provider"],
            "model": override["model"],
            "temperature": float(override["temperature"]),
            "base_url": override.get("base_url"),
            "provider_options": dict(override.get("provider_options") or {}),
            "structured_output": dict(override.get("structured_output") or {}),
            "llm_retry": dict(override.get("llm_retry") or default_config["llm_retry"]),
            "content_filter_fallback": _resolved_content_filter_fallback(
                override.get("content_filter_fallback"),
                default_retry=default_config["llm_retry"],
            ),
        }
    return resolved


def _resolved_content_filter_fallback(raw_config: Any, *, default_retry: dict[str, Any]) -> dict[str, Any] | None:
    if not raw_config:
        return None
    fallback = dict(raw_config)
    return {
        "provider": fallback["provider"],
        "model": fallback["model"],
        "temperature": float(fallback["temperature"]),
        "base_url": fallback.get("base_url"),
        "provider_options": dict(fallback.get("provider_options") or {}),
        "structured_output": dict(fallback.get("structured_output") or {}),
        "llm_retry": dict(fallback.get("llm_retry") or default_retry),
    }


def build_llm_runtimes(config: dict[str, Any], roles: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    runtimes: dict[str, dict[str, Any]] = {}
    for role, role_config in resolved_llm_configs(config, roles).items():
        runtimes[role] = {
            "config": role_config,
            "llm": make_llm(
                provider=role_config["provider"],
                model=role_config["model"],
                temperature=float(role_config["temperature"]),
                base_url=role_config.get("base_url"),
                max_retries=0,
                provider_options=role_config.get("provider_options"),
            ),
        }
        fallback = role_config.get("content_filter_fallback")
        if fallback:
            runtimes[role]["content_filter_fallback"] = {
                "config": fallback,
                "llm": make_llm(
                    provider=fallback["provider"],
                    model=fallback["model"],
                    temperature=float(fallback["temperature"]),
                    base_url=fallback.get("base_url"),
                    max_retries=0,
                    provider_options=fallback.get("provider_options"),
                ),
            }
    return runtimes


def llm_route_summary(config: dict[str, Any], roles: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    return {
        role: {
            "provider": role_config["provider"],
            "model": role_config["model"],
            "structured_output": role_config["structured_output"],
        }
        for role, role_config in resolved_llm_configs(config, roles).items()
    }
