from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.pipeline_v2.handoffs.common import read_json, write_text_files

from .app import PROFILE_ORDER, run


PROFILE_ARTIFACTS = {
    "story_map": ("L3", "stories.json"),
    "fact_packet": ("L4", "fact_packets.json"),
    "editorial_brief": ("L5", "selected_video_brief.json"),
    "content_packet": ("L6", "content_packet.json"),
    "script_review": ("L7", "script_package.json"),
    "publish_review": ("L8", "verification_package.json"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate standalone ChatGPT handoff files")
    parser.add_argument("--input-json", help="Optional prebuilt handoff request JSON")
    parser.add_argument("--run-id", default="current")
    parser.add_argument("--profile", default="auto")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    if args.input_json:
        request = read_json(Path(args.input_json))
    else:
        request = _build_request_from_run(args.run_id, args.profile, Path(args.output_root), args.output_dir)

    result = run(request)
    if result["status"] != "ok":
        raise SystemExit(result["summary"].get("error", "ChatGPT handoff export failed"))

    output_dir = Path(args.output_dir or request.get("config", {}).get("output_dir") or _default_output_dir(result, Path(args.output_root)))
    paths = write_text_files(result["data"]["handoff_package"]["files"], output_dir)
    print(f"[chatgpt_exporter] Wrote: {output_dir}")
    for path in paths:
        print(f"  {path}")


def _build_request_from_run(run_ref: str, profile: str, output_root: Path, output_dir: str | None) -> dict[str, Any]:
    manifest = _load_manifest(run_ref, output_root)
    run_id = manifest["run_id"]
    run_dir = output_root / run_id
    artifacts = _load_available_artifacts(run_dir)
    summaries = _load_summaries(run_dir)
    return {
        "run": {"run_id": run_id},
        "config": {
            "profile": profile,
            "output_dir": output_dir or str(output_root / "chatgpt_handoffs" / run_id / _output_profile(profile, artifacts)),
        },
        "input": {
            "manifest": manifest,
            "artifacts": artifacts,
            "summaries": summaries,
        },
    }


def _load_manifest(run_ref: str, output_root: Path) -> dict[str, Any]:
    if run_ref == "current":
        current = read_json(output_root / "current_manifest.json")
        run_id = current.get("run_id")
        if not run_id:
            raise KeyError(f"{output_root / 'current_manifest.json'} is missing run_id")
        return read_json(output_root / run_id / "run_manifest.json")
    return read_json(output_root / run_ref / "run_manifest.json")


def _load_available_artifacts(run_dir: Path) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for profile, (layer, filename) in PROFILE_ARTIFACTS.items():
        path = run_dir / layer / filename
        if path.exists():
            artifacts[profile] = read_json(path)
    return artifacts


def _load_summaries(run_dir: Path) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for summary_path in sorted(run_dir.glob("L*/summary.json")):
        summaries[summary_path.parent.name] = read_json(summary_path)
    return summaries


def _output_profile(profile: str, artifacts: dict[str, dict[str, Any]]) -> str:
    if profile != "auto":
        return profile
    for candidate in PROFILE_ORDER:
        if candidate in artifacts:
            return candidate
    return "auto"


def _default_output_dir(result: dict[str, Any], output_root: Path) -> Path:
    run_id = result["data"]["run_id"]
    profile = result["data"]["profile"]
    return output_root / "chatgpt_handoffs" / run_id / profile


if __name__ == "__main__":
    main()
