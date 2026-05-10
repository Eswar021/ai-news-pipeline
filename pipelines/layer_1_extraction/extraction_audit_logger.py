"""
Module: extraction_audit_logger
Layer: 1 — Source Extraction
Purpose: Log collector events (failures, warnings, rate limits, partial fetches) to failed_sources.jsonl.
         This is how you know whether weak output is due to weak news or broken collection.

Run standalone:
    python extraction_audit_logger.py
"""

import sys
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def log_event(
    run_id: str,
    source_id: str,
    collector_name: str,
    event_type: str,
    severity: str,
    message: str,
    output_path: Path = None,
    retryable: bool = False,
    extra: dict = None,
) -> dict:
    """
    Append a collector event to failed_sources.jsonl.

    event_type: api_error | rate_limit | empty_result | parse_error | auth_error |
                partial_content | date_missing | fetch_blocked | success_note
    severity:   error | warning | info
    """
    if output_path is None:
        output_path = RUNS_DIR / run_id / "layer_1" / "failed_sources.jsonl"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "run_id": run_id,
        "source_id": source_id,
        "collector_name": collector_name,
        "event_type": event_type,
        "severity": severity,
        "retryable": retryable,
        "message": message,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        event.update(extra)

    with open(output_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    return event


def read_events(output_path: Path) -> list:
    """Read all logged events from failed_sources.jsonl."""
    if not output_path.exists():
        return []
    events = []
    with open(output_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


if __name__ == "__main__":
    run_id = "test_run_layer1"
    output_path = RUNS_DIR / run_id / "layer_1" / "failed_sources.jsonl"

    if output_path.exists():
        output_path.unlink()

    log_event(run_id, "newsapi_ai", "tech_news_api_collector",
              "rate_limit", "warning", "Hit 100 req/day limit after 80 articles", retryable=True)

    log_event(run_id, "reddit_ai", "community_signal_collector",
              "auth_error", "error", "REDDIT_CLIENT_ID not set in .env", retryable=False)

    log_event(run_id, "arxiv_cs_ai", "research_paper_collector",
              "success_note", "info", "Fetched 25 papers from cs.AI", extra={"doc_count": 25})

    events = read_events(output_path)
    print(f"Logged {len(events)} events:\n")
    for e in events:
        icon = {"error": "❌", "warning": "⚠️", "info": "✓"}.get(e["severity"], "·")
        print(f"  {icon} [{e['severity']}] {e['source_id']}: {e['message']}")
