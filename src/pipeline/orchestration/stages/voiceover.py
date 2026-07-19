from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import os
import subprocess
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from src.pipeline.config import ConfigDocument
from src.pipeline.content.metadata_finalizer import run as run_metadata_finalizer
from src.pipeline.voiceover.contract import VoiceoverConfig
from ..artifact_selection import fingerprint_token, resolve_script_result, resolve_voiceover_package
from ..io import load_json, write_json
from ..logging import configure_stage_logging
from ..state import RunStateStore
from .common import (
    BaseStageRequest,
    StageConfigResolver,
    current_or_named_context,
    effective_logging_config,
    now_iso,
    project_paths,
    rendered_config,
    require_ready,
    reusable_config_matches,
    write_module_config_snapshot,
)


STAGE = "voiceover"
MODULES = ["voiceover", "metadata_finalizer"]


class VoiceoverOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_mode: Literal["live", "frozen"] = "live"
    script_source: str = "auto"
    synthesis_mode: Literal["preview", "final"] = "final"
    variant: str | None = None
    voiceover_python: str = ".venv-voiceover/bin/python"
    resume_completed: bool = True
    finalize_metadata: bool = True


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    request = BaseStageRequest.model_validate(input_json)
    options = VoiceoverOptions.model_validate(request.config)
    project_root, output_root, config_path = project_paths(request.paths)
    run_context = current_or_named_context(output_root, request.run.run_id)
    logger = configure_stage_logging(run_context, STAGE, effective_logging_config(run_context))
    state = RunStateStore(run_context)
    state.start_stage(STAGE, MODULES)
    result_path = Path(run_context["run_dir"]) / "orchestration" / "voiceover_stage_result.json"

    try:
        response = _run_stage(
            request=request,
            options=options,
            project_root=project_root,
            output_root=output_root,
            config_path=config_path,
            run_context=run_context,
            logger=logger,
            state=state,
        )
        logger.attach_paths(response, state_path=state.path)
        write_json(result_path, response)
        state.finish_stage(STAGE, status="ok")
        logger.logger.info("COMPLETE stage=%s", STAGE)
        logger.event("stage.completed", status="ok", details=response["summary"])
        return response
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        response = {
            "status": "failed",
            "data": {"run_id": run_context["run_id"], "run_dir": run_context["run_dir"], "stage": STAGE},
            "summary": {"failure_reason": reason},
            "handoff": {"ready_for_visuals": False},
        }
        logger.attach_paths(response, state_path=state.path)
        write_json(result_path, response)
        state.finish_stage(STAGE, status="failed", failure_reason=reason)
        logger.logger.exception("FAILED stage=%s", STAGE)
        logger.event("stage.failed", status="failed", details={"error": reason})
        return response


