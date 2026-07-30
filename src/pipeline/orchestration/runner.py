"""Thin production router for the four pipeline stages.

Run from the project root with the main project Python, not `.venv-voiceover`::

    python3 -m src.pipeline.orchestration.runner collect \
      --profile daily_48h_all_sources --environment prod
    python3 -m src.pipeline.orchestration.runner content \
      --run-id current
    python3 -m src.pipeline.orchestration.runner voiceover \
      --run-id current --synthesis-mode final
    python3 -m src.pipeline.orchestration.runner voiceover \
      --run-id current --synthesis-mode preview
    python3 -m src.pipeline.orchestration.runner visuals \
      --run-id current

The visuals stage is a thin trigger for the self-contained ``video_engine/`` tool:
it resolves the run's selected voiceover package and invokes the engine's portable
``render-episode.mjs`` over a subprocess boundary. The engine has no dependency on
the pipeline (and vice versa), so it is reusable by any project that emits the same
voiceover-package contract.

Module configs are reloaded from their stage YAML immediately before execution
by default. Use ``--config-mode frozen`` only when reproducing the exact config
captured when the run was created. Resume from a module with ``--from-module``;
the stage reuses compatible upstream artifacts and reruns downstream work.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable

from dotenv import load_dotenv

from .io import load_json


StageFunction = Callable[[dict[str, Any]], dict[str, Any]]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_host_runtime(args.stage)
        request = load_json(Path(args.input_json)) if args.input_json else _request_from_args(args)
        _load_project_environment(request)
        stage_function = _stage_function(args.stage)
        result = stage_function(request)
    except Exception as exc:
        result = {
            "status": "failed",
            "data": {"stage": args.stage, "run_id": getattr(args, "run_id", None)},
            "summary": {"failure_reason": f"{type(exc).__name__}: {exc}"},
            "handoff": {},
        }
    print(json.dumps(_console_result(result), indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "ok" else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m src.pipeline.orchestration.runner",
        description="Run one resumable production stage using the canonical pipeline contracts.",
    )
    subparsers = parser.add_subparsers(dest="stage", required=True)

    collect = subparsers.add_parser("collect", help="Create a run and collect normalized source records.")
    _add_common_arguments(collect, default_run_id=None)
    collect.add_argument("--profile", dest="run_profile")
    collect.add_argument("--no-resume", action="store_true")

    content = subparsers.add_parser("content", help="Prepare, select, write, and draft metadata.")
    _add_common_arguments(content, default_run_id="current")
    content.add_argument("--profile", dest="run_profile")
    content.add_argument("--from-module")
    content.add_argument("--stop-after")
    content.add_argument("--no-resume", action="store_true")

    voiceover = subparsers.add_parser("voiceover", help="Synthesize the native script and finalize metadata.")
    _add_common_arguments(voiceover, default_run_id="current")
    voiceover.add_argument(
        "--synthesis-mode",
        choices=("preview", "final"),
        default="final",
        help="Use the profile's fast local preview voice or its final production voice.",
    )
    voiceover.add_argument("--variant")
    voiceover.add_argument("--voiceover-python", default=".venv-voiceover/bin/python")
    voiceover.add_argument("--no-resume", action="store_true")
    voiceover.add_argument("--skip-metadata-finalization", action="store_true")
    voiceover.add_argument(
        "--config-overrides-json",
        help="Optional JSON object merged into the effective voiceover config for this invocation.",
    )

    visuals = subparsers.add_parser("visuals", help="Render the episode video from the run's voiceover via video_engine.")
    _add_common_arguments(visuals, default_run_id="current")
    visuals.add_argument("--video-engine-dir", default="video_engine", help="Path (relative to project root) to the video_engine tool.")
    visuals.add_argument("--node-bin", default="node", help="Node executable used to launch the visual engine.")
    visuals.add_argument("--deterministic", action="store_true", help="Use the no-LLM bridge instead of the LLM art-director.")
    visuals.add_argument("--units", type=int, help="Dev slice: only plan the first N audio units.")
    visuals.add_argument("--skip-render", action="store_true", help="Stop after building index.html — no MP4.")

    return parser


def _add_common_arguments(parser: argparse.ArgumentParser, *, default_run_id: str | None) -> None:
    parser.add_argument(
        "--input-json",
        help="Use an exact stage request envelope instead of constructing one from CLI flags.",
    )
    parser.add_argument("--run-id", default=default_run_id)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--pipeline-config", default="src/pipeline/config/workbench.yaml")
    parser.add_argument(
        "--environment",
        help="Config overlay to use. Defaults to PIPELINE_ENVIRONMENT/ENVIRONMENT, then the manifest default.",
    )
    parser.add_argument(
        "--config-mode",
        choices=("live", "frozen"),
        default="live",
        help=(
            "Resolve each module from current authoring YAML (live, default) or from the run's initial "
            "profile snapshot (frozen). Every executed module writes its own config snapshot."
        ),
    )


def _request_from_args(args: argparse.Namespace) -> dict[str, Any]:
    request: dict[str, Any] = {
        "run": {
            "run_id": args.run_id,
            "config_environment": args.environment,
        },
        "paths": {
            "project_root": args.project_root,
            "output_root": args.output_root,
            "pipeline_config_path": args.pipeline_config,
        },
        "config": {},
        "input": {},
    }
    if args.stage == "collect":
        request["run"]["run_profile"] = args.run_profile
        request["config"] = {
            "config_mode": args.config_mode,
            "resume_completed": not args.no_resume,
        }
    elif args.stage == "content":
        request["run"]["run_profile"] = args.run_profile
        request["config"] = {
            "config_mode": args.config_mode,
            "resume_completed": not args.no_resume,
            "from_module": args.from_module,
            "stop_after": args.stop_after,
        }
    elif args.stage == "voiceover":
        request["config"] = {
            "config_mode": args.config_mode,
            "synthesis_mode": args.synthesis_mode,
            "variant": args.variant,
            "voiceover_python": args.voiceover_python,
            "resume_completed": not args.no_resume,
            "finalize_metadata": not args.skip_metadata_finalization,
        }
        if args.config_overrides_json:
            overrides = json.loads(args.config_overrides_json)
            if not isinstance(overrides, dict):
                raise ValueError("--config-overrides-json must decode to a JSON object")
            request["input"]["voiceover_config_overrides"] = overrides
    elif args.stage == "visuals":
        request["config"] = {
            "config_mode": args.config_mode,
            "video_engine_dir": args.video_engine_dir,
            "node_bin": args.node_bin,
            "deterministic": args.deterministic,
            "units": args.units,
            "skip_render": args.skip_render,
        }
    return request


def _stage_function(stage: str) -> StageFunction:
    # Keep CLI help and argument validation fast; stage imports load optional LLM/media dependencies.
    if stage == "collect":
        from .stages.ingestion import run

        return run
    if stage == "content":
        from .stages.content import run

        return run
    if stage == "voiceover":
        from .stages.voiceover import run

        return run
    if stage == "visuals":
        from .stages.visuals import run

        return run
    raise ValueError(f"Unknown stage: {stage}")


def _validate_host_runtime(stage: str) -> None:
    virtual_env = os.environ.get("VIRTUAL_ENV", "")
    runtime_paths = (virtual_env, sys.executable, sys.prefix)
    if any(".venv-voiceover" in path for path in runtime_paths):
        raise RuntimeError(
            "The orchestration runner must use the main project Python, not .venv-voiceover. "
            "Run `deactivate`, then "
            f"`python3 -m src.pipeline.orchestration.runner {stage} ...`. "
            "The voiceover stage launches .venv-voiceover internally when synthesis is required."
        )


def _load_project_environment(request: dict[str, Any]) -> None:
    paths = request.get("paths") if isinstance(request.get("paths"), dict) else {}
    project_root = Path(str(paths.get("project_root") or ".")).expanduser().resolve()
    load_dotenv(dotenv_path=project_root / ".env", override=False)
    run = request.setdefault("run", {})
    if not isinstance(run, dict):
        raise TypeError("runner request run must be a mapping")
    if not str(run.get("config_environment") or "").strip():
        configured = os.getenv("PIPELINE_ENVIRONMENT") or os.getenv("ENVIRONMENT")
        if configured:
            run["config_environment"] = configured.strip().lower()


def _console_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "data": result.get("data", {}),
        "summary": result.get("summary", {}),
        "handoff": result.get("handoff", {}),
    }


if __name__ == "__main__":
    sys.exit(main())
