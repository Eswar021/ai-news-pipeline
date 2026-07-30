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

from src.pipeline.orchestration.io import load_json, write_json
from src.pipeline.orchestration.run_context import create_run_context


SCHEMA_VERSION = "pipeline_fixture_scenario_v1"


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = seed_scenario(
            project_root=Path(args.project_root),
            output_root=Path(args.output_root),
            scenario=args.scenario,
            fixture_root=Path(args.fixture_root),
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
    write_json(
        run_dir / "fixture_scenario.json",
        {
            **deepcopy(spec),
            "scenario_source": str(scenario_dir),
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
    return parser


if __name__ == "__main__":
    sys.exit(main())