def _run_stage(
    *,
    request: BaseStageRequest,
    options: VoiceoverOptions,
    project_root: Path,
    output_root: Path,
    config_path: Path,
    run_context: dict[str, Any],
    logger,
    state: RunStateStore,
) -> dict[str, Any]:
    run_id = str(run_context["run_id"])
    run_dir = Path(run_context["run_dir"])
    config_resolver = StageConfigResolver(run_context, config_path, options.config_mode)
    script_path, script_result = resolve_script_result(
        run_dir=run_dir,
        run_id=run_id,
        source=options.script_source,
    )
    script_package = script_result["data"]["script_package"]
    script_provenance = script_package["provenance"]
    voice_document = _voiceover_config_document(config_resolver, options.synthesis_mode)
    voice_config = rendered_config(
        run_context,
        voice_document.value,
        project_root=project_root,
        output_root=output_root,
    )
    _deep_update(voice_config, request.input.get("voiceover_config_overrides") or {})
    voice_config["output_dir"] = str(run_dir / "voiceover")
    voice_config = VoiceoverConfig.model_validate(voice_config).model_dump(mode="json")
    variant = options.variant or _voiceover_variant(voice_config, script_package, script_provenance)
    voiceover_dir = run_dir / "voiceover" / variant
    voice_config["output_dir"] = str(voiceover_dir)
    input_envelope = {
        "run": {"run_id": run_id, "generated_at": now_iso()},
        "config": voice_config,
        "input": {"script_generation": script_result},
    }
    input_path = run_dir / "inputs" / "voiceover" / f"{variant}.json"
    write_json(input_path, input_envelope)
    config_snapshot_path = voiceover_dir / "config_snapshot.json"

    existing: tuple[Path, dict[str, Any]] | None = None
    if options.resume_completed and reusable_config_matches(
        config_snapshot_path,
        voice_document,
        mode=options.config_mode,
        effective_config=voice_config,
    ):
        try:
            existing = resolve_voiceover_package(
                run_dir=run_dir,
                run_id=run_id,
                script_fingerprint=script_provenance["script_fingerprint"],
                variant=variant,
            )
        except (FileNotFoundError, ValueError):
            existing = None

    if existing:
        package_path, voiceover_package = existing
        summary = load_json(package_path.parent / "summary.json")
        voiceover_result = _voiceover_envelope(run_id, voiceover_package, summary)
        logger.logger.info("REUSE module=voiceover package=%s", package_path)
        logger.event("module.reused", module="voiceover", status="ok", details={"package_path": str(package_path)})
        state.record_module(
            STAGE,
            "voiceover",
            status="ok",
            result_path=str(package_path.parent / "voiceover_result.json"),
            summary=summary,
            reused=True,
        )
    else:
        voiceover_python = Path(options.voiceover_python).expanduser()
        if not voiceover_python.is_absolute():
            voiceover_python = project_root / voiceover_python
        if not voiceover_python.exists():
            raise FileNotFoundError(f"Voiceover Python not found: {voiceover_python}")

        def generate(_: dict[str, Any]) -> dict[str, Any]:
            _run_subprocess(
                [str(voiceover_python), "-m", "src.pipeline.voiceover.cli", "--input-json", str(input_path)],
                cwd=project_root,
                logger=logger,
            )
            package = load_json(voiceover_dir / "voiceover_package.json")
            summary = load_json(voiceover_dir / "summary.json")
            return _voiceover_envelope(run_id, package, summary)

        voiceover_result = logger.run_module("voiceover", generate, input_envelope)
        require_ready(voiceover_result, "voiceover")
        voiceover_package = voiceover_result["data"]["voiceover_package"]
        summary = voiceover_result["summary"]
        write_json(voiceover_dir / "voiceover_input.json", input_envelope)
        write_json(voiceover_dir / "voiceover_result.json", voiceover_result)
        write_module_config_snapshot(
            voiceover_dir,
            stage=STAGE,
            module="voiceover",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=voice_document,
            effective_config=voice_config,
        )
        state.record_module(
            STAGE,
            "voiceover",
            status="ok",
            result_path=str(voiceover_dir / "voiceover_result.json"),
            summary=summary,
        )

    write_json(
        run_dir / "orchestration" / "voiceover_selection.json",
        {
            "script_result_path": str(script_path),
            "script_fingerprint": script_provenance["script_fingerprint"],
            "voiceover_package_path": str(voiceover_dir / "voiceover_package.json"),
            "voiceover_fingerprint": voiceover_package["provenance"]["voiceover_fingerprint"],
        },
    )

    metadata_result_path = run_dir / "metadata_finalizer" / "metadata_finalizer_result.json"
    if options.finalize_metadata:
        metadata_creator_path = run_dir / "metadata_creator" / "metadata_creator_result.json"
        metadata_creator_result = load_json(metadata_creator_path)
        metadata_document = config_resolver.module("content", "metadata_finalizer")
        metadata_input = {
            "run": {"run_id": run_id, "generated_at": now_iso()},
            "config": deepcopy(metadata_document.value),
            "input": {
                "metadata_creator": metadata_creator_result,
                "script_generation": script_result,
                "voiceover": voiceover_result,
            },
        }
        metadata_result = logger.run_module("metadata_finalizer", run_metadata_finalizer, metadata_input)
        metadata_dir = run_dir / "metadata_finalizer"
        write_module_config_snapshot(
            metadata_dir,
            stage=STAGE,
            module="metadata_finalizer",
            mode=options.config_mode,
            profile_name=str(run_context["run_profile"]),
            document=metadata_document,
            effective_config=metadata_input["config"],
        )
        write_json(metadata_dir / "metadata_finalizer_input.json", metadata_input)
        write_json(metadata_result_path, metadata_result)
        write_json(metadata_dir / "summary.json", metadata_result["summary"])
        state.record_module(
            STAGE,
            "metadata_finalizer",
            status="ok",
            result_path=str(metadata_result_path),
            summary=metadata_result["summary"],
        )
        require_ready(metadata_result, "metadata_finalizer")
        package = metadata_result["data"]["metadata_package"]
        write_json(metadata_dir / "metadata_package.json", package)
        write_json(metadata_dir / "youtube_metadata.json", package["youtube_metadata"])

    return {
        "status": "ok",
        "data": {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "stage": STAGE,
            "script_result_path": str(script_path),
            "voiceover_result_path": str(voiceover_dir / "voiceover_result.json"),
            "voiceover_package_path": str(voiceover_dir / "voiceover_package.json"),
            "metadata_finalizer_result_path": str(metadata_result_path) if options.finalize_metadata else "",
        },
        "summary": {
            "synthesis_mode": options.synthesis_mode,
            "provider": summary.get("provider", ""),
            "voice": summary.get("voice", ""),
            "duration_seconds": summary.get("duration_seconds", 0),
            "audio_unit_count": summary.get("audio_unit_count", 0),
            "aligned_beat_count": summary.get("aligned_beat_count", 0),
            "variant": variant,
        },
        "handoff": {"ready_for_visuals": True},
    }


