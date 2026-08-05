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
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from src.pipeline.content.asset_collection import build_asset_manifest
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
    manifest_path = _write_asset_manifest(run_dir, visuals_dir, logger)
    command = [
        options.node_bin,
        str(entrypoint),
        "--voiceover-package", str(package_path),
        "--audio", str(audio_path),
        "--out-dir", str(visuals_dir),
        "--tag", str(run_id),
    ]
    if manifest_path is not None:
        command += ["--asset-manifest", str(manifest_path)]
    selected_format = _selected_format(run_dir)
    if selected_format:
        # The engine is format-aware: roundup gets numbered story dividers; a
        # deep-dive is one continuous topic (no "story N of M" numbering).
        command += ["--format", selected_format]
    research_path = _write_research_pack(run_dir, visuals_dir, selected_format, logger)
    if research_path is not None:
        # Researched deep-dive: hand the art-director the dossier's showable facts
        # so it builds real timeline / stat / quote visuals from the research.
        command += ["--research", str(research_path)]
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


def _selected_format(run_dir: Path) -> str:
    """The run's format (roundup / deep_dive) from the video-packaging result, so the
    engine can plan format-appropriately. Best-effort — absent → the engine defaults."""
    packet_path = run_dir / "video_packaging" / "video_packaging_result.json"
    if not packet_path.exists():
        return ""
    try:
        return str((load_json(packet_path).get("data") or {}).get("selected_format") or "")
    except Exception:  # noqa: BLE001 — never let a read failure break the render
        return ""


def _domain(url: str) -> str:
    """Bare hostname (no www) — a clean short source label for the art-director."""
    try:
        net = urlparse(str(url)).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:  # noqa: BLE001
        return ""


def _write_research_pack(run_dir: Path, visuals_dir: Path, selected_format: str, logger) -> Path | None:
    """For a RESEARCHED deep-dive, hand the art-director the dossier's SHOWABLE facts
    (timeline, numbers, quotes, sources) so it can build real timeline / stat / quote /
    montage visuals from the research — not only from what the narration restates.
    Deep-dive + researched only; best-effort (any failure → None → engine unchanged)."""
    if selected_format != "deep_dive":
        return None
    res_path = run_dir / "topic_research" / "topic_research_result.json"
    if not res_path.exists():
        return None
    try:
        data = load_json(res_path).get("data") or {}
        if not data.get("researched"):
            return None
        doss = data.get("research_dossier") or {}
        pack = {
            "timeline": [{"date": e.get("date", ""), "event": e.get("event", "")}
                         for e in (doss.get("timeline") or [])[:8] if e.get("event")],
            "numbers": [{"value": n.get("value", ""), "context": n.get("context", "")}
                        for n in (doss.get("numbers") or [])[:8] if n.get("value")],
            "quotes": [{"text": q.get("text", ""), "speaker": q.get("speaker", ""), "source": _domain(q.get("source_url", ""))}
                       for q in (doss.get("quotes") or [])[:5] if q.get("text")],
            "sources": [{"source": _domain(s.get("url", "")), "title": s.get("title", "")}
                        for s in (doss.get("sources") or [])[:6] if s.get("url")],
        }
        if not any(pack.values()):
            return None
        visuals_dir.mkdir(parents=True, exist_ok=True)
        out = visuals_dir / "research_pack.json"
        write_json(out, pack)
        logger.logger.info(
            "VISUALS research pack: %d timeline, %d numbers, %d quotes, %d sources",
            len(pack["timeline"]), len(pack["numbers"]), len(pack["quotes"]), len(pack["sources"]),
        )
        return out
    except Exception as exc:  # noqa: BLE001 — research is an enhancement, never break the render
        logger.logger.warning("VISUALS research pack skipped: %s", exc)
        return None


def _write_asset_manifest(run_dir: Path, visuals_dir: Path, logger) -> Path | None:
    """Collect real source images (og:image) for the selected stories and write an
    asset manifest for the engine. Best-effort: any failure returns None and the
    render proceeds exactly as before (engine stays decoupled — no manifest, no
    change in behavior)."""
    packet_path = run_dir / "video_packaging" / "video_packaging_result.json"
    if not packet_path.exists():
        return None
    try:
        packet_result = load_json(packet_path)
        stories = (
            ((packet_result.get("data") or {}).get("video_packet") or {}).get("stories") or []
        )
        if not stories:
            return None
        manifest = build_asset_manifest(stories)
        image_count = sum(len(story.get("images", [])) for story in manifest.get("stories", []))
        if image_count == 0:
            logger.logger.info("VISUALS asset manifest: no source images resolved; skipping")
            return None
        manifest_path = visuals_dir / "asset_manifest.json"
        write_json(manifest_path, manifest)
        logger.logger.info(
            "VISUALS asset manifest: %d image(s) across %d story(ies) → %s",
            image_count,
            len(manifest.get("stories", [])),
            manifest_path,
        )
        return manifest_path
    except Exception as exc:  # best-effort; never block the render
        logger.logger.warning("VISUALS asset manifest skipped: %s: %s", type(exc).__name__, exc)
        return None


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
