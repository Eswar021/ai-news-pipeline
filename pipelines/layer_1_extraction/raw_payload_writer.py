"""
Module: raw_payload_writer
Layer: 1 — Source Extraction
Purpose: Save the original API response / raw HTML / XML to disk as the evidence audit trail.
         Every raw document's payload is preserved here so any claim can be traced back
         to the exact original source material.

Path structure: layer1_dir/raw_payloads/{source_group}/{source_id}/{raw_document_id}.{ext}

Run standalone:
    python raw_payload_writer.py
"""

import sys
import json
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_EXT_MAP = {"html": "html", "json": "json", "xml": "xml", "text": "txt"}


def save_payload(
    run_id: str,
    raw_document_id: str,
    source_group: str,
    source_id: str,
    payload_type: str,
    payload,
    layer1_dir: Path = None,
) -> dict:
    """
    Save a raw payload to disk and return storage metadata.

    Returns:
        dict: payload_path, payload_sha256, payload_size_bytes
    """
    if layer1_dir is None:
        layer1_dir = RUNS_DIR / run_id / "layer_1"

    ext = _EXT_MAP.get(payload_type, payload_type)
    payload_dir = layer1_dir / "raw_payloads" / source_group / source_id
    payload_dir.mkdir(parents=True, exist_ok=True)

    payload_path = payload_dir / f"{raw_document_id}.{ext}"

    payload_bytes = payload if isinstance(payload, bytes) else str(payload).encode("utf-8", errors="replace")
    payload_path.write_bytes(payload_bytes)

    return {
        "payload_path": str(payload_path),
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload_size_bytes": len(payload_bytes),
    }


if __name__ == "__main__":
    run_id = "test_run_layer1"
    layer1_dir = RUNS_DIR / run_id / "layer_1"
    print(f"Testing raw_payload_writer → {layer1_dir}\n")

    r1 = save_payload(run_id, "rawdoc_openai_news_abc12345", "ai_company_blogs", "openai_news",
                      "html", "<html><h1>OpenAI news</h1></html>", layer1_dir)
    print(f"HTML: {r1['payload_path']}  ({r1['payload_size_bytes']} bytes)")

    r2 = save_payload(run_id, "rawdoc_newsapi_xyz98765", "tech_news_apis", "newsapi_ai",
                      "json", json.dumps({"articles": [{"title": "AI news"}]}), layer1_dir)
    print(f"JSON: {r2['payload_path']}  ({r2['payload_size_bytes']} bytes)")

    print("\nPayload dir contents:")
    for p in sorted(layer1_dir.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(layer1_dir)}")