def _voiceover_envelope(run_id: str, package: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "data": {
            "run_id": run_id,
            "generated_at": package.get("generated_at"),
            "voiceover_package": package,
        },
        "summary": summary,
        "handoff": package.get("handoff", {}),
    }


def _voiceover_variant(
    config: dict[str, Any],
    script_package: dict[str, Any],
    script_provenance: dict[str, Any],
) -> str:
    def slug(value: object) -> str:
        text = str(value).strip().lower().replace(".", "p")
        return "_".join(part for part in "".join(ch if ch.isalnum() else "_" for ch in text).split("_") if part)

    source = "chatgpt" if script_package.get("generation_source") == "chatgpt_handoff" else "app"
    provider = str(config.get("provider", "provider"))
    provider_config = config.get(provider) if isinstance(config.get(provider), dict) else {}
    configured_voice = (
        provider_config.get("voice")
        if provider in {"openai", "gemini"}
        else config.get("voice") or provider_config.get("voice")
    )
    values = [
        slug(provider),
        slug(config.get("style", "style")),
        slug(configured_voice or "default"),
        slug(provider_config.get("model")) if provider in {"openai", "gemini"} else "",
        f"speed_{slug(config.get('speed', 'style'))}",
        f"cfg_{_api_voice_config_token(config, provider)}" if provider in {"openai", "gemini"} else "",
        source,
        fingerprint_token(script_provenance["script_fingerprint"]),
    ]
    return "_".join(filter(None, values))


def _api_voice_config_token(config: dict[str, Any], provider: str) -> str:
    identity = {
        "provider": provider,
        "style": config.get("style"),
        "voice": config.get("voice"),
        "speed": config.get("speed"),
        "sample_rate_hz": config.get("sample_rate_hz"),
        "chunking": config.get("chunking"),
        "alignment": config.get("alignment"),
        "mastering": config.get("mastering"),
        "captions": config.get("captions"),
        "provider_config": config.get(provider),
    }
    serialized = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:10]


def _voiceover_config_document(
    resolver: StageConfigResolver,
    synthesis_mode: Literal["preview", "final"],
) -> ConfigDocument:
    base = resolver.module("voiceover", "voiceover")
    if synthesis_mode == "final":
        return base

    preview = resolver.module("voiceover", "voiceover_preview")
    value = deepcopy(base.value)
    _deep_update(value, preview.value)
    identity = {
        "mode": synthesis_mode,
        "base_sha256": base.sha256,
        "preview_sha256": preview.sha256,
        "value": value,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return ConfigDocument(
        value=value,
        sha256=digest,
        source_paths=tuple(dict.fromkeys((*base.source_paths, *preview.source_paths))),
    )


def _run_subprocess(command: list[str], *, cwd: Path, logger) -> None:
    env = {**os.environ, "PYTHONPATH": str(cwd)}
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        logger.logger.info("SUBPROCESS %s", line.rstrip())
    return_code = process.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, command)


def _deep_update(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = deepcopy(value)
