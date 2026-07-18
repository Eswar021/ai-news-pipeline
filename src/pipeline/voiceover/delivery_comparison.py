from __future__ import annotations

import argparse
import csv
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import time
from typing import Any, Callable

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml

from .app import run as run_voiceover
from .contract import VoiceoverConfig


class DeliveryVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    config: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def id_must_be_safe(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in cleaned
        ):
            raise ValueError("delivery variant id must contain only letters, digits, underscores, and hyphens")
        return cleaned

    @field_validator("label", "description")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("delivery variant label and description must not be empty")
        return cleaned


class DeliveryComparisonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_type: str = "intro"
    beat_count: int = Field(default=1, ge=1, le=10)
    default_variant_ids: list[str] = Field(default_factory=list)
    provider_request_intervals_seconds: dict[str, float] = Field(default_factory=dict)
    max_projected_cost_usd: float = Field(default=2.0, ge=0)
    variants: list[DeliveryVariant]
    matrices: list["DeliveryMatrix"] = Field(default_factory=list)

    @field_validator("section_type")
    @classmethod
    def section_type_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("delivery comparison section_type must not be empty")
        return cleaned

    @field_validator("variants")
    @classmethod
    def variant_ids_must_be_unique(cls, value: list[DeliveryVariant]) -> list[DeliveryVariant]:
        identifiers = [variant.id for variant in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("delivery comparison variant ids must be unique")
        return value

    @field_validator("default_variant_ids")
    @classmethod
    def default_variant_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("delivery comparison default_variant_ids must be unique")
        return cleaned

    @field_validator("provider_request_intervals_seconds")
    @classmethod
    def request_intervals_must_be_non_negative(cls, value: dict[str, float]) -> dict[str, float]:
        cleaned: dict[str, float] = {}
        for provider, seconds in value.items():
            provider_name = provider.strip()
            if not provider_name:
                raise ValueError("delivery comparison request interval provider names must not be empty")
            if seconds < 0 or seconds > 300:
                raise ValueError("delivery comparison request intervals must be between 0 and 300 seconds")
            cleaned[provider_name] = float(seconds)
        return cleaned

    @model_validator(mode="after")
    def variants_or_matrices_are_required(self) -> "DeliveryComparisonConfig":
        if not self.variants and not self.matrices:
            raise ValueError("delivery comparison requires at least one variant or matrix")
        return self


class DeliveryMatrixVoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    voice: str
    label: str
    character: str

    @field_validator("id")
    @classmethod
    def id_must_be_safe(cls, value: str) -> str:
        return _safe_id(value, "matrix voice id")

    @field_validator("voice", "label", "character")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("matrix voice fields must not be empty")
        return cleaned


class DeliveryMatrixDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    speed: float = Field(gt=0, le=4)
    instructions: str
    transcript_prefix: str = ""

    @field_validator("id")
    @classmethod
    def id_must_be_safe(cls, value: str) -> str:
        return _safe_id(value, "matrix direction id")

    @field_validator("label", "description", "instructions")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("matrix direction fields must not be empty")
        return cleaned


class DeliveryMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    provider: str
    model: str
    style: str = "general_youtube"
    provider_config: dict[str, Any] = Field(default_factory=dict)
    pricing: "DeliveryMatrixPricing | None" = None
    voices: list[DeliveryMatrixVoice]
    directions: list[DeliveryMatrixDirection]

    @field_validator("id")
    @classmethod
    def id_must_be_safe(cls, value: str) -> str:
        return _safe_id(value, "delivery matrix id")

    @field_validator("label", "provider", "model", "style")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("delivery matrix identity fields must not be empty")
        return cleaned

    @field_validator("voices", "directions")
    @classmethod
    def matrix_axes_must_not_be_empty(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("delivery matrix voices and directions must not be empty")
        identifiers = [item.id for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("delivery matrix axis ids must be unique")
        return value


class DeliveryMatrixPricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_input_usd_per_million_tokens: float = Field(ge=0)
    audio_output_usd_per_million_tokens: float = Field(ge=0)
    audio_tokens_per_second: float = Field(default=25.0, gt=0)
    projected_audio_seconds: float = Field(default=20.0, gt=0)


def extract_sample(
    script_result: dict[str, Any],
    *,
    section_type: str,
    beat_count: int,
) -> dict[str, Any]:
    package = ((script_result.get("data") or {}).get("script_package") or {})
    sections = package.get("sections") or []
    section = next(
        (item for item in sections if str(item.get("section_type") or "") == section_type),
        None,
    )
    if section is None:
        raise ValueError(f"Script package has no section_type={section_type!r}")

    beats = list(section.get("beats") or [])[:beat_count]
    beat_texts = [str(beat.get("narration_text") or "").strip() for beat in beats]
    text = " ".join(item for item in beat_texts if item).strip()
    if not text:
        text = str(section.get("narration_text") or "").strip()
    if not text:
        raise ValueError(f"Script section {section.get('section_id', section_type)!r} has no narration text")

    return {
        "text": text,
        "section_id": str(section.get("section_id") or ""),
        "section_type": section_type,
        "beat_ids": [str(beat.get("beat_id") or "") for beat in beats],
        "word_count": len(text.split()),
    }


def run_comparison(
    *,
    script_result: dict[str, Any],
    script_source: str,
    base_voiceover_config: dict[str, Any],
    comparison_config: DeliveryComparisonConfig,
    output_dir: Path,
    selected_variant_ids: list[str] | None = None,
    selected_matrix_ids: list[str] | None = None,
    resume: bool = False,
    voiceover_runner: Callable[[dict[str, Any]], dict[str, Any]] = run_voiceover,
) -> dict[str, Any]:
    sample = extract_sample(
        script_result,
        section_type=comparison_config.section_type,
        beat_count=comparison_config.beat_count,
    )
    source_run_id = str((script_result.get("data") or {}).get("run_id") or "voice_demo").strip()
    variants = _resolve_variants(
        comparison_config,
        selected_variant_ids=selected_variant_ids or [],
        selected_matrix_ids=selected_matrix_ids or [],
    )
    variants = [_with_projected_cost(variant, sample) for variant in variants]
    projected_cost_usd = sum(
        float(variant.metadata.get("projected_cost_usd") or 0.0) for variant in variants
    )
    if projected_cost_usd > comparison_config.max_projected_cost_usd:
        raise ValueError(
            "Voiceover comparison projected cost "
            f"${projected_cost_usd:.4f} exceeds configured cap "
            f"${comparison_config.max_projected_cost_usd:.4f}"
        )

    previous_summaries = _load_reusable_summaries(output_dir) if resume else {}
    output_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = output_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "sample_context.json", {**sample, "script_source": script_source})

    summaries: list[dict[str, Any]] = []
    provider_started_at: dict[str, float] = {}
    stopped_reason = ""
    for order, variant in enumerate(variants, start=1):
        reusable = previous_summaries.get(variant.id)
        if reusable is not None:
            duration_seconds = float(reusable.get("duration_seconds") or 0.0)
            reused_summary = {
                **reusable,
                "order": order,
                "actual_wpm": round(
                    sample["word_count"] / duration_seconds * 60 if duration_seconds > 0 else 0.0,
                    1,
                ),
                "estimated_cost_usd": round(
                    _estimated_actual_cost(variant, duration_seconds),
                    6,
                ),
                **variant.metadata,
            }
            summaries.append(reused_summary)
            print(
                f"[voiceover_delivery_comparison] REUSE variant={variant.id} "
                f"audio={reused_summary['audio_path']}",
                flush=True,
            )
            continue

        variant_dir = output_dir / "variants" / variant.id
        effective_config = _deep_merge(base_voiceover_config, variant.config)
        effective_config.update(
            {
                "output_dir": str(variant_dir.resolve()),
                "force": True,
                "keep_chunks": True,
            }
        )
        effective_config["chunking"] = {
            "chunk_max_chars": 4096,
            "max_sentences_per_chunk": 20,
            "chunk_pause_seconds": 0.0,
            "paragraph_pause_seconds": 0.0,
        }
        effective_config["captions"] = {
            **dict(effective_config.get("captions") or {}),
            "enabled": False,
        }
        effective_config = VoiceoverConfig.model_validate(effective_config).model_dump(mode="json")
        transcript_prefix = str(variant.metadata.get("transcript_prefix") or "").strip()
        variant_text = " ".join(part for part in (transcript_prefix, sample["text"]) if part).strip()

        request = {
            "run": {
                "run_id": f"{source_run_id}_delivery_demo_{variant.id}",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "config": effective_config,
            "input": {
                "script_text": variant_text,
                "script_source": script_source,
            },
        }
        _write_json(variant_dir / "voiceover_input.json", request)

        provider = str(effective_config.get("provider") or "")
        _wait_for_provider_slot(
            provider=provider,
            minimum_interval_seconds=float(
                comparison_config.provider_request_intervals_seconds.get(provider, 0.0)
            ),
            provider_started_at=provider_started_at,
        )
        print(
            f"[voiceover_delivery_comparison] START variant={variant.id} "
            f"voice={_variant_voice(effective_config)} speed={effective_config.get('speed')}",
            flush=True,
        )
        provider_started_at[provider] = time.monotonic()
        try:
            result = voiceover_runner(request)
            status = str(result.get("status") or "failed")
            failure_reason = str((result.get("summary") or {}).get("failure_reason") or "")
        except Exception as exc:
            result = {
                "status": "failed",
                "data": {"run_id": request["run"]["run_id"]},
                "summary": {"failure_reason": f"{type(exc).__name__}: {exc}"},
                "handoff": {"ready_for_video_assembly": False},
            }
            status = "failed"
            failure_reason = str(exc)
        _write_json(variant_dir / "voiceover_result.json", result)

        source_audio = variant_dir / "audio" / "full_voiceover.wav"
        sample_audio = samples_dir / f"{order:02d}_{variant.id}.wav"
        if status == "ok" and source_audio.exists():
            shutil.copy2(source_audio, sample_audio)
            audio_path = str(sample_audio.resolve())
        else:
            audio_path = ""
            if status == "ok":
                status = "failed"
                failure_reason = "Voiceover completed without creating audio/full_voiceover.wav"

        duration_seconds = float((result.get("summary") or {}).get("duration_seconds") or 0.0)
        actual_wpm = sample["word_count"] / duration_seconds * 60 if duration_seconds > 0 else 0.0
        estimated_cost_usd = _estimated_actual_cost(variant, duration_seconds)
        summary = {
            "order": order,
            "variant_id": variant.id,
            "label": variant.label,
            "description": variant.description,
            "status": status,
            "provider": effective_config.get("provider"),
            "model": _variant_model(effective_config),
            "voice": _variant_voice(effective_config),
            "speed": effective_config.get("speed"),
            "instructions": _variant_instructions(effective_config),
            "transcript_prefix": transcript_prefix,
            "duration_seconds": duration_seconds,
            "actual_wpm": round(actual_wpm, 1),
            "estimated_cost_usd": round(estimated_cost_usd, 6),
            "audio_path": audio_path,
            "failure_reason": failure_reason,
            **variant.metadata,
        }
        summaries.append(summary)
        print(
            f"[voiceover_delivery_comparison] END variant={variant.id} "
            f"status={status} duration={summary['duration_seconds']:.2f}s",
            flush=True,
        )
        _write_comparison_outputs(
            output_dir=output_dir,
            source_run_id=source_run_id,
            sample=sample,
            requested_variant_count=len(variants),
            projected_cost_usd=projected_cost_usd,
            summaries=summaries,
            stopped_reason=stopped_reason,
            checkpoint=True,
        )
        if _is_quota_failure(failure_reason):
            stopped_reason = f"Stopped after provider quota response from variant {variant.id}: {failure_reason}"
            print(f"[voiceover_delivery_comparison] STOP {stopped_reason}", flush=True)
            break

    return _write_comparison_outputs(
        output_dir=output_dir,
        source_run_id=source_run_id,
        sample=sample,
        requested_variant_count=len(variants),
        projected_cost_usd=projected_cost_usd,
        summaries=summaries,
        stopped_reason=stopped_reason,
        checkpoint=False,
    )


def _load_reusable_summaries(output_dir: Path) -> dict[str, dict[str, Any]]:
    manifest_path = output_dir / "comparison_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    reusable: dict[str, dict[str, Any]] = {}
    for item in manifest.get("variants") or []:
        audio_path = Path(str(item.get("audio_path") or ""))
        if item.get("status") == "ok" and audio_path.is_file() and audio_path.stat().st_size > 44:
            reusable[str(item.get("variant_id") or "")] = dict(item)
    return reusable


def _resolve_variants(
    config: DeliveryComparisonConfig,
    *,
    selected_variant_ids: list[str],
    selected_matrix_ids: list[str],
) -> list[DeliveryVariant]:
    matrix_by_id = {matrix.id: matrix for matrix in config.matrices}
    unknown_matrices = set(selected_matrix_ids) - set(matrix_by_id)
    if unknown_matrices:
        raise ValueError(f"Unknown voiceover delivery matrix id(s): {sorted(unknown_matrices)}")

    all_matrix_variants = [
        variant
        for matrix in config.matrices
        for variant in _expand_matrix(matrix)
    ]
    all_variants = [*config.variants, *all_matrix_variants]
    selected: list[DeliveryVariant] = []
    if selected_variant_ids:
        selected.extend(_selected_variants(all_variants, selected_variant_ids))
    if selected_matrix_ids:
        for matrix_id in selected_matrix_ids:
            selected.extend(_expand_matrix(matrix_by_id[matrix_id]))
    if not selected:
        selected.extend(_selected_variants(config.variants, config.default_variant_ids))
    return _dedupe_variants(selected)


def _expand_matrix(matrix: DeliveryMatrix) -> list[DeliveryVariant]:
    variants: list[DeliveryVariant] = []
    for voice in matrix.voices:
        for direction in matrix.directions:
            provider_settings = _deep_merge(
                matrix.provider_config,
                {
                    "model": matrix.model,
                    "voice": voice.voice,
                    "instructions": direction.instructions,
                },
            )
            variants.append(
                DeliveryVariant(
                    id=f"{matrix.id}_{voice.id}_{direction.id}",
                    label=f"{voice.label} - {direction.label}",
                    description=f"{voice.character} / {direction.description}",
                    config={
                        "provider": matrix.provider,
                        "style": matrix.style,
                        "speed": direction.speed,
                        matrix.provider: provider_settings,
                    },
                    metadata={
                        "matrix_id": matrix.id,
                        "matrix_label": matrix.label,
                        "voice_character": voice.character,
                        "delivery_id": direction.id,
                        "delivery_label": direction.label,
                        "transcript_prefix": direction.transcript_prefix,
                        "pricing": matrix.pricing.model_dump(mode="json") if matrix.pricing else {},
                    },
                )
            )
    return variants


def _dedupe_variants(variants: list[DeliveryVariant]) -> list[DeliveryVariant]:
    unique: list[DeliveryVariant] = []
    seen: set[str] = set()
    for variant in variants:
        if variant.id not in seen:
            unique.append(variant)
            seen.add(variant.id)
    return unique


def _selected_variants(
    variants: list[DeliveryVariant],
    selected_ids: list[str],
) -> list[DeliveryVariant]:
    if not selected_ids:
        return variants
    selected = set(selected_ids)
    unknown = selected - {variant.id for variant in variants}
    if unknown:
        raise ValueError(f"Unknown voiceover delivery comparison variant(s): {sorted(unknown)}")
    return [variant for variant in variants if variant.id in selected]


def _safe_id(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in cleaned
    ):
        raise ValueError(f"{label} must contain only letters, digits, underscores, and hyphens")
    return cleaned


def _wait_for_provider_slot(
    *,
    provider: str,
    minimum_interval_seconds: float,
    provider_started_at: dict[str, float],
) -> None:
    if minimum_interval_seconds <= 0 or provider not in provider_started_at:
        return
    elapsed = time.monotonic() - provider_started_at[provider]
    wait_seconds = max(0.0, minimum_interval_seconds - elapsed)
    if wait_seconds > 0:
        print(
            f"[voiceover_delivery_comparison] WAIT provider={provider} seconds={wait_seconds:.1f}",
            flush=True,
        )
        time.sleep(wait_seconds)


def _is_quota_failure(failure_reason: str) -> bool:
    lowered = failure_reason.lower()
    return any(marker in lowered for marker in ("resource_exhausted", "rate limit", "quota", "429"))


def _with_projected_cost(variant: DeliveryVariant, sample: dict[str, Any]) -> DeliveryVariant:
    metadata = dict(variant.metadata)
    pricing = dict(metadata.get("pricing") or {})
    if not pricing:
        return variant
    instructions = str(_provider_block(variant.config).get("instructions") or "")
    transcript_prefix = str(metadata.get("transcript_prefix") or "")
    estimated_text_tokens = max(
        1,
        math.ceil((len(instructions) + len(transcript_prefix) + len(str(sample.get("text") or ""))) / 4),
    )
    input_cost = (
        estimated_text_tokens
        * float(pricing["text_input_usd_per_million_tokens"])
        / 1_000_000
    )
    audio_cost = (
        float(pricing["projected_audio_seconds"])
        * float(pricing["audio_tokens_per_second"])
        * float(pricing["audio_output_usd_per_million_tokens"])
        / 1_000_000
    )
    metadata.update(
        {
            "projected_input_tokens": estimated_text_tokens,
            "projected_cost_usd": round(input_cost + audio_cost, 6),
        }
    )
    return variant.model_copy(update={"metadata": metadata})


def _estimated_actual_cost(variant: DeliveryVariant, duration_seconds: float) -> float:
    pricing = dict(variant.metadata.get("pricing") or {})
    if not pricing:
        return 0.0
    input_cost = (
        float(variant.metadata.get("projected_input_tokens") or 0)
        * float(pricing["text_input_usd_per_million_tokens"])
        / 1_000_000
    )
    audio_cost = (
        duration_seconds
        * float(pricing["audio_tokens_per_second"])
        * float(pricing["audio_output_usd_per_million_tokens"])
        / 1_000_000
    )
    return input_cost + audio_cost


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _provider_block(config: dict[str, Any]) -> dict[str, Any]:
    return dict(config.get(str(config.get("provider") or "")) or {})


def _variant_model(config: dict[str, Any]) -> str:
    return str(_provider_block(config).get("model") or "")


def _variant_voice(config: dict[str, Any]) -> str:
    return str(_provider_block(config).get("voice") or config.get("voice") or "")


def _variant_instructions(config: dict[str, Any]) -> str:
    return str(_provider_block(config).get("instructions") or "")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_summary_markdown(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Voiceover Delivery Comparison",
        "",
        f"Sample: {comparison['sample']['word_count']} words from `{comparison['sample']['section_id']}`",
        "",
        f"Projected maximum cost: `${float(comparison.get('projected_cost_usd') or 0.0):.4f}`",
        f"Estimated completed cost: `${float(comparison.get('estimated_cost_usd') or 0.0):.4f}`",
        "",
        "| # | Sample | Model | Voice | Character | Delivery | Target | Measured | Duration | Est. cost | Status |",
        "|---:|---|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in comparison["variants"]:
        audio_path = str(item.get("audio_path") or "")
        sample_link = f"[{item['label']}](samples/{Path(audio_path).name})" if audio_path else item["label"]
        lines.append(
            "| {order} | {sample} | {model} | {voice} | {character} | {delivery} | {speed:.2f}x | {wpm:.0f} WPM | {duration:.2f}s | ${cost:.4f} | {status} |".format(
                order=item["order"],
                sample=sample_link,
                model=item.get("model") or "",
                voice=item.get("voice") or "",
                character=item.get("voice_character") or "",
                delivery=item.get("delivery_label") or item.get("description") or "",
                speed=float(item.get("speed") or 0.0),
                wpm=float(item.get("actual_wpm") or 0.0),
                duration=float(item.get("duration_seconds") or 0.0),
                cost=float(item.get("estimated_cost_usd") or 0.0),
                status=item.get("status") or "",
            )
        )
    if comparison.get("stopped_reason"):
        stopped_reason = str(comparison["stopped_reason"])
        if _is_quota_failure(stopped_reason):
            stopped_reason = "Provider quota reached; see comparison_manifest.json for the complete API response."
        lines.extend(["", f"Stopped early: {stopped_reason}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_summary_csv(path: Path, summaries: list[dict[str, Any]]) -> None:
    fields = [
        "order",
        "variant_id",
        "label",
        "provider",
        "model",
        "voice",
        "voice_character",
        "delivery_id",
        "delivery_label",
        "speed",
        "actual_wpm",
        "duration_seconds",
        "projected_cost_usd",
        "estimated_cost_usd",
        "status",
        "audio_path",
        "instructions",
        "transcript_prefix",
        "failure_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)


def _write_comparison_outputs(
    *,
    output_dir: Path,
    source_run_id: str,
    sample: dict[str, Any],
    requested_variant_count: int,
    projected_cost_usd: float,
    summaries: list[dict[str, Any]],
    stopped_reason: str,
    checkpoint: bool,
) -> dict[str, Any]:
    completed = len(summaries)
    all_successful = completed == requested_variant_count and all(
        item["status"] == "ok" for item in summaries
    )
    comparison = {
        "status": "ok" if all_successful else "partial",
        "checkpoint": checkpoint,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_run_id": source_run_id,
        "sample": sample,
        "output_dir": str(output_dir.resolve()),
        "requested_variant_count": requested_variant_count,
        "variant_count": completed,
        "successful_variant_count": sum(item["status"] == "ok" for item in summaries),
        "projected_cost_usd": round(projected_cost_usd, 6),
        "estimated_cost_usd": round(
            sum(float(item.get("estimated_cost_usd") or 0.0) for item in summaries),
            6,
        ),
        "stopped_reason": stopped_reason,
        "variants": summaries,
    }
    _write_json(output_dir / "comparison_manifest.json", comparison)
    _write_summary_markdown(output_dir / "comparison_summary.md", comparison)
    _write_summary_csv(output_dir / "comparison_summary.csv", summaries)
    _write_playlist(output_dir / "comparison_playlist.m3u8", summaries)
    return comparison


def _write_playlist(path: Path, summaries: list[dict[str, Any]]) -> None:
    lines = ["#EXTM3U"]
    for item in summaries:
        audio_path = Path(str(item.get("audio_path") or ""))
        if item.get("status") != "ok" or not audio_path.name:
            continue
        duration = float(item.get("duration_seconds") or 0.0)
        label = " | ".join(
            part
            for part in (
                str(item.get("model") or ""),
                str(item.get("voice") or ""),
                str(item.get("delivery_label") or item.get("label") or ""),
            )
            if part
        )
        lines.extend(
            [
                f"#EXTINF:{duration:.3f},{label}",
                f"samples/{audio_path.name}",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate short, same-text voiceover delivery samples without synthesizing a full episode."
    )
    parser.add_argument("--script-result", required=True, help="Canonical script_generation_result.json")
    parser.add_argument("--output-dir", required=True, help="Isolated output/labs directory")
    parser.add_argument("--profile", default="daily_48h_all_sources")
    parser.add_argument("--pipeline-config", default="src/pipeline/config/workbench.yaml")
    parser.add_argument("--variant", action="append", default=[], help="Variant id to run; repeat as needed")
    parser.add_argument("--matrix", action="append", default=[], help="Config matrix id to run; repeat as needed")
    parser.add_argument("--resume", action="store_true", help="Reuse successful samples already in output-dir")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env", override=False)
    script_path = (root / args.script_result).resolve()
    config_path = (root / args.pipeline_config).resolve()
    output_dir = (root / args.output_dir).resolve()

    authoring = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    profile = ((authoring.get("profiles") or {}).get(args.profile) or {})
    if not profile:
        raise ValueError(f"Unknown workbench profile: {args.profile}")
    base_voiceover_config = dict(profile.get("voiceover") or {})
    if not base_voiceover_config:
        raise ValueError(f"Profile {args.profile!r} has no voiceover config")
    raw_comparison = ((authoring.get("experiments") or {}).get("voiceover_delivery_comparison") or {})
    comparison_config = DeliveryComparisonConfig.model_validate(raw_comparison)
    script_result = json.loads(script_path.read_text(encoding="utf-8"))

    comparison = run_comparison(
        script_result=script_result,
        script_source=str(script_path),
        base_voiceover_config=base_voiceover_config,
        comparison_config=comparison_config,
        output_dir=output_dir,
        selected_variant_ids=args.variant,
        selected_matrix_ids=args.matrix,
        resume=args.resume,
    )
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0 if comparison["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
