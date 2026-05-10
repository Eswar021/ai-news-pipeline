"""
Module: raw_document_writer
Layer: 1 — Source Extraction
Purpose: Append standardized RawExtractedDocument records to raw_documents.jsonl.
         Every collector calls this after building its output — the JSONL file is
         the single Layer 1 → Layer 2 handoff artifact.

Run standalone:
    python raw_document_writer.py
"""

import sys
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_REQUIRED_FIELDS = ["raw_document_id", "run_id", "source", "item", "content", "collection"]


def write_raw_document(raw_doc: dict, output_path: Path) -> None:
    """
    Append a single RawExtractedDocument to the JSONL file.
    Creates the file and parent directories if they don't exist.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(raw_doc, ensure_ascii=False) + "\n")


def write_raw_documents(raw_docs: list, output_path: Path) -> int:
    """Append a list of RawExtractedDocuments. Returns count written."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "a", encoding="utf-8") as f:
        for doc in raw_docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    return len(raw_docs)


def read_raw_documents(raw_documents_path: Path) -> list:
    """Read all RawExtractedDocuments from a JSONL file."""
    if not raw_documents_path.exists():
        return []
    docs = []
    with open(raw_documents_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return docs


if __name__ == "__main__":
    run_id = "test_run_layer1"
    layer1_dir = RUNS_DIR / run_id / "layer_1"
    output_path = layer1_dir / "raw_documents.jsonl"

    # Clear any previous test file
    if output_path.exists():
        output_path.unlink()

    now = datetime.now(timezone.utc).isoformat()

    sample_doc = {
        "raw_document_id": "rawdoc_openai_news_test001",
        "run_id": run_id,
        "source": {
            "source_id": "openai_news",
            "source_name": "OpenAI News",
            "source_group": "ai_company_blogs",
            "source_type": "official_blog",
            "trust_tier_hint": 1,
        },
        "item": {
            "title": "OpenAI Releases GPT-5",
            "url": "https://openai.com/news/gpt-5",
            "published_at": "2026-05-10T08:00:00Z",
            "author": "OpenAI",
        },
        "content": {
            "raw_text": "GPT-5 is now available...",
            "content_available": "full",
        },
        "collection": {
            "collector_name": "official_company_blog_collector",
            "collection_method": "rss",
            "collected_at": now,
            "extraction_status": "success",
        },
    }

    write_raw_document(sample_doc, output_path)
    write_raw_document({**sample_doc, "raw_document_id": "rawdoc_openai_news_test002",
                        "item": {**sample_doc["item"], "title": "OpenAI Safety Update"}}, output_path)

    docs = read_raw_documents(output_path)
    print(f"Written {len(docs)} documents to {output_path}")
    for d in docs:
        print(f"  {d['raw_document_id']} — {d['item']['title']}")
