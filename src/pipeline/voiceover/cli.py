from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pipeline voiceover from an input JSON envelope.")
    parser.add_argument("--input-json", required=True, help="Path to a voiceover input JSON file.")
    args = parser.parse_args()

    input_path = Path(args.input_json)
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        result = run(payload)
    except Exception as exc:
        print(f"[voiceover] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
