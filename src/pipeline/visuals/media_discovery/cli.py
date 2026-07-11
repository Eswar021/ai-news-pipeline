from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and download contextual media for a visual scene plan.")
    parser.add_argument("--input-json", required=True, help="Path to the visual media discovery input JSON.")
    args = parser.parse_args()
    result = run(json.loads(Path(args.input_json).read_text(encoding="utf-8")))
    if result["status"] == "failed":
        raise SystemExit(f"[visual_media_discovery] ERROR: {result['summary'].get('failure_reason', 'failed')}")


if __name__ == "__main__":
    main()
