from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "pipeline_orchestration_state_v1"


class RunStateStore:
    def __init__(self, run_context: dict[str, Any]) -> None:
        self.path = Path(run_context["run_dir"]) / "orchestration" / "run_state.json"
        self.run_id = str(run_context["run_id"])
        self.run_profile = str(run_context["run_profile"])

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "run_profile": self.run_profile,
                "updated_at": _now(),
                "stages": {},
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported orchestration state at {self.path}")
        if payload.get("run_id") != self.run_id:
            raise ValueError(f"Orchestration state run_id mismatch at {self.path}")
        return payload

    def start_stage(self, stage: str, modules: list[str]) -> dict[str, Any]:
        state = self.read()
        previous = dict(state.get("stages", {}).get(stage, {}))
        state.setdefault("stages", {})[stage] = {
            "status": "running",
            "started_at": _now(),
            "completed_at": None,
            "invocation_count": int(previous.get("invocation_count", 0)) + 1,
            "module_order": list(modules),
            "modules": {},
            "failure_reason": "",
        }
        return self._write(state)

    def record_module(
        self,
        stage: str,
        module: str,
        *,
        status: str,
        result_path: str = "",
        summary: dict[str, Any] | None = None,
        reused: bool = False,
    ) -> dict[str, Any]:
        state = self.read()
        stage_state = state.setdefault("stages", {}).setdefault(stage, {})
        stage_state.setdefault("modules", {})[module] = {
            "status": status,
            "recorded_at": _now(),
            "result_path": result_path,
            "reused": reused,
            "summary": deepcopy(summary or {}),
        }
        return self._write(state)

    def finish_stage(self, stage: str, *, status: str, failure_reason: str = "") -> dict[str, Any]:
        state = self.read()
        stage_state = state.setdefault("stages", {}).setdefault(stage, {})
        stage_state["status"] = status
        stage_state["completed_at"] = _now()
        stage_state["failure_reason"] = failure_reason
        return self._write(state)

    def _write(self, state: dict[str, Any]) -> dict[str, Any]:
        state["updated_at"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)
        return state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
