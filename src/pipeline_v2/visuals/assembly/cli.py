from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble v2 visual scene clips with voiceover audio.")
    parser.add_argument("--input-json", required=True, help="Path to the video assembly input JSON.")
    args = parser.parse_args()
    input_path = Path(args.input_json)
    result = run(json.loads(input_path.read_text(encoding="utf-8")))
    if result["status"] == "failed":
        raise SystemExit(f"[video_assembly] ERROR: {result['summary'].get('failure_reason', 'failed')}")


if __name__ == "__main__":
    main()
