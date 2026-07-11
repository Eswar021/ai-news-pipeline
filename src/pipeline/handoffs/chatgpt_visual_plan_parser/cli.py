from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.pipeline.handoffs.common import read_json

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a ChatGPT visual scene-plan response into a visual_scene_plan envelope")
    parser.add_argument("--input-json", required=True, help="Parser request JSON")
    args = parser.parse_args()

    request = read_json(Path(args.input_json))
    result = run(request)
    output_dir = request.get("config", {}).get("output_dir")
    if output_dir:
        _write_outputs(result, Path(output_dir))
    print(f"[chatgpt_visual_plan_parser] status={result['status']} scenes={result['summary'].get('scene_count', 0)}")
    if result["status"] != "ok":
        raise SystemExit(result["summary"].get("failure_reason", "ChatGPT visual plan parse failed"))


def _write_outputs(result: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    visual_scene_plan = result.get("data", {}).get("visual_scene_plan", {})
    paths = {
        "chatgpt_visual_plan_parse_result.json": result,
        "visual_scene_plan.json": visual_scene_plan,
        "scene_timeline.json": visual_scene_plan.get("scene_timeline", []),
        "summary.json": result.get("summary", {}),
    }
    for filename, payload in paths.items():
        (output_dir / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
