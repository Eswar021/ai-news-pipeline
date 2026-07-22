from __future__ import annotations

import argparse
from pathlib import Path

from src.pipeline.handoffs.common import read_json, write_text_files

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a manual publishing review from an explicit JSON request")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    request = read_json(Path(args.input_json))
    result = run(request)
    if result["status"] != "ok":
        raise SystemExit(result["summary"].get("error", "Publish handoff failed"))
    configured = request.get("config", {}).get("output_dir")
    output_value = args.output_dir or configured
    if not output_value:
        raise SystemExit("Provide --output-dir or config.output_dir")
    output_dir = Path(output_value)
    paths = write_text_files(result["data"]["publish_handoff_package"]["files"], output_dir)
    print(f"[publish_handoff] Wrote: {output_dir}")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
