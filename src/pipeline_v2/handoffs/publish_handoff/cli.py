from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from src.pipeline_v2.handoffs.common import read_json, write_text_files

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a standalone publishing handoff Markdown file")
    parser.add_argument("--input-json", help="Optional prebuilt publish handoff request JSON")
    parser.add_argument("--run-id", default="current")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--output-dir")
    parser.add_argument("--allow-unapproved", action="store_true")
    args = parser.parse_args()

    if args.input_json:
        request = read_json(Path(args.input_json))
    else:
        request = _build_request_from_run(args.run_id, Path(args.output_root), args.output_dir, args.allow_unapproved)

    result = run(request)
    if result["status"] != "ok":
        raise SystemExit(result["summary"].get("error", "Publish handoff failed"))

    output_dir = Path(args.output_dir or request.get("config", {}).get("output_dir") or _default_output_dir(result, Path(args.output_root)))
    paths = write_text_files(result["data"]["publish_handoff_package"]["files"], output_dir)
    print(f"[publish_handoff] Wrote: {output_dir}")
    for path in paths:
        print(f"  {path}")


def _build_request_from_run(run_ref: str, output_root: Path, output_dir: str | None, allow_unapproved: bool) -> dict[str, Any]:
    manifest = _load_manifest(run_ref, output_root)
    run_id = manifest["run_id"]
    return {
        "run": {"run_id": run_id},
        "config": {
            "output_dir": output_dir or str(output_root / run_id / "publish_handoff"),
            "require_approved": not allow_unapproved,
        },
        "input": {
            "manifest": manifest,
            "verification_package": read_json(output_root / run_id / "L8" / "verification_package.json"),
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


def _default_output_dir(result: dict[str, Any], output_root: Path) -> Path:
    return output_root / result["data"]["run_id"] / "publish_handoff"


if __name__ == "__main__":
    main()
