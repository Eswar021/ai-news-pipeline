from __future__ import annotations

import fcntl
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from typing import Any
from uuid import uuid4

from .planner import PlannedRun, RunPlanner
from .storage import ControllerStore, now_iso


class JobConflict(RuntimeError):
    pass


class ConfirmationRequired(ValueError):
    pass


SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|password|passwd|secret|credential|cookie)\b(\s*[:=]\s*)(\S+)"
)


class JobManager:
    def __init__(self, planner: RunPlanner, store: ControllerStore) -> None:
        self.planner = planner
        self.store = store
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._guard = threading.Lock()
        self._recover()

    def submit(self, request_id: str, planned: PlannedRun) -> dict[str, Any]:
        if planned.requires_provider_confirmation and not planned.plan.confirm_provider_costs:
            raise ConfirmationRequired("Confirm possible provider costs before starting this plan")
        if planned.requires_final_confirmation and not planned.plan.confirm_final_media:
            raise ConfirmationRequired("Confirm final-media generation before starting this plan")
        runtime = self.planner.runtime_status()
        if not runtime["ready"]:
            raise ValueError(f"Pipeline runtime is not ready: {runtime['reason']}")

        with self._guard:
            existing = self.store.get_job_by_request(request_id)
            if existing:
                return existing
            active = self.store.active_job()
            if active:
                raise JobConflict(
                    f"Job {active['id']} is already {active['status']} for run {active['run_id']}"
                )
            job_id = f"job_{uuid4().hex}"
            job, created = self.store.create_job(
                job_id=job_id,
                request_id=request_id,
                operation=planned.plan.operation,
                run_id=str(planned.plan.run_id),
                plan=planned.plan.model_dump(mode="json"),
                commands=[command.public() for command in planned.commands],
            )
            if not created:
                return job
            thread = threading.Thread(
                target=self._run_job,
                args=(job_id, planned),
                name=f"run-desk-{job_id}",
                daemon=True,
            )
            self._threads[job_id] = thread
            thread.start()
            return job

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise FileNotFoundError(job_id)
        if job["status"] not in {"queued", "running", "cancelling", "orphaned"}:
            return job
        self.store.update_job(job_id, cancel_requested=1, status="cancelling")
        process = self._processes.get(job_id)
        pid = process.pid if process else job.get("pid")
        if pid:
            self._terminate_group(int(pid))
        self.store.append_event(job_id, "controller", "Cancellation requested.")
        return self.store.get_job(job_id) or job

    def shutdown(self) -> None:
        for job_id in list(self._processes):
            self.cancel(job_id)

    def _run_job(self, job_id: str, planned: PlannedRun) -> None:
        lock_file = self.store.lock_path.open("a+")
        try:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                reason = "Another Run Desk controller owns the pipeline writer lock"
                self.store.update_job(
                    job_id,
                    status="blocked",
                    failure_reason=reason,
                    finished_at=now_iso(),
                )
                self.store.append_event(job_id, "controller", reason)
                return

            self.store.update_job(job_id, status="running", started_at=now_iso())
            self.store.append_event(job_id, "controller", "Writer lock acquired.")
            for index, command in enumerate(planned.commands, start=1):
                job = self.store.get_job(job_id)
                if not job or job["cancel_requested"]:
                    self._finish_cancelled(job_id)
                    return
                self.store.update_job(
                    job_id,
                    current_step=index,
                    current_stage=command.stage,
                    pid=None,
                    exit_code=None,
                )
                self.store.append_event(job_id, "command", f"$ {command.display}")
                exit_code = self._run_command(job_id, command.argv)
                self.store.update_job(job_id, pid=None, exit_code=exit_code)
                latest = self.store.get_job(job_id)
                if latest and latest["cancel_requested"]:
                    self._finish_cancelled(job_id)
                    return
                if exit_code != 0:
                    reason = f"{command.stage} exited with status {exit_code}"
                    self.store.update_job(
                        job_id,
                        status="failed",
                        failure_reason=reason,
                        finished_at=now_iso(),
                    )
                    self.store.append_event(job_id, "controller", reason)
                    return
            self.store.update_job(
                job_id,
                status="completed",
                finished_at=now_iso(),
                failure_reason="",
                pid=None,
            )
            self.store.append_event(job_id, "controller", "Plan completed.")
        except Exception as exc:
            reason = self._sanitize(f"{type(exc).__name__}: {exc}")
            self.store.update_job(
                job_id,
                status="failed",
                failure_reason=reason,
                finished_at=now_iso(),
                pid=None,
            )
            self.store.append_event(job_id, "controller", reason)
        finally:
            self._processes.pop(job_id, None)
            self._threads.pop(job_id, None)
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    def _run_command(self, job_id: str, argv: tuple[str, ...]) -> int:
        process = subprocess.Popen(
            list(argv),
            cwd=self.planner.project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
            close_fds=True,
        )
        self._processes[job_id] = process
        self.store.update_job(job_id, pid=process.pid)
        event_count = self.store.event_count(job_id)
        truncated = False
        assert process.stdout is not None
        for line in process.stdout:
            if event_count < 20_000:
                self.store.append_event(job_id, "runner", self._sanitize(line.rstrip()))
                event_count += 1
            elif not truncated:
                self.store.append_event(
                    job_id,
                    "controller",
                    "Controller log storage reached 20,000 lines; canonical stage logs remain available in the run.",
                )
                truncated = True
            latest = self.store.get_job(job_id)
            if latest and latest["cancel_requested"] and process.poll() is None:
                self._terminate_group(process.pid)
        return process.wait()

    def _finish_cancelled(self, job_id: str) -> None:
        self.store.update_job(
            job_id,
            status="cancelled",
            finished_at=now_iso(),
            pid=None,
            failure_reason="Cancelled by the local operator",
        )
        self.store.append_event(job_id, "controller", "Job cancelled.")

    def _terminate_group(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

        def force_kill() -> None:
            time.sleep(8)
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        threading.Thread(target=force_kill, daemon=True).start()

    def _recover(self) -> None:
        for job in self.store.unfinished_jobs():
            pid = job.get("pid")
            if pid and self._runner_process_is_alive(int(pid)):
                self.store.update_job(job["id"], status="orphaned")
                self.store.append_event(
                    job["id"],
                    "controller",
                    "Controller restarted while the runner was active. The job is orphaned and can be cancelled, but completion cannot be inferred from process exit.",
                )
                threading.Thread(
                    target=self._watch_orphan,
                    args=(job["id"], int(pid)),
                    daemon=True,
                ).start()
            else:
                self.store.update_job(
                    job["id"],
                    status="interrupted",
                    finished_at=now_iso(),
                    failure_reason="Controller stopped before job completion could be observed",
                    pid=None,
                )

    def _watch_orphan(self, job_id: str, pid: int) -> None:
        while self._runner_process_is_alive(pid):
            time.sleep(2)
        job = self.store.get_job(job_id)
        if job and job["status"] in {"orphaned", "cancelling"}:
            status = "cancelled" if job["cancel_requested"] else "interrupted"
            self.store.update_job(
                job_id,
                status=status,
                finished_at=now_iso(),
                pid=None,
                failure_reason=(
                    "Cancelled after controller restart"
                    if status == "cancelled"
                    else "Runner exited after controller restart; inspect persisted run state"
                ),
            )

    def _runner_process_is_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        try:
            result = subprocess.run(
                ["/bin/ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return self.planner.runner_module in result.stdout

    def _sanitize(self, value: str) -> str:
        sanitized = value.replace(str(self.planner.project_root), "[project]")
        return SECRET_ASSIGNMENT_RE.sub(r"\1\2[redacted]", sanitized)
