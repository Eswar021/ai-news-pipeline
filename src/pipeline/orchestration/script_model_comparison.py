from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from src.pipeline.content.script_generation.formats.roundup import run as run_script_generation
from src.pipeline.config import ConfigRepository


class VariantPricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_cache_miss: float = Field(ge=0)
    input_cache_hit: float = Field(ge=0)
    output: float = Field(ge=0)


class ComparisonVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    config: dict[str, Any]
    pricing_per_million_tokens: VariantPricing | None = None
    pricing_by_route: dict[str, VariantPricing] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def id_must_be_safe(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in cleaned):
            raise ValueError("variant id must contain only letters, digits, underscores, and hyphens")
        return cleaned

    @model_validator(mode="after")
    def pricing_must_cover_single_or_mixed_route(self) -> "ComparisonVariant":
        if self.pricing_per_million_tokens is None and not self.pricing_by_route:
            raise ValueError("comparison variant requires pricing_per_million_tokens or pricing_by_route")
        return self


def run_comparison(
    *,
    source_input: dict[str, Any],
    variants: list[ComparisonVariant],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_run_id = str((source_input.get("run") or {}).get("run_id") or "").strip()
    if not source_run_id:
        raise ValueError("source script input is missing run.run_id")
    if not variants:
        raise ValueError("comparison requires at least one model variant")

    summaries: list[dict[str, Any]] = []
    for variant in variants:
        print(
            f"[script_model_comparison] START variant={variant.id} "
            f"provider={variant.config.get('provider')} model={variant.config.get('model')}",
            flush=True,
        )
        variant_dir = output_dir / variant.id
        variant_dir.mkdir(parents=True, exist_ok=True)
        variant_input = deepcopy(source_input)
        variant_input["config"].update(deepcopy(variant.config))
        _write_json(variant_dir / "script_generation_input.json", variant_input)

        started = time.monotonic()
        try:
            result = run_script_generation(variant_input)
            error = ""
        except Exception as exc:
            result = {
                "status": "failed",
                "data": {"run_id": source_run_id},
                "summary": {"failure_reason": f"{type(exc).__name__}: {exc}"},
                "handoff": {"ready_for_metadata_creation": False},
                "llm_calls": [],
            }
            error = str(exc)
        elapsed = time.monotonic() - started

        _write_json(variant_dir / "script_generation_result.json", result)
        _write_jsonl(variant_dir / "llm_calls.jsonl", result.get("llm_calls") or [])
        script_package = (result.get("data") or {}).get("script_package") or {}
        full_script = str(script_package.get("full_script") or "").strip()
        if full_script:
            (variant_dir / "full_script.txt").write_text(full_script, encoding="utf-8")

        usage = _aggregate_usage(result.get("llm_calls") or [])
        usage_by_route = _aggregate_usage_by_route(result.get("llm_calls") or [])
        estimated_cost_by_route, unpriced_routes = _estimate_variant_costs(
            usage=usage,
            usage_by_route=usage_by_route,
            variant=variant,
        )
        estimated_cost = sum(estimated_cost_by_route.values())
        summary = {
            "variant_id": variant.id,
            "provider": variant.config.get("provider"),
            "model": variant.config.get("model"),
            "status": result.get("status", "failed"),
            "failure_reason": (result.get("summary") or {}).get("failure_reason") or error,
            "duration_seconds": round(elapsed, 3),
            "word_count": len(full_script.split()),
            "section_count": int((result.get("summary") or {}).get("section_count") or 0),
            "llm_call_count": len(result.get("llm_calls") or []),
            "usage": usage,
            "usage_by_route": usage_by_route,
            "estimated_cost_by_route_usd": {
                route: round(cost, 6)
                for route, cost in estimated_cost_by_route.items()
            },
            "unpriced_routes": unpriced_routes,
            "estimated_cost_usd": round(estimated_cost, 6),
            "result_path": str((variant_dir / "script_generation_result.json").resolve()),
            "script_path": str((variant_dir / "full_script.txt").resolve()) if full_script else "",
        }
        _write_json(variant_dir / "comparison_metrics.json", summary)
        summaries.append(summary)
        print(
            f"[script_model_comparison] END variant={variant.id} "
            f"status={summary['status']} duration={summary['duration_seconds']}s "
            f"calls={summary['llm_call_count']} cost=${summary['estimated_cost_usd']:.4f}",
            flush=True,
        )

    comparison = {
        "status": "ok" if all(item["status"] == "ok" for item in summaries) else "partial",
        "source_run_id": source_run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir.resolve()),
        "variants": summaries,
        "total_estimated_cost_usd": round(sum(item["estimated_cost_usd"] for item in summaries), 6),
    }
    _write_json(output_dir / "comparison_summary.json", comparison)
    return comparison


