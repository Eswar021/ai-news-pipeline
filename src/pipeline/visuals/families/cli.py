from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gallery import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the active visual-family gallery")
    parser.add_argument("--input-json", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    result = run(payload)
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
