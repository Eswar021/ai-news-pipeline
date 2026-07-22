"""Developer adapter for deterministic pipeline fixture scenarios.

This module never changes production app behavior. It seeds canonical artifacts
under a dedicated output root and can bind a curated visual plan to a preview
voiceover so renderer work does not require collection or LLM calls.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import yaml

from src.pipeline.orchestration.artifact_selection import resolve_voiceover_package
from src.pipeline.orchestration.io import load_json, write_json
from src.pipeline.orchestration.run_context import create_run_context, load_run_context
from src.pipeline.visuals.planner.retime import bind_visual_plan_result, retime_visual_plan_result


SCHEMA_VERSION = "pipeline_fixture_scenario_v1"


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "seed":
            result = seed_scenario(
                project_root=Path(args.project_root),
                output_root=Path(args.output_root),
                scenario=args.scenario,
                fixture_root=Path(args.fixture_root),
            )
        else:
            result = bind_visual_plan(
                project_root=Path(args.project_root),
                output_root=Path(args.output_root),
                run_id=args.run_id,
                voiceover_variant=args.voiceover_variant,
            )
    except Exception as exc:
        result = {
            "status": "failed",
            "data": {},
            "summary": {"failure_reason": f"{type(exc).__name__}: {exc}"},
            "handoff": {},
        }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "ok" else 1


def seed_scenario(
    *,
    project_root: Path,
    output_root: Path,
    scenario: str,
    fixture_root: Path,
) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    fixtures = fixture_root if fixture_root.is_absolute() else root / fixture_root
    scenario_dir = (fixtures / scenario).resolve()
    spec = _load_scenario(scenario_dir / "scenario.yaml")
    output = output_root if output_root.is_absolute() else root / output_root
    context = create_run_context(
        project_root=root,
        run_profile=str(spec["run_profile"]),
        run_id=str(spec["run_id"]),
        trigger="fixture",
        orchestrator="src.pipeline.orchestration.fixture_scenarios:seed",
        config_path=root / "src/pipeline/config/workbench.yaml",
        output_root=output,
        config_environment=str(spec["config_environment"]),
    )
    run_dir = Path(context["run_dir"])
    artifacts = spec["artifacts"]
    video_result = load_json(scenario_dir / artifacts["video_packaging"])
    script_result = load_json(scenario_dir / artifacts["script_generation"])
    _require_fixture_run_id(video_result, str(spec["run_id"]), "video_packaging")
    _require_fixture_run_id(script_result, str(spec["run_id"]), "script_generation")

    video_dir = run_dir / "video_packaging"
    script_dir = run_dir / "script_generation"
    fixture_dir = run_dir / "fixtures" / str(spec["scenario_id"])
    write_json(video_dir / "video_packaging_result.json", video_result)
    write_json(video_dir / "video_packet.json", video_result["data"]["video_packet"])
    write_json(video_dir / "summary.json", video_result.get("summary", {}))
    write_json(script_dir / "script_generation_result.json", script_result)
    write_json(script_dir / "script_package.json", script_result["data"]["script_package"])
    write_json(script_dir / "summary.json", script_result.get("summary", {}))
    full_script = str(script_result["data"]["script_package"].get("full_script") or "").strip()
    if not full_script:
        raise ValueError("fixture script_generation result has an empty full_script")
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "full_script.txt").write_text(full_script, encoding="utf-8")

    fixture_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        scenario_dir / artifacts["visual_plan_template"],
        fixture_dir / "visual_scene_planning_result_template.json",
    )
    write_json(
        run_dir / "fixture_scenario.json",
        {
            **deepcopy(spec),
            "scenario_source": str(scenario_dir),
            "visual_plan_template": str(fixture_dir / "visual_scene_planning_result_template.json"),
        },
    )
    return {
        "status": "ok",
        "data": {
            "run_id": context["run_id"],
            "run_dir": context["run_dir"],
            "output_root": str(output),
            "scenario": spec["scenario_id"],
        },
        "summary": {"seeded_artifact_count": 3},
        "handoff": {"ready_for_preview_voiceover": True},
    }


def bind_visual_plan(
    *,
    project_root: Path,
    output_root: Path,
    run_id: str,
    voiceover_variant: str | None,
) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    output = output_root if output_root.is_absolute() else root / output_root
    context = load_run_context(output_root=output, run_id=run_id)
    run_dir = Path(context["run_dir"])
    fixture_spec = load_json(run_dir / "fixture_scenario.json")
    script_result = load_json(run_dir / "script_generation" / "script_generation_result.json")
    script_provenance = script_result["data"]["script_package"]["provenance"]
    _, voiceover_package = resolve_voiceover_package(
        run_dir=run_dir,
        run_id=str(context["run_id"]),
        script_fingerprint=script_provenance["script_fingerprint"],
        variant=voiceover_variant,
    )
    voiceover_provenance = voiceover_package["provenance"]
    duration = float((voiceover_package.get("audio") or {}).get("duration_seconds") or 0)
    if duration <= 0:
        raise ValueError("selected fixture voiceover has no positive duration")
    template = load_json(Path(fixture_spec["visual_plan_template"]))
    retimed = retime_visual_plan_result(template, duration)
    bound = bind_visual_plan_result(
        retimed,
        run_id=str(context["run_id"]),
        script_provenance=script_provenance,
        voiceover_provenance=voiceover_provenance,
    )
    planning_dir = run_dir / "visuals" / "planning" / "chatgpt"
    write_json(planning_dir / "visual_scene_planning_result.json", bound)
    write_json(planning_dir / "visual_scene_plan.json", bound["data"]["visual_scene_plan"])
    write_json(planning_dir / "summary.json", bound.get("summary", {}))
    return {
        "status": "ok",
        "data": {
            "run_id": context["run_id"],
            "visual_plan_path": str(planning_dir / "visual_scene_planning_result.json"),
            "voiceover_variant": voiceover_variant or "auto",
        },
        "summary": {
            "scene_count": len(bound["data"]["visual_scene_plan"]["scene_timeline"]),
            "duration_seconds": duration,
        },
        "handoff": {"ready_for_fixture_visuals": True},
    }


def _load_scenario(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Fixture scenario not found: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported fixture scenario: {path}")
    required = {"scenario_id", "run_id", "run_profile", "config_environment", "artifacts"}
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"Fixture scenario is missing fields: {missing}")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, dict):
        raise TypeError("fixture scenario artifacts must be a mapping")
    return value


def _require_fixture_run_id(result: dict[str, Any], run_id: str, label: str) -> None:
    actual = str((result.get("data") or {}).get("run_id") or "")
    if actual != run_id:
        raise ValueError(f"{label} fixture run_id {actual!r} does not match scenario {run_id!r}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m src.pipeline.orchestration.fixture_scenarios")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed = subparsers.add_parser("seed", help="Seed a deterministic test run from committed artifacts.")
    seed.add_argument("--scenario", default="media_roundup_reference")
    seed.add_argument("--fixture-root", default="tests/fixtures")
    seed.add_argument("--project-root", default=".")
    seed.add_argument("--output-root", default="output/tests")
    bind = subparsers.add_parser("bind-visual-plan", help="Bind the curated plan to a generated preview voiceover.")
    bind.add_argument("--run-id", default="fixture_media_roundup_reference")
    bind.add_argument("--voiceover-variant")
    bind.add_argument("--project-root", default=".")
    bind.add_argument("--output-root", default="output/tests")
    return parser


if __name__ == "__main__":
    sys.exit(main())
