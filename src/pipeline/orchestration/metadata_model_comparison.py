from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from dotenv import load_dotenv
import yaml

from src.pipeline.apps.metadata_creator import run as run_metadata_creator
from src.pipeline.orchestration.io import load_json, write_json, write_jsonl


def run_comparison(
    *,
    script_result: dict[str, Any],
    video_packaging_result: dict[str, Any],
    profile: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    run_id = str((script_result.get("data") or {}).get("run_id") or "").strip()
    if not run_id:
        raise ValueError("script result is missing data.run_id")

    metadata_config = deepcopy(profile.get("metadata_creator") or {})
    channel = profile.get("channel") or {}
    metadata_config["channel"] = {
        "channel_name": channel.get("channel_name", ""),
        "content_promise": channel.get("content_promise", ""),
    }
    request = {
        "run": {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "config": metadata_config,
        "input": {
            "script_generation": script_result,
            "video_packaging": video_packaging_result,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metadata_creator_input.json", request)
    started = time.monotonic()
    try:
        result = run_metadata_creator(request)
        error = ""
    except Exception as exc:
        result = {
            "status": "failed",
            "data": {"run_id": run_id},
            "summary": {"failure_reason": f"{type(exc).__name__}: {exc}"},
            "handoff": {"ready_for_metadata_finalization": False},
            "llm_calls": [],
        }
        error = str(exc)
    duration = time.monotonic() - started

    write_json(output_dir / "metadata_creator_result.json", result)
    write_jsonl(output_dir / "llm_calls.jsonl", result.get("llm_calls") or [])
    package = (result.get("data") or {}).get("metadata_package") or {}
    if package:
        write_json(output_dir / "metadata_package.json", package)
        write_json(output_dir / "youtube_metadata.json", package.get("youtube_metadata") or {})

    summary = {
        "status": result.get("status", "failed"),
        "run_id": run_id,
        "provider": metadata_config.get("provider"),
        "model": metadata_config.get("model"),
        "duration_seconds": round(duration, 3),
        "llm_call_count": len(result.get("llm_calls") or []),
        "failure_reason": (result.get("summary") or {}).get("failure_reason") or error,
        "result_path": str((output_dir / "metadata_creator_result.json").resolve()),
    }
    write_json(output_dir / "comparison_metrics.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate metadata generation against a frozen script and video packet.")
    parser.add_argument("--script-result", required=True)
    parser.add_argument("--video-packaging-result", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pipeline-config", default="src/pipeline/config/workbench.yaml")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env", override=False)
    authoring = yaml.safe_load((root / args.pipeline_config).resolve().read_text(encoding="utf-8"))
    profile_name = authoring["default_run_profile"]
    profile = authoring["profiles"][profile_name]
    summary = run_comparison(
        script_result=load_json((root / args.script_result).resolve()),
        video_packaging_result=load_json((root / args.video_packaging_result).resolve()),
        profile=profile,
        output_dir=(root / args.output_dir).resolve(),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
