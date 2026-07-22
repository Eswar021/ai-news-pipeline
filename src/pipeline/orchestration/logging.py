from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time
from typing import Any, Callable, TypeVar


T = TypeVar("T")


@dataclass
class StageLogger:
    logger: logging.Logger
    run_id: str
    stage: str
    log_path: Path
    profile: str = "summary"

    def attach_paths(
        self,
        result: dict[str, Any],
        *,
        state_path: Path | None = None,
    ) -> dict[str, Any]:
        data = result.setdefault("data", {})
        if not isinstance(data, dict):
            raise TypeError("stage result data must be a dict")
        data["log_path"] = str(self.log_path)
        if state_path is not None:
            data["run_state_path"] = str(state_path)
        return result

    def run_module(
        self,
        module: str,
        function: Callable[[dict[str, Any]], T],
        input_json: dict[str, Any],
    ) -> T:
        started = time.perf_counter()
        self.logger.info("START module=%s", module)
        try:
            result = function(input_json)
        except Exception:
            duration = time.perf_counter() - started
            self.logger.exception("FAIL module=%s duration=%.2fs", module, duration)
            raise

        duration = time.perf_counter() - started
        status = str(result.get("status", "unknown")) if isinstance(result, dict) else "completed"
        summary = result.get("summary", {}) if isinstance(result, dict) else {}
        level = logging.INFO if status in {"ok", "partial", "completed"} else logging.ERROR
        details = _compact_summary(summary) if self.profile == "summary" else _json_safe(summary)
        self.logger.log(
            level,
            "END module=%s status=%s duration=%.2fs summary=%s",
            module,
            status,
            duration,
            json.dumps(details, ensure_ascii=False, separators=(",", ":")),
        )
        return result


def configure_stage_logging(
    run_context: dict[str, Any],
    stage: str,
    config: dict[str, Any] | None = None,
) -> StageLogger:
    settings = dict(config or {})
    run_id = str(run_context["run_id"])
    logs_dir = Path(run_context["run_dir"]) / "orchestration" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{stage}.log"
    logger_name = f"ai_content_creation.{run_id}.{stage}"
    logger = logging.getLogger(logger_name)
    level = _logging_level(settings.get("level", "INFO"), default=logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    if bool(settings.get("file_enabled", True)):
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=int(settings.get("max_bytes", 5_000_000)),
            backupCount=int(settings.get("backup_count", 3)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    if bool(settings.get("console_enabled", True)):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    dependency_levels = settings.get("dependency_levels") or {}
    if not isinstance(dependency_levels, dict):
        raise TypeError("orchestration.logging.dependency_levels must be a mapping")
    for dependency_name, dependency_level in dependency_levels.items():
        logging.getLogger(str(dependency_name)).setLevel(
            _logging_level(dependency_level, default=logging.WARNING)
        )

    stage_logger = StageLogger(
        logger=logger,
        run_id=run_id,
        stage=stage,
        log_path=log_path,
        profile=str(settings.get("profile", "summary")).strip().lower() or "summary",
    )
    logger.info("START stage=%s run_id=%s log=%s", stage, run_id, log_path)
    return stage_logger


def _logging_level(value: Any, *, default: int) -> int:
    if isinstance(value, int):
        return value
    resolved = logging.getLevelName(str(value).strip().upper())
    return resolved if isinstance(resolved, int) else default


def _compact_summary(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {"value": str(summary)}
    preferred = (
        "status",
        "record_count",
        "story_count",
        "selected_story_count",
        "section_count",
        "total_word_count",
        "duration_seconds",
        "scene_count",
        "rendered_scene_count",
        "failed_scene_count",
        "failure_reason",
        "error",
    )
    compact = {key: summary[key] for key in preferred if key in summary}
    return compact or {"keys": sorted(summary)[:20]}


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)
