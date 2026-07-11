from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a ChatGPT script response into the canonical script contract.")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    result = run(payload)
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if result.get("status") != "ok":
        raise SystemExit(result.get("summary", {}).get("failure_reason", "script parsing failed"))


if __name__ == "__main__":
    main()
