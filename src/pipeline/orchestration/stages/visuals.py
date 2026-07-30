"""Thin visuals stage: turn a finished run's voiceover into a rendered episode.

This stage owns NO visual logic. The visual engine lives in ``video_engine/`` as a
self-contained, project-agnostic Node tool with its own dependencies; nothing in
``src/pipeline`` imports it and it imports nothing from the pipeline. The only
contact is this subprocess boundary: we resolve the run's selected voiceover
package (the pipeline-specific bit), then invoke the engine's portable
``render-episode.mjs`` with explicit paths. The engine could be pointed at any
project that emits the same voiceover-package contract.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ..io import load_json, write_json
from ..logging import configure_stage_logging
from ..state import RunStateStore
from .common import (
    BaseStageRequest,
    current_or_named_context,
    effective_logging_config,
    project_paths,
    require_matching_config_environment,
)


STAGE = "visuals"
MODULES = ["visuals"]


class VisualsOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_mode: Literal["live", "frozen"] = "live"
    video_engine_dir: str = "video_engine"
    node_bin: str = "node"
    deterministic: bool = False
    units: int | None = None
    skip_render: bool = False


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    request = BaseStageRequest.model_validate(input_json)
    options = VisualsOptions.model_validate(request.config)
    project_root, output_root, _config_path = project_paths(request.paths)
    run_context = current_or_named_context(output_root, request.run.run_id)
    require_matching_config_environment(run_context, request.run.config_environment)
    logger = configure_stage_logging(run_context, STAGE, effective_logging_config(run_context))
    state = RunStateStore(run_context)
    state.start_stage(STAGE, MODULES)
    run_dir = Path(run_context["run_dir"])
    result_path = run_dir / "orchestration" / "visuals_stage_result.json"

    try:
        response = _run_stage(
            options=options,
            project_root=project_root,
            run_context=run_context,
            logger=logger,
        )
        logger.attach_paths(response, state_path=state.path)
        write_json(result_path, response)
        state.record_module(STAGE, "visuals", status="ok", result_path=str(result_path), summary=response["summary"])
        state.finish_stage(STAGE, status="ok")
        logger.logger.info("COMPLETE stage=%s", STAGE)
        return response
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        response = {
            "status": "failed",
            "data": {"run_id": run_context["run_id"], "run_dir": run_context["run_dir"], "stage": STAGE},
            "summary": {"failure_reason": reason},
            "handoff": {"episode_rendered": False},
        }
        logger.attach_paths(response, state_path=state.path)
        write_json(result_path, response)
        state.finish_stage(STAGE, status="failed", failure_reason=reason)
        logger.logger.exception("FAILED stage=%s", STAGE)
        return response


def _run_stage(
    *,
    options: VisualsOptions,
    project_root: Path,
    run_context: dict[str, Any],
    logger,
) -> dict[str, Any]:
    run_id = run_context["run_id"]
    run_dir = Path(run_context["run_dir"])

    # Pipeline-specific input resolution: the selected voiceover package + its WAV.
    selection_path = run_dir / "orchestration" / "voiceover_selection.json"
    if not selection_path.exists():
        raise FileNotFoundError(
            f"No voiceover_selection.json at {selection_path}; run the voiceover stage first."
        )
    selection = load_json(selection_path)
    package_path = Path(str(selection.get("voiceover_package_path") or "")).expanduser()
    if not package_path.is_absolute():
        package_path = (run_dir / package_path).resolve()
    if not package_path.exists():
        raise FileNotFoundError(f"Selected voiceover package missing: {package_path}")
    audio_path = package_path.parent / "audio" / "full_voiceover.wav"
    if not audio_path.exists():
        raise FileNotFoundError(f"Voiceover WAV missing: {audio_path}")

    engine_dir = (project_root / options.video_engine_dir).resolve()
    entrypoint = engine_dir / "scripts" / "pipeline" / "render-episode.mjs"
    if not entrypoint.exists():
        raise FileNotFoundError(f"Visual engine entrypoint not found: {entrypoint}")

    visuals_dir = run_dir / "visuals"
    command = [
        options.node_bin,
        str(entrypoint),
        "--voiceover-package", str(package_path),
        "--audio", str(audio_path),
        "--out-dir", str(visuals_dir),
        "--tag", str(run_id),
    ]
    if options.deterministic:
        command.append("--deterministic")
    if options.units is not None:
        command += ["--units", str(options.units)]
    if options.skip_render:
        command.append("--skip-render")
    channel_name = _channel_name(project_root, run_context)
    if channel_name:
        command += ["--channel-name", channel_name]

    logger.logger.info("VISUALS launching engine: %s", " ".join(command))
    _run_subprocess(command, cwd=engine_dir, logger=logger)

    episode_path = visuals_dir / f"{run_id}-ad.mp4"
    episode_rendered = (not options.skip_render) and episode_path.exists()

    return {
        "status": "ok",
        "data": {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "stage": STAGE,
            "voiceover_package_path": str(package_path),
            "visuals_dir": str(visuals_dir),
            "episode_path": str(episode_path) if episode_rendered else "",
        },
        "summary": {
            "engine": str(entrypoint.relative_to(project_root)),
            "art_director": "bridge" if options.deterministic else "llm",
            "units": options.units,
            "rendered": episode_rendered,
        },
        "handoff": {"episode_rendered": episode_rendered},
    }


def _channel_name(project_root: Path, run_context: dict[str, Any]) -> str:
    """The pipeline profile owns the channel identity; pass channel_name to the
    engine so branding has a single source of truth. Best-effort — the engine
    falls back to its own configured default if this is unavailable."""
    profile = str(run_context.get("run_profile") or "").strip()
    if not profile:
        return ""
    profile_path = project_root / "src" / "pipeline" / "config" / "profiles" / profile / "profile.yaml"
    if not profile_path.exists():
        return ""
    try:
        import yaml

        data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    channel = data.get("channel") if isinstance(data.get("channel"), dict) else {}
    return str(channel.get("channel_name") or "").strip()


def _run_subprocess(command: list[str], *, cwd: Path, logger) -> None:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env={**os.environ},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        logger.logger.info("ENGINE %s", line.rstrip())
    return_code = process.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, command)
