from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a trusted visual asset catalog before scene planning.")
    parser.add_argument("--input-json", required=True, help="Path to the asset catalog input JSON.")
    args = parser.parse_args()
    input_path = Path(args.input_json)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    result = run(payload)
    output_dir = Path(payload["config"]["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog = result.get("data", {}).get("visual_asset_catalog", {})
    (output_dir / "visual_asset_catalog_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "visual_asset_catalog.json").write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(result.get("summary", {}), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if result.get("status") == "failed":
        raise SystemExit(f"[visual_asset_catalog] ERROR: {result.get('summary', {}).get('failure_reason', 'failed')}")


if __name__ == "__main__":
    main()
