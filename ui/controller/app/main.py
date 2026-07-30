from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config_store import ConfigConflict, ConfigError, ConfigStore
from .job_manager import ConfirmationRequired, JobConflict, JobManager
from .models import ConfigUpdate, JobCreate, ReviewNoteUpdate, RunPlan, SLUG_RE
from .planner import PlanError, RunPlanner
from .storage import ControllerStore


def project_root_from_env() -> Path:
    configured = os.environ.get("RUN_DESK_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def create_app(
    project_root: Path | None = None,
    *,
    state_root: Path | None = None,
    pipeline_python: str | None = None,
    runner_module: str = "src.pipeline.orchestration.runner",
    config_validator: Callable[[Path], dict[str, Any]] | None = None,
) -> FastAPI:
    root = (project_root or project_root_from_env()).resolve()
    state = (state_root or root / "ui" / ".local" / "controller").resolve()
    store = ControllerStore(state)
    planner = RunPlanner(
        root,
        pipeline_python=pipeline_python,
        runner_module=runner_module,
    )
    manager = JobManager(planner, store)
    configs = ConfigStore(
        root,
        store,
        pipeline_python=planner.pipeline_python,
        validator=config_validator,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        manager.shutdown()

    app = FastAPI(
        title="AI Content Creation Run Desk Controller",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )
    app.state.project_root = root
    app.state.store = store
    app.state.planner = planner
    app.state.manager = manager
    app.state.configs = configs

    @app.get("/control/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "bind": "127.0.0.1",
            "runtime": planner.runtime_status(),
            "active_job": store.active_job(),
        }

    @app.get("/control/capabilities")
    def capabilities() -> dict[str, Any]:
        try:
            return planner.capabilities()
        except (OSError, PlanError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/control/plans/preview")
    def preview(plan: RunPlan) -> dict[str, Any]:
        try:
            return planner.preview(plan).public()
        except (OSError, PlanError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/control/runs/{run_id}/status")
    def run_status(run_id: str) -> dict[str, Any]:
        try:
            return planner.run_status(run_id)
        except (OSError, PlanError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/control/jobs")
    def jobs(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        return {
            "active_job": store.active_job(),
            "jobs": store.list_jobs(limit),
        }

    @app.post("/control/jobs")
    def create_job(request: JobCreate) -> dict[str, Any]:
        try:
            existing = store.get_job_by_request(request.request_id)
            if existing:
                return {"job": existing}
            planned = planner.preview(request.plan)
            job = manager.submit(request.request_id, planned)
            return {"job": job}
        except ConfirmationRequired as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except JobConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, PlanError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/control/jobs/{job_id}")
    def job(
        job_id: str,
        after_event_id: int = Query(0, ge=0),
        event_limit: int = Query(500, ge=1, le=1000),
    ) -> dict[str, Any]:
        value = store.get_job(job_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "job": value,
            **store.events(job_id, after=after_event_id, limit=event_limit),
        }

    @app.post("/control/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> dict[str, Any]:
        try:
            return {"job": manager.cancel(job_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/control/config/files")
    def config_files() -> dict[str, Any]:
        return {"files": configs.files()}

    @app.get("/control/config/file")
    def config_file(path: str = Query(...)) -> dict[str, Any]:
        try:
            return configs.read(path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Config file not found") from exc
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/control/config/file")
    def update_config(request: ConfigUpdate) -> dict[str, Any]:
        try:
            active = store.active_job()
            if active:
                raise JobConflict(
                    f"Config writes are locked while job {active['id']} is {active['status']}"
                )
            return configs.update(
                relative=request.path,
                expected_sha256=request.expected_sha256,
                text=request.text,
                change_summary=request.change_summary,
                confirm_write=request.confirm_write,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Config file not found") from exc
        except ConfigConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except JobConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/control/config/revisions")
    def config_revisions(
        path: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            return {"revisions": configs.revisions(path, limit)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Config file not found") from exc
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/control/notes/{run_id}")
    def note(run_id: str) -> dict[str, Any]:
        _require_run(root, run_id)
        return store.get_note(run_id)

    @app.put("/control/notes/{run_id}")
    def save_note(run_id: str, request: ReviewNoteUpdate) -> dict[str, Any]:
        _require_run(root, run_id)
        return store.save_note(run_id, status=request.status, body=request.body)

    return app


def _require_run(project_root: Path, run_id: str) -> Path:
    if not SLUG_RE.fullmatch(run_id) or run_id in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid run id")
    runs_root = (project_root / "output" / "runs").resolve()
    path = (runs_root / run_id).resolve()
    try:
        path.relative_to(runs_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid run id") from exc
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")
    return path