def _aggregate_usage(calls: list[dict[str, Any]]) -> dict[str, int]:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cache_read_tokens = 0
    reasoning_tokens = 0
    for call in calls:
        usage = call.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        input_details = usage.get("input_token_details") or {}
        output_details = usage.get("output_token_details") or {}
        cache_read_tokens += int(
            input_details.get("cache_read")
            or input_details.get("cached_tokens")
            or 0
        )
        reasoning_tokens += int(output_details.get("reasoning") or output_details.get("reasoning_tokens") or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": cache_read_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


def _aggregate_usage_by_route(calls: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    routes: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        route = f"{str(call.get('provider') or '').strip()}/{str(call.get('model') or '').strip()}"
        routes.setdefault(route, []).append(call)
    return {route: _aggregate_usage(route_calls) for route, route_calls in sorted(routes.items())}


def _estimate_variant_costs(
    *,
    usage: dict[str, int],
    usage_by_route: dict[str, dict[str, int]],
    variant: ComparisonVariant,
) -> tuple[dict[str, float], list[str]]:
    if variant.pricing_by_route:
        costs = {}
        unpriced = []
        for route, route_usage in usage_by_route.items():
            pricing = variant.pricing_by_route.get(route)
            if pricing is None:
                unpriced.append(route)
                continue
            costs[route] = _estimate_cost(route_usage, pricing)
        return costs, unpriced
    if variant.pricing_per_million_tokens is None:
        return {}, sorted(usage_by_route)
    return {"variant_default": _estimate_cost(usage, variant.pricing_per_million_tokens)}, []


def _estimate_cost(usage: dict[str, int], pricing: VariantPricing) -> float:
    prompt_tokens = usage["prompt_tokens"]
    cache_read_tokens = min(prompt_tokens, usage["cache_read_tokens"])
    cache_miss_tokens = prompt_tokens - cache_read_tokens
    return (
        cache_miss_tokens * pricing.input_cache_miss
        + cache_read_tokens * pricing.input_cache_hit
        + usage["completion_tokens"] * pricing.output
    ) / 1_000_000


def _load_variants(config_path: Path, selected_ids: list[str]) -> list[ComparisonVariant]:
    experiment = ConfigRepository(config_path).experiment("script_model_comparison").value
    raw_variants = experiment.get("variants")
    variants = [ComparisonVariant.model_validate(item) for item in (raw_variants or [])]
    if not selected_ids:
        return variants
    selected = set(selected_ids)
    unknown = selected - {variant.id for variant in variants}
    if unknown:
        raise ValueError(f"Unknown comparison variant(s): {sorted(unknown)}")
    return [variant for variant in variants if variant.id in selected]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare script models against one frozen input packet.")
    parser.add_argument("--input", required=True, help="Existing script_generation_input.json")
    parser.add_argument("--output-dir", required=True, help="Isolated output/labs directory")
    parser.add_argument("--pipeline-config", default="src/pipeline/config/workbench.yaml")
    parser.add_argument("--variant", action="append", default=[], help="Variant id to run; repeat as needed")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env", override=False)
    source_input = json.loads((root / args.input).resolve().read_text(encoding="utf-8"))
    config_path = (root / args.pipeline_config).resolve()
    output_dir = (root / args.output_dir).resolve()
    variants = _load_variants(config_path, args.variant)
    comparison = run_comparison(source_input=source_input, variants=variants, output_dir=output_dir)
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0 if comparison["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
