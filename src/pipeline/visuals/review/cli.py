from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a contact sheet for a final pipeline video.")
    parser.add_argument("--input-json", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    result = run(payload)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
