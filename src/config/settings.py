import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
import yaml

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_BASE = PROJECT_ROOT / "output"
IST = timezone(timedelta(hours=5, minutes=30))


def today() -> str:
    return datetime.now(IST).date().isoformat()


def now_ist() -> datetime:
    return datetime.now(IST)


def iso_now() -> str:
    return now_ist().isoformat()


def parse_run_date(value: str | None) -> date:
    return date.fromisoformat(value) if value else now_ist().date()


def run_window_end(run_date: date) -> datetime:
    current = now_ist()
    if run_date == current.date():
        return current
    return datetime.combine(run_date, time(23, 59, 59), tzinfo=IST)


def output_dir(run_id: str) -> Path:
    return OUTPUT_BASE / run_id


def manifest_path(run_id: str) -> Path:
    return output_dir(run_id) / "run_manifest.json"


def load_manifest(run_id: str) -> dict:
    path = manifest_path(run_id)
    if not path.exists():
        raise FileNotFoundError(
            f"run_manifest.json not found for {run_id}. Run L0 first:\n"
            f"  python -m src.pipeline.L0_manifest.runner --run-profile <name>"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must deserialize to a dict: {path}")
    return raw
