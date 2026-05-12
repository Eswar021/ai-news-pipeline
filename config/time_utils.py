"""
Project-wide timezone helpers.

Generated pipeline timestamps should use the project's configured local
timezone from config/run_defaults.yaml. This keeps run manifests, layer
manifests, memory records, and human-facing logs aligned with the channel's
operating timezone.

Source-document published_at normalization remains separate and may still use
UTC where that is the canonical evidence representation.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import yaml

from config.paths import RUN_DEFAULTS_YAML

_DEFAULT_TZ = "Asia/Kolkata"


@lru_cache(maxsize=1)
def get_project_timezone_name() -> str:
    if not RUN_DEFAULTS_YAML.exists():
        return _DEFAULT_TZ

    try:
        config = yaml.safe_load(RUN_DEFAULTS_YAML.read_text(encoding="utf-8")) or {}
    except Exception:
        return _DEFAULT_TZ

    defaults = config.get("defaults", {}) if isinstance(config, dict) else {}
    timezone_name = defaults.get("timezone", _DEFAULT_TZ)
    return timezone_name or _DEFAULT_TZ


@lru_cache(maxsize=1)
def get_project_timezone() -> ZoneInfo:
    return ZoneInfo(get_project_timezone_name())


def now_project() -> datetime:
    return datetime.now(get_project_timezone())


def now_project_iso() -> str:
    return now_project().isoformat()


def now_project_file_stamp() -> str:
    return now_project().strftime("%Y%m%dT%H%M%S%f_%Z")


def to_project_timezone(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=get_project_timezone())
    return dt.astimezone(get_project_timezone())


def parse_to_project_timezone(value: str | None) -> datetime:
    if not value:
        return now_project()

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return now_project()
    return to_project_timezone(dt)


def format_project_timestamp(dt: datetime | None = None, fmt: str = "%Y-%m-%d %H:%M %Z") -> str:
    value = now_project() if dt is None else to_project_timezone(dt)
    return value.strftime(fmt)
